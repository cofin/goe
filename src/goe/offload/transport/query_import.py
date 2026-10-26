# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Query Import offload transport implementation for streaming Arrow-to-staging extraction."""

import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from goe.offload.offload_constants import (
    DBTYPE_BIGQUERY,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.offload_messages import VERBOSE
from goe.offload.offload_transport_functions import get_local_staging_path
from goe.offload.registry import create_query_import_encoder
from goe.offload.staging.arrow_writers import (
    ArrowAvroStagingWriter,
    ArrowParquetStagingWriter,
)
from goe.offload.transport.arrow_extractor import (
    ArrowExtractionConfig,
    OracleArrowStreamExtractor,
)
from goe.offload.transport.base import (
    OffloadTransport,
    convert_nans_to_nulls,
)
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
)
from goe.offload.transport.duckdb import (
    DuckDBEngine,
    DuckDBSessionConfig,
    ParquetWriteOptions,
    verify_batch_scn_invariant,
)
from goe.orchestration import command_steps

if TYPE_CHECKING:
    from goe.offload.offload_source_data import OffloadSourcePartitions

__all__ = [
    "QUERY_IMPORT_BIGQUERY_MAX_FETCH_SIZE",
    "QUERY_IMPORT_MAX_FETCH_SIZE",
    "OffloadTransportQueryImport",
    "query_import_fetch_size",
]

QUERY_IMPORT_MAX_FETCH_SIZE = 1000
QUERY_IMPORT_BIGQUERY_MAX_FETCH_SIZE = 10000


def query_import_fetch_size(requested_fetch_size: int | str, target: str) -> int:
    """Cap the Query Import array fetch size at 10000 rows for BigQuery targets and 1000 for other targets."""
    cap = QUERY_IMPORT_BIGQUERY_MAX_FETCH_SIZE if target == DBTYPE_BIGQUERY else QUERY_IMPORT_MAX_FETCH_SIZE
    return min(int(requested_fetch_size), cap)


class OffloadTransportQueryImport(OffloadTransport):
    """Stream RDBMS extraction batches via PyArrow into Parquet or Avro staging files."""

    def __init__(
        self,
        offload_source_table,
        offload_target_table,
        offload_operation,
        offload_options,
        messages,
        dfs_client,
    ):
        """Initialize the Query Import transport while preserving configured transport parallelism."""
        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        self._offload_transport_parallelism = max(1, int(getattr(self, "_offload_transport_parallelism", 1) or 1))
        self._offload_transport_fetch_size = query_import_fetch_size(self._offload_transport_fetch_size, self._target)
        self._convert_nans_to_nulls = convert_nans_to_nulls(offload_target_table, offload_operation)

    def transport(self, partition_chunk: Optional["OffloadSourcePartitions"] = None) -> int | None:
        """Run the data transport step and record staged row count and byte metrics."""
        self._reset_transport_context()

        def step_fn():
            return_values = self._query_import_to_local_fs(partition_chunk)
            if isinstance(return_values, tuple):
                rows_imported, local_staging_path, dfs_load_path = return_values
                self._query_import_copy_to_dfs(local_staging_path, dfs_load_path)
                staged_bytes = self._check_and_log_transported_files(rows_imported)
                self._transport_context[TRANSPORT_CXT_BYTES] = staged_bytes
                self._transport_context[TRANSPORT_CXT_ROWS] = rows_imported
                self._target_table.post_transport_tasks(self._staging_file)
                return rows_imported
            return return_values

        rows_imported = self._messages.offload_step(
            command_steps.STEP_STAGING_TRANSPORT, step_fn, execute=(not self._dry_run)
        )
        return rows_imported

    def ping_source_rdbms(self):
        """Raise NotImplementedError because Query Import uses the frontend RDBMS session directly."""
        raise NotImplementedError("ping_source_rdbms not implemented for QueryImport")

    def _column_type_read_remappings(self):
        """Return None because Spark JDBC type remappings do not apply to Query Import."""
        return None

    def _query_import_to_local_fs(self, partition_chunk: Any = None) -> tuple | int:
        """Extract from the source RDBMS into a local staging file via Arrow streaming."""
        if self._nothing_to_do(partition_chunk):
            return 0

        local_staging_path = get_local_staging_path(
            self._target_owner,
            self._target_table_name,
            self._offload_options,
            "." + self._staging_format.lower(),
        )
        dfs_load_path = os.path.join(self._staging_table_location, "part-m-00000." + self._staging_format.lower())
        staging_columns = self._staging_file.get_staging_columns()
        source_query = self._build_source_query(partition_chunk)
        source_binds = None

        self._refresh_rdbms_action()
        rows_imported: int | None = None
        if self._dry_run:
            self.log("Extraction sql: %s" % source_query, detail=VERBOSE)
        else:
            rows_imported = self._stream_to_local_staging_file(
                local_staging_path,
                staging_columns,
                source_query,
                source_binds,
            )

        self._check_rows_imported(rows_imported)
        return rows_imported, local_staging_path, dfs_load_path

    def _build_source_query(self, partition_chunk: Any = None) -> str:
        """Build the extraction SQL query with AS OF SCN snapshot pinning and predicate filtering."""
        colexpressions, colnames = self._build_offload_query_lists(
            convert_expressions_on_rdbms_side=self._rdbms_api.convert_query_import_expressions_on_rdbms_side(),
            for_qi=True,
        )
        sql_projection = self._sql_projection_from_offload_query_expression_list(colexpressions, colnames)
        table_name = ('"%s"."%s"' % (self._rdbms_owner, self._rdbms_table_name)).upper()
        if partition_chunk:
            split_row_source_by = self._get_transport_split_type(partition_chunk)
            row_source = self._get_transport_row_source_query(split_row_source_by, partition_chunk)
            source_query = "SELECT %s\nFROM (%s)" % (sql_projection, row_source)
        else:
            snapshot_clause = self._rdbms_api.get_snapshot_clause(
                self._offload_transport_snapshot,
                self._offload_transport_consistent_read,
            )
            if not isinstance(snapshot_clause, str):
                snapshot_clause = (
                    f" AS OF SCN {self._offload_transport_snapshot}"
                    if self._offload_transport_consistent_read and self._offload_transport_snapshot is not None
                    else ""
                )
            source_query = "SELECT %s\nFROM   %s%s" % (
                sql_projection,
                table_name,
                snapshot_clause,
            )
        if self._rdbms_offload_predicate:
            source_query += "\nWHERE (%s)" % self._rdbms_table.predicate_to_where_clause(self._rdbms_offload_predicate)
        verify_batch_scn_invariant(
            source_query,
            bool(self._offload_transport_consistent_read),
            self._offload_transport_snapshot,
        )
        return source_query

    def _stream_to_local_staging_file(
        self,
        local_staging_path: str,
        staging_columns: Sequence[Any],
        source_query: str,
        source_binds: Any,
    ) -> int:
        """Stream an Arrow RecordBatchReader from the RDBMS API into the configured staging writer."""
        base64_cols = [getattr(col, "name", str(col)) for col in (self._base64_staged_columns() or ())]
        session_commands = self._get_rdbms_session_setup_commands()
        if hasattr(self._rdbms_api, "arrow_batch_extraction"):
            with self._rdbms_api.arrow_batch_extraction(
                staging_columns,
                source_query,
                source_binds,
                self._offload_transport_fetch_size,
                self._compress_load_table,
                session_commands,
                nan_values_as_null=bool(self._convert_nans_to_nulls),
                base64_columns=base64_cols,
                source_columns=self._rdbms_columns,
            ) as reader:
                return self._write_arrow_reader(reader, local_staging_path, staging_columns, base64_cols)

        extractor = OracleArrowStreamExtractor(
            ArrowExtractionConfig(
                batch_size=int(self._offload_transport_fetch_size or 65_536),
                nan_values_as_null=bool(self._convert_nans_to_nulls),
                base64_columns=frozenset(base64_cols),
            )
        )
        with self._rdbms_api.query_import_extraction(
            staging_columns,
            source_query,
            source_binds,
            self._offload_transport_fetch_size,
            self._compress_load_table,
            session_commands,
        ) as rdbms_cursor:
            reader = extractor.from_cursor(
                rdbms_cursor,
                staging_columns,
                source_columns=self._rdbms_columns,
            )
            return self._write_arrow_reader(reader, local_staging_path, staging_columns, base64_cols)

    def _write_arrow_reader(
        self,
        reader: Any,
        local_staging_path: str,
        staging_columns: Sequence[Any],
        base64_cols: Sequence[str],
    ) -> int:
        """Write a pyarrow.RecordBatchReader to local_staging_path as Parquet or Avro."""
        if self._staging_format == FILE_STORAGE_FORMAT_PARQUET:
            engine = DuckDBEngine(
                DuckDBSessionConfig(
                    execution_key=uuid.uuid4().hex[:12],
                    parallelism=self._offload_transport_parallelism,
                )
            )
            engine.open(load_oracle=False)
            try:
                pq_writer = ArrowParquetStagingWriter(
                    engine,
                    write_options=ParquetWriteOptions(
                        compression="SNAPPY" if self._compress_load_table else "UNCOMPRESSED",
                        per_thread_output=False,
                    ),
                    staging_columns=staging_columns,
                    base64_columns=base64_cols,
                )
                manifest = pq_writer.write(reader, staging_columns, local_staging_path)
                return manifest.total_rows
            finally:
                engine.close()

        if self._staging_format == FILE_STORAGE_FORMAT_AVRO:
            schema_json = self._staging_file.get_file_schema_json(as_string=True)
            avro_writer = ArrowAvroStagingWriter(
                schema_json,
                compress=bool(self._compress_load_table),
                base64_columns=base64_cols,
                staging_columns=staging_columns,
            )
            manifest = avro_writer.write(reader, local_staging_path)
            return manifest.total_rows

        encoder = create_query_import_encoder(
            self._staging_file,
            self._messages,
            compression=self._compress_load_table,
            base64_columns=self._base64_staged_columns(),
        )
        manifest = encoder.write(reader, local_staging_path)
        return int(manifest.total_rows)

    def _query_import_copy_to_dfs(self, local_staging_path, dfs_load_path):
        """Copy the local staging file to the load location and always remove the local file afterwards."""
        self.log_dfs_cmd('copy_from_local("%s", "%s")' % (local_staging_path, dfs_load_path))
        if not self._dry_run:
            try:
                self._dfs_client.copy_from_local(local_staging_path, dfs_load_path, overwrite=True)
            finally:
                Path(local_staging_path).unlink(missing_ok=True)
