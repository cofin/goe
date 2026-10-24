#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadTransportMSSQLApi: Library for logic/interaction with source MSSQL system during offload transport."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from goe.offload.column_metadata import ColumnMetadataInterface
from goe.offload.offload_constants import OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED
from goe.offload.offload_source_data import OffloadSourcePartitions
from goe.offload.offload_source_table import OffloadSourceTableInterface
from goe.offload.offload_transport_rdbms_api import OffloadTransportRdbmsApiInterface
from goe.util.string_utils import id_generator

if TYPE_CHECKING:
    pass


class OffloadTransportMSSQLApi(OffloadTransportRdbmsApiInterface):
    """MSSQL specific methods"""

    def __init__(
        self,
        rdbms_owner,
        rdbms_table_name,
        offload_options,
        messages,
        dry_run=False,
    ):
        super().__init__(
            rdbms_owner,
            rdbms_table_name,
            offload_options,
            messages,
            dry_run=dry_run,
        )
        self.debug("OffloadTransportMSSQLApi setup: (%s, %s)" % (rdbms_owner, rdbms_table_name))

    def generate_transport_action(self):
        id_str = id_generator()
        return "%s_%s" % (id_str, self._rdbms_table_name.lower())

    def get_id_column_for_range_splitting(
        self,
        rdbms_table: OffloadSourceTableInterface,
    ) -> ColumnMetadataInterface:
        raise NotImplementedError("MSSQL get_id_column_for_range_splitting() pending implementation")

    def get_id_range(
        self,
        rdbms_col_name: str,
        predicate_offload_clause: str = "",
        partition_chunk: Any = None,
    ) -> tuple[Any, ...]:
        raise NotImplementedError("MSSQL get_id_range() pending implementation")

    def get_rdbms_query_cast(
        self,
        column_expression,
        rdbms_column,
        staging_column,
        max_ts_scale,
        convert_expressions_on_rdbms_side=False,
        for_spark=False,
        nan_values_as_null=False,
        for_qi=False,
    ):
        """Returns an expression suitable for reading a specific column from the RDBMS table"""
        raise NotImplementedError("MSSQL get_rdbms_query_cast() pending implementation")

    def get_rdbms_session_setup_commands(
        self,
        module: Any,
        action: Any,
        custom_session_parameters: Any,
        for_plsql: bool = False,
        include_semi_colons: bool = False,
        escape_semi_colons: bool = False,
        max_ts_scale: Any = None,
    ) -> list[Any]:
        raise NotImplementedError("MSSQL get_rdbms_session_setup_commands() not implemented.")

    def get_rdbms_session_setup_hint(self, custom_session_parameters, max_ts_scale):
        """No session setup hints required on MSSQL"""
        return ""

    def get_snapshot_clause(self, transport_scn: int, consistent_read: bool) -> str:
        return ""

    def get_transport_split_type(
        self,
        partition_chunk: OffloadSourcePartitions,
        rdbms_table: OffloadSourceTableInterface,
        parallelism: int,
        rdbms_partition_type: str,
        offload_by_subpartition: bool,
        predicate_offload_clause: str,
        native_range_split_available: bool = False,
    ) -> tuple[Any, ...]:
        raise NotImplementedError("MSSQL get_transport_split_type() not implemented.")

    def get_transport_row_source_query(
        self,
        partition_by_prm: Any,
        rdbms_table: Any,
        consistent_read: bool,
        transport_scn: int,
        parallelism: Any,
        offload_by_subpartition: Any,
        mod_column: Any,
        predicate_offload_clause: Any,
        partition_chunk: Any = None,
        pad: Any = None,
        id_col_min: Any = None,
        id_col_max: Any = None,
    ) -> str:
        raise NotImplementedError("MSSQL get_transport_row_source_query() not implemented.")

    def get_transport_row_source_query_hint_block(self) -> str:
        raise NotImplementedError("MSSQL get_transport_row_source_query_hint_block() not implemented.")

    def jdbc_driver_name(self):
        return None

    def jdbc_url(self) -> str:
        return '"jdbc:sqlserver://' + (self._offload_transport_dsn or "") + '"'

    def log_sql_stats(
        self,
        module,
        action,
        payload,
        validation_polling_interval=OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED,
    ):
        raise NotImplementedError("MSSQL log_sql_stats() not implemented.")

    def get_rdbms_canary_query(self):
        return "SELECT 1"

    @contextmanager
    def query_import_extraction(
        self,
        staging_columns,
        source_query,
        source_binds,
        fetch_size,
        compress,
        rdbms_session_setup_commands,
    ):
        raise NotImplementedError("MSSQL query_import_extraction() not implemented")
