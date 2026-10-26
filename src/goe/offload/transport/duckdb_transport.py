# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Opt-in DuckDB 2.0 offload transport: Oracle batches streamed to cloud Parquet via shared DuckDBEngine."""

import shutil
import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
from google.auth.transport.requests import Request

from goe.config.gcp_credentials import resolve_gcp_credentials
from goe.observability.transport import submit_with_context, traced_transport_batch
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_transport_rdbms_api import (
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
)
from goe.offload.transport.constants import TRANSPORT_CXT_BYTES, TRANSPORT_CXT_ROWS
from goe.offload.transport.duckdb.engine import (
    CloudStorageSecretSpec,
    DuckDBEngine,
    DuckDBSessionConfig,
    build_cast_projection,
    verify_batch_scn_invariant,
)
from goe.offload.transport.duckdb.oracle_pushdown import (
    OracleExtensionTransport,
    OracleFallbackAssessment,
    OraclePushdownPlan,
)
from goe.offload.transport.duckdb.parquet_writer import (
    DuckDBParquetWriter,
    ParquetCompression,
    ParquetWriteOptions,
)
from goe.offload.transport.duckdb_constants import DUCKDB_GCS_SCOPE, OFFLOAD_TRANSPORT_METHOD_DUCKDB
from goe.offload.transport.protocol import OffloadTransportException
from goe.offload.transport.spark.polling import OffloadTransport, convert_nans_to_nulls
from goe.orchestration import command_steps

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.filesystem.goe_dfs import GOEDfs
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_data import OffloadSourcePartitions
    from goe.offload.offload_source_table import OffloadSourceTableInterface

DUCKDB_MIN_ORACLE_CONNECTION_LIMIT = 8


class OffloadTransportDuckDB(OffloadTransport):
    """Transport Oracle data to cloud Parquet with a shared in-process DuckDB 2.0 engine."""

    def __init__(
        self,
        offload_source_table: "OffloadSourceTableInterface",
        offload_target_table: "BackendTableInterface",
        offload_operation: Any,
        offload_options: "OrchestrationConfig",
        messages: "OffloadMessages",
        dfs_client: "GOEDfs",
        *,
        arrow_fallback_runner: Callable[[list[str], str, str], int] | None = None,
    ) -> None:
        """Initialise base transport state, NaN handling, and DuckDB 2.0 session configuration."""
        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_DUCKDB
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        self._convert_nans_to_nulls = convert_nans_to_nulls(offload_target_table, offload_operation)
        self._duckdb_temp_root = offload_options.offload_transport_duckdb_temp_directory
        self._session_config = DuckDBSessionConfig(
            execution_key=uuid.uuid4().hex[:12],
            parallelism=max(1, int(self._offload_transport_parallelism or 1)),
            memory_limit_override=offload_options.offload_transport_duckdb_memory_limit,
            threads_override=offload_options.offload_transport_duckdb_threads,
            temp_directory=self._duckdb_temp_root or "/tmp/goe_duckdb",
            extension_repository=offload_options.offload_transport_duckdb_extension_repository,
            extension_directory=offload_options.offload_transport_duckdb_extension_dir,
            extension_path=offload_options.offload_transport_duckdb_extension_path,
        )
        self._arrow_fallback_runner = arrow_fallback_runner
        self._shared_engine: DuckDBEngine | None = None

    def assess_fallback(self, *, has_oci_library: bool | None = None) -> OracleFallbackAssessment:
        """Return whether the source table requires Arrow fallback instead of duckdb-oracle pushdown."""
        columns = getattr(self, "_rdbms_columns", None) or []
        effective_oci = getattr(self, "_has_oci_library", has_oci_library)
        return OracleExtensionTransport.assess_table_eligibility(columns, has_oci_library=effective_oci)

    def transport(self, partition_chunk: "OffloadSourcePartitions | None" = None) -> int | None:
        """Extract every batch to canonical Parquet URIs, then hand the staged files to the backend load table."""
        self._reset_transport_context()

        def step_fn() -> int | None:
            if self._nothing_to_do(partition_chunk):
                return 0
            self._refresh_rdbms_action()
            cast_projection = build_cast_projection(self._staging_file.get_staging_columns())
            compression: ParquetCompression = "SNAPPY" if self._compress_load_table else "UNCOMPRESSED"
            staging_uri = self._staging_table_location.rstrip("/")
            batch_queries = self._batch_oracle_queries(partition_chunk)
            plan = OraclePushdownPlan(
                batch_queries=tuple(batch_queries),
                cast_projection=cast_projection,
                consistent_read=bool(self._offload_transport_consistent_read),
                snapshot_scn=self._offload_transport_snapshot,
            )
            pushdown = OracleExtensionTransport(DuckDBEngine(self._default_session_config()))
            writer = DuckDBParquetWriter(ParquetWriteOptions(compression=compression, per_thread_output=False))
            copy_sqls: list[str] = []
            for batch, oracle_sql in enumerate(batch_queries):
                target_uri = f"{staging_uri}/part-{batch:05d}.parquet"
                self.log(f"DuckDB batch {batch} extraction SQL: {oracle_sql}", detail=VERBOSE)
                self.log(f"DuckDB batch {batch} target: {target_uri}", detail=VERBOSE)
                relation_sql = pushdown.build_oracle_query_relation_sql(plan, batch)
                copy_sqls.append(writer.build_copy_sql(relation_sql, target_uri))
            rows_imported: int | None = None
            if not self._dry_run:
                fallback_runner = getattr(self, "_arrow_fallback_runner", None)
                assessment = self.assess_fallback(has_oci_library=True if fallback_runner is None else None)
                if assessment.requires_arrow_fallback and fallback_runner is not None:
                    for reason in assessment.reasons:
                        self.log(f"DuckDB transport routing to Arrow fallback: {reason}", detail=VERBOSE)
                    rows_imported = fallback_runner(batch_queries, staging_uri, compression)
                else:
                    rows_imported = self._run_batches(copy_sqls)
                self.log(f"DuckDB transport rows staged: {rows_imported}", detail=VVERBOSE)
            self._check_rows_imported(rows_imported)
            self._transport_context[TRANSPORT_CXT_BYTES] = self._check_and_log_transported_files(rows_imported)
            self._transport_context[TRANSPORT_CXT_ROWS] = rows_imported
            self._target_table.post_transport_tasks(self._staging_file)
            return rows_imported

        rows: int | None = self._messages.offload_step(
            command_steps.STEP_STAGING_TRANSPORT, step_fn, execute=not self._dry_run
        )
        return rows

    def ping_source_rdbms(self) -> None:
        """Not supported: DuckDB connectivity is exercised by the transport itself."""
        raise NotImplementedError("ping_source_rdbms not implemented for DUCKDB transport")

    def _default_session_config(self, temp_directory: str | None = None) -> DuckDBSessionConfig:
        """Return the active DuckDBSessionConfig or construct one for partially initialized test doubles."""
        existing = getattr(self, "_session_config", None)
        if isinstance(existing, DuckDBSessionConfig):
            if temp_directory is None:
                return existing
            return DuckDBSessionConfig(
                execution_key=existing.execution_key,
                parallelism=existing.parallelism,
                configured_memory_bytes=existing.configured_memory_bytes,
                memory_limit_override=existing.memory_limit_override,
                threads_override=existing.threads_override,
                temp_directory=temp_directory,
                max_temp_directory_size=existing.max_temp_directory_size,
                extension_repository=existing.extension_repository,
                extension_directory=existing.extension_directory,
                extension_path=existing.extension_path,
                oracle_array_size=existing.oracle_array_size,
                oracle_call_timeout_ms=existing.oracle_call_timeout_ms,
            )
        return DuckDBSessionConfig(
            execution_key=uuid.uuid4().hex[:12],
            parallelism=max(1, int(getattr(self, "_offload_transport_parallelism", 1) or 1)),
            temp_directory=temp_directory or getattr(self, "_duckdb_temp_root", None) or "/tmp/goe_duckdb",
        )

    def _batch_split(self, partition_chunk: "OffloadSourcePartitions | None") -> tuple[str, int | None, int | None]:
        """Return the split type and optional id range, switching to MOD when the id range is blank."""
        split_type = self._get_transport_split_type(partition_chunk)
        if split_type != TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE:
            return split_type, None, None
        id_column = self._rdbms_api.get_id_column_for_range_splitting(self._rdbms_table)
        predicate = self._rdbms_table.predicate_to_where_clause(self._rdbms_offload_predicate)
        id_min, id_max = self._rdbms_api.get_id_range(id_column.name, predicate, partition_chunk=partition_chunk)
        if id_min is None or id_max is None:
            return TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD, None, None
        return split_type, id_min, id_max

    def _batch_oracle_queries(self, partition_chunk: "OffloadSourcePartitions | None") -> list[str]:
        """Return one Oracle query per batch, filtered on goe_offload_batch and verified against the transport SCN."""
        split_type, id_min, id_max = self._batch_split(partition_chunk)
        colexpressions, colnames = self._build_offload_query_lists(convert_expressions_on_rdbms_side=True, for_qi=True)
        projection = self._sql_projection_from_offload_query_expression_list(colexpressions, colnames, no_newlines=True)
        row_source = self._get_transport_row_source_query(
            split_type, partition_chunk, id_col_min=id_min, id_col_max=id_max
        )
        hint = self._rdbms_api.get_rdbms_session_setup_hint(
            self._offload_transport_rdbms_session_parameters, self._get_max_ts_scale()
        )
        alias = self._rdbms_table.enclose_identifier(self._rdbms_table_name)
        queries = []
        for batch in range(self._offload_transport_parallelism):
            sql = (
                f"SELECT {hint} /* {self._rdbms_action} */ {projection} FROM ({row_source}) {alias} "
                f"WHERE {alias}.{TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN} = {batch}"
            )
            verify_batch_scn_invariant(
                sql, bool(self._offload_transport_consistent_read), self._offload_transport_snapshot
            )
            queries.append(sql)
        return queries

    def _gcs_access_token(self) -> tuple[str, str | None]:
        """Return a freshly minted OAuth2 access token and project from GOE's central GCP credential resolver."""
        bundle = resolve_gcp_credentials(self._offload_options, scopes=[DUCKDB_GCS_SCOPE])
        bundle.credentials.refresh(Request())
        return str(bundle.credentials.token or ""), bundle.project

    def _open_shared_engine(self, run_dir: Path, access_token: str) -> DuckDBEngine:
        """Open a single shared DuckDBEngine for the run, attach Oracle, and clear the metadata cache."""
        session_cfg = self._default_session_config(temp_directory=str(run_dir))
        engine = DuckDBEngine(session_cfg)
        cloud_secret = CloudStorageSecretSpec(scheme="gs", bearer_token=access_token) if access_token else None
        try:
            conn = engine.open(load_oracle=True, cloud_secret=cloud_secret)
            options = getattr(self, "_offload_options", None)
            dsn = str(getattr(self, "_offload_transport_dsn", "") or "")
            OracleExtensionTransport(engine).prepare_session(
                conn,
                user=getattr(options, "rdbms_app_user", None),
                password=getattr(options, "rdbms_app_pass", None),
                dsn=dsn,
                wallet_path=getattr(options, "oracle_wallet_location", None),
            )
            return engine
        except duckdb.Error as exc:
            engine.close()
            raise OffloadTransportException(f"DuckDB transport initialization failed: {exc}") from exc

    def _run_batch(self, batch: int, copy_sql: str, access_token: str, project_id: str | None, run_dir: Path) -> int:
        """Execute one batch COPY statement over a worker cursor from the shared DuckDBEngine."""
        del access_token, project_id, run_dir
        engine = getattr(self, "_shared_engine", None)
        if engine is None:
            raise OffloadTransportException(f"DuckDB transport batch {batch} failed: shared DuckDBEngine is not open")
        try:
            with engine.cursor() as cursor:
                row = cursor.execute(copy_sql).fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except duckdb.Error as exc:
            raise OffloadTransportException(f"DuckDB transport batch {batch} failed: {exc}") from exc

    def _run_batch_traced(
        self, batch: int, copy_sql: str, access_token: str, project_id: str | None, run_dir: Path
    ) -> int:
        """Run ``_run_batch`` inside a ``goe.transport.duckdb.batch`` span and record the rows written."""
        with traced_transport_batch(self.get_transport_method(), batch) as batch_op:
            rows = self._run_batch(batch, copy_sql, access_token, project_id, run_dir)
            if batch_op.span.is_recording():
                batch_op.span.set_attribute("goe.transport.batch.rows", rows)
            return rows

    def _run_batches(self, copy_sqls: list[str]) -> int:
        """Run all batches concurrently over a single shared DuckDBEngine and clean up the spill directory."""
        access_token, project_id = self._gcs_access_token()
        temp_root = getattr(self, "_duckdb_temp_root", None) or tempfile.gettempdir()
        Path(temp_root).mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="goe_duckdb_", dir=temp_root))
        custom_batch_fn = "_run_batch" in self.__dict__
        self._shared_engine = None
        try:
            if not custom_batch_fn:
                self._shared_engine = self._open_shared_engine(run_dir, access_token)
            with ThreadPoolExecutor(max_workers=max(1, len(copy_sqls))) as executor:
                futures = [
                    submit_with_context(executor, self._run_batch_traced, batch, sql, access_token, project_id, run_dir)
                    for batch, sql in enumerate(copy_sqls)
                ]
                return sum(future.result() for future in futures)
        finally:
            if self._shared_engine is not None:
                self._shared_engine.close()
                self._shared_engine = None
            shutil.rmtree(run_dir, ignore_errors=True)
