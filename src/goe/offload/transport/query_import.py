# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Query Import offload transport implementation for direct RDBMS-to-staging extraction."""

import os
from typing import TYPE_CHECKING, Any, Optional

from goe.offload.factory.query_import_factory import query_import_factory
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_transport_functions import (
    get_local_staging_path,
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
from goe.orchestration import command_steps

if TYPE_CHECKING:
    from goe.offload.offload_source_data import OffloadSourcePartitions


class OffloadTransportQueryImport(OffloadTransport):
    """Use Python to transport data, only suitable for small chunks"""

    def __init__(
        self,
        offload_source_table,
        offload_target_table,
        offload_operation,
        offload_options,
        messages,
        dfs_client,
    ):
        """CONSTRUCTOR

        Cap fetch size at 1000
        """
        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        self._offload_transport_parallelism = 1
        self._offload_transport_fetch_size = min(int(self._offload_transport_fetch_size), 1000)
        self._convert_nans_to_nulls = convert_nans_to_nulls(offload_target_table, offload_operation)

    def transport(self, partition_chunk: Optional["OffloadSourcePartitions"] = None) -> int | None:
        """Run the data transport"""
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

        rows_imported = self._messages.offload_step(
            command_steps.STEP_STAGING_TRANSPORT, step_fn, execute=(not self._dry_run)
        )
        return rows_imported

    def ping_source_rdbms(self):
        raise NotImplementedError("ping_source_rdbms not implemented for QueryImport")

    def _column_type_read_remappings(self):
        """Not applicable to Query Import"""
        return None

    def _query_import_to_local_fs(self, partition_chunk: Any = None) -> tuple | int:
        """Execute Query Import transport.

        Query Import is not partition aware therefore partition_chunk is ignored
        """

        if self._nothing_to_do(partition_chunk):
            return 0

        local_staging_path = get_local_staging_path(
            self._target_owner,
            self._target_table_name,
            self._offload_options,
            "." + self._staging_format.lower(),
        )
        dfs_load_path = os.path.join(self._staging_table_location, "part-m-00000." + self._staging_format.lower())
        qi_fetch_size = self._offload_transport_fetch_size if self._fetchmany_takes_fetch_size else None

        staging_columns = self._staging_file.get_staging_columns()

        if self._offload_transport_consistent_read:
            self.log(
                "Ignoring --offload-transport-consistent-read for serial transport task",
                detail=VVERBOSE,
            )

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
            source_query = "SELECT %s\nFROM   %s%s" % (
                sql_projection,
                table_name,
                snapshot_clause,
            )
        if self._rdbms_offload_predicate:
            source_query += "\nWHERE (%s)" % self._rdbms_table.predicate_to_where_clause(self._rdbms_offload_predicate)
        source_binds = None

        self._refresh_rdbms_action()
        rows_imported = None
        if self._dry_run:
            self.log("Extraction sql: %s" % source_query, detail=VERBOSE)
        else:
            encoder = query_import_factory(
                self._staging_file,
                self._messages,
                compression=self._compress_load_table,
                base64_columns=self._base64_staged_columns(),
            )
            with self._rdbms_api.query_import_extraction(
                staging_columns,
                source_query,
                source_binds,
                self._offload_transport_fetch_size,
                self._compress_load_table,
                self._get_rdbms_session_setup_commands(),
            ) as rdbms_cursor:
                rows_imported = encoder.write_from_cursor(
                    local_staging_path, rdbms_cursor, self._rdbms_columns, qi_fetch_size
                )

        self._check_rows_imported(rows_imported)
        return rows_imported, local_staging_path, dfs_load_path

    def _query_import_copy_to_dfs(self, local_staging_path, dfs_load_path):
        """Simulate Sqoop's use of recreate load dir"""
        rm_local_file = ["rm", "-f", local_staging_path]
        self.log_dfs_cmd('copy_from_local("%s", "%s")' % (local_staging_path, dfs_load_path))
        if not self._dry_run:
            self._dfs_client.copy_from_local(local_staging_path, dfs_load_path, overwrite=True)
            self._run_os_cmd(rm_local_file)
