# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Opt-in DuckDB offload transport: Oracle batches streamed to GCS Parquet via duckdb-oracle and gcs."""

import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
from google.auth.transport.requests import Request

from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_transport_rdbms_api import (
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
)
from goe.offload.transport.base import OffloadTransport, OffloadTransportException, convert_nans_to_nulls
from goe.offload.transport.constants import TRANSPORT_CXT_BYTES, TRANSPORT_CXT_ROWS
from goe.offload.transport.duckdb_constants import DUCKDB_GCS_SCOPE, OFFLOAD_TRANSPORT_METHOD_DUCKDB
from goe.offload.transport.duckdb_engine import (
    DuckDBTransportSettings,
    attach_oracle,
    build_batch_copy_sql,
    build_cast_projection,
    create_gcs_token_secret,
    load_gcs_extension,
    load_oracle_extension,
    open_batch_connection,
    parse_ezconnect_dsn,
    to_duckdb_gcs_uri,
    verify_batch_scn_invariant,
)
from goe.orchestration import command_steps
from goe.util.gcp_credentials import resolve_gcp_credentials

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.filesystem.goe_dfs import GOEDfs
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_data import OffloadSourcePartitions
    from goe.offload.offload_source_table import OffloadSourceTableInterface

DUCKDB_MIN_ORACLE_CONNECTION_LIMIT = 8


class OffloadTransportDuckDB(OffloadTransport):
    """Transport Oracle data to GCS Parquet with in-process DuckDB, duckdb-oracle and the community gcs extension."""

    def __init__(
        self,
        offload_source_table: "OffloadSourceTableInterface",
        offload_target_table: "BackendTableInterface",
        offload_operation: Any,
        offload_options: "OrchestrationConfig",
        messages: "OffloadMessages",
        dfs_client: "GOEDfs",
    ) -> None:
        """Initialise base transport state, NaN handling and DuckDB resource settings."""
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
        self._duckdb_settings = DuckDBTransportSettings(
            threads=offload_options.offload_transport_duckdb_threads,
            memory_limit=offload_options.offload_transport_duckdb_memory_limit,
            extension_repository=offload_options.offload_transport_duckdb_extension_repository,
            extension_dir=offload_options.offload_transport_duckdb_extension_dir,
            extension_path=offload_options.offload_transport_duckdb_extension_path,
        )
        self._duckdb_temp_root = offload_options.offload_transport_duckdb_temp_directory

    def transport(self, partition_chunk: "OffloadSourcePartitions | None" = None) -> int | None:
        """Extract every batch to gcss:// Parquet, then hand the staged files to the backend load table."""
        self._reset_transport_context()

        def step_fn() -> int | None:
            if self._nothing_to_do(partition_chunk):
                return 0
            self._refresh_rdbms_action()
            cast_projection = build_cast_projection(self._staging_file.get_staging_columns())
            compression = "SNAPPY" if self._compress_load_table else "UNCOMPRESSED"
            staging_uri = to_duckdb_gcs_uri(self._staging_table_location.rstrip("/"))
            copy_sqls = []
            for batch, oracle_sql in enumerate(self._batch_oracle_queries(partition_chunk)):
                target_uri = f"{staging_uri}/part-{batch:05d}.parquet"
                self.log(f"DuckDB batch {batch} extraction SQL: {oracle_sql}", detail=VERBOSE)
                self.log(f"DuckDB batch {batch} target: {target_uri}", detail=VERBOSE)
                copy_sqls.append(build_batch_copy_sql(cast_projection, oracle_sql, target_uri, compression))
            rows_imported = None
            if not self._dry_run:
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

    def _run_batch(self, batch: int, copy_sql: str, access_token: str, project_id: str | None, run_dir: Path) -> int:
        """Run one COPY on a fresh DuckDB connection and return the number of rows written.

        A fresh connection per batch is required because the gcs extension caches its storage client per connection.
        """
        ezconnect = parse_ezconnect_dsn(self._offload_transport_dsn)
        if ezconnect is None:
            raise OffloadTransportException(
                f"DUCKDB transport requires an EZConnect DSN: {self._offload_transport_dsn}"
            )
        batch_temp = run_dir / f"batch_{batch:05d}"
        batch_temp.mkdir(parents=True, exist_ok=True)
        conn = open_batch_connection(self._duckdb_settings, str(batch_temp))
        try:
            load_oracle_extension(conn, self._duckdb_settings)
            load_gcs_extension(conn)
            conn.execute(
                "SET oracle_connection_limit = %s"
                % max(DUCKDB_MIN_ORACLE_CONNECTION_LIMIT, self._offload_transport_parallelism)
            )
            attach_oracle(
                conn,
                self._offload_options.rdbms_app_user or "",
                self._offload_options.rdbms_app_pass or "",
                ezconnect,
            )
            create_gcs_token_secret(conn, access_token, project_id)
            row = conn.execute(copy_sql).fetchone()
            return int(row[0]) if row else 0
        except duckdb.Error as exc:
            raise OffloadTransportException(f"DuckDB transport batch {batch} failed: {exc}") from exc
        finally:
            conn.close()

    def _run_batches(self, copy_sqls: list[str]) -> int:
        """Run all batches concurrently in a private spill directory that is always removed."""
        os.environ["ORA_SDTZ"] = "UTC"
        access_token, project_id = self._gcs_access_token()
        temp_root = self._duckdb_temp_root or tempfile.gettempdir()
        Path(temp_root).mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="goe_duckdb_", dir=temp_root))
        try:
            with ThreadPoolExecutor(max_workers=len(copy_sqls)) as executor:
                futures = [
                    executor.submit(self._run_batch, batch, sql, access_token, project_id, run_dir)
                    for batch, sql in enumerate(copy_sqls)
                ]
                return sum(future.result() for future in futures)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
