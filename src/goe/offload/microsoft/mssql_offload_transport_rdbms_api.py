# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadTransportMSSQLApi: Library for logic/interaction with source MSSQL system during offload transport."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from goe.offload.offload_constants import OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED
from goe.offload.offload_source_table import OffloadSourceTableInterface
from goe.offload.offload_transport_rdbms_api import OffloadTransportRdbmsApiInterface
from goe.offload.schema.column_spec import ColumnSpec
from goe.orchestration.models import OffloadSourcePartitions
from goe.util.string_utils import id_generator


class OffloadTransportMSSQLApi(OffloadTransportRdbmsApiInterface):
    """MSSQL-specific transport RDBMS API methods."""

    def __init__(
        self,
        rdbms_owner: str,
        rdbms_table_name: str,
        offload_options: Any,
        messages: Any,
        dry_run: bool = False,
    ) -> None:
        """Initialize OffloadTransportMSSQLApi for a source SQL Server table."""
        super().__init__(
            rdbms_owner,
            rdbms_table_name,
            offload_options,
            messages,
            dry_run=dry_run,
        )
        self.debug(f"OffloadTransportMSSQLApi setup: ({rdbms_owner}, {rdbms_table_name})")

    def generate_transport_action(self) -> str:
        """Generate a unique transport action identifier for the target table."""
        id_str = id_generator()
        return f"{id_str}_{self._rdbms_table_name.lower()}"

    def get_id_column_for_range_splitting(
        self,
        rdbms_table: OffloadSourceTableInterface,
    ) -> ColumnSpec:
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
        column_expression: str,
        rdbms_column: Any,
        staging_column: Any,
        max_ts_scale: int | None,
        convert_expressions_on_rdbms_side: bool = False,
        for_spark: bool = False,
        nan_values_as_null: bool = False,
        for_qi: bool = False,
    ) -> str:
        """Return an expression suitable for reading a specific column from the RDBMS table."""
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

    def get_rdbms_session_setup_hint(self, custom_session_parameters: Any, max_ts_scale: Any) -> str:
        """Return empty session setup hints for MSSQL."""
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

    def jdbc_driver_name(self) -> str:
        return ""

    def jdbc_url(self) -> str:
        return '"jdbc:sqlserver://' + (self._offload_transport_dsn or "") + '"'

    def log_sql_stats(
        self,
        module: Any,
        action: Any,
        payload: Any,
        validation_polling_interval: int = OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED,
    ) -> Any:
        raise NotImplementedError("MSSQL log_sql_stats() not implemented.")

    def get_rdbms_canary_query(self) -> str:
        return "SELECT 1"

    @contextmanager
    def query_import_extraction(
        self,
        staging_columns: list[Any],
        source_query: str,
        source_binds: Any,
        fetch_size: int,
        compress: bool,
        rdbms_session_setup_commands: list[str],
    ) -> Iterator[Any]:
        raise NotImplementedError("MSSQL query_import_extraction() not implemented")
