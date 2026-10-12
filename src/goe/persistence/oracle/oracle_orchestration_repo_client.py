#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0


"""OracleOrchestrationRepoClient: Oracle implementation of API for get/put of orchestration metadata."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import msgspec
import oracledb

from goe.offload.factory.offload_source_table_factory import OffloadSourceTable
from goe.offload.offload_constants import (
    BACKEND_DISTRO_CDH,
    BACKEND_DISTRO_GCP,
    BACKEND_DISTRO_MSAZURE,
    BACKEND_DISTRO_SNOWFLAKE,
)
from goe.offload.offload_messages import QUIET, VERBOSE, VVERBOSE, OffloadMessages
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.oracle_gateway import OracleGateway, load_sql_file
from goe.persistence.orchestration_metadata import (
    COMMAND_EXECUTION,
    HADOOP_OWNER,
    HADOOP_TABLE,
    INCREMENTAL_HIGH_VALUE,
    INCREMENTAL_KEY,
    INCREMENTAL_PREDICATE_TYPE,
    INCREMENTAL_PREDICATE_VALUE,
    INCREMENTAL_RANGE,
    OFFLOAD_BUCKET_COLUMN,
    OFFLOAD_PARTITION_FUNCTIONS,
    OFFLOAD_SNAPSHOT,
    OFFLOAD_SORT_COLUMNS,
    OFFLOAD_TYPE,
    OFFLOADED_OWNER,
    OFFLOADED_TABLE,
    OrchestrationMetadata,
)
from goe.persistence.orchestration_repo_client import (
    OrchestrationRepoClientInterface,
)
from goe.persistence.schemas import (
    ColumnDetail,
    CommandExecutionRow,
    CommandExecutionStepRow,
    OffloadableSchemaRow,
    PartitionDetail,
    SchemaTableRow,
    SubPartitionDetail,
)
from goe.util.json_tools import deserialize_object, serialize_object

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.offload_messages import OffloadMessages


OFFLOAD_METADATA_ORA_TYPE_NAME = "OFFLOAD_METADATA_OT"
OFFLOAD_PARTITION_ORA_TYPE_NAME = "OFFLOAD_PARTITION_OT"
OFFLOAD_PARTITIONS_ORA_TYPE_NAME = "OFFLOAD_PARTITION_NTT"

METADATA_SOURCE_TYPE_VIEW = "VIEW"
ORACLE_REPO_SQL_PATH = Path(__file__).resolve().parents[1] / "sql" / "oracle_repo.sql"


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OracleOrchestrationRepoClient(OrchestrationRepoClientInterface):
    """OracleOrchestrationRepoClient: Oracle implementation of API for get/put of orchestration metadata"""

    def __init__(
        self,
        connection_options: "OrchestrationConfig",
        messages: "OffloadMessages",
        dry_run: bool = False,
        trace_action: str | None = None,
    ) -> None:
        super().__init__(connection_options, messages, dry_run=dry_run, trace_action=trace_action)
        self._repo_user = self._connection_options.ora_repo_user
        self._repo_gateway: OracleGateway | None = None

    def set_offload_metadata(
        self,
        metadata: dict | OrchestrationMetadata,
    ) -> None:
        self._set_metadata(metadata)

    def drop_offload_metadata(self, frontend_owner: str, frontend_name: str) -> None:
        self._drop_metadata(frontend_owner, frontend_name)

    def start_command(
        self,
        execution_id: ExecutionId,
        command_type: str,
        command_input: str | dict | None,
        parameters: dict | None,
    ) -> int:
        """Call into Oracle API function OFFLOAD_REPO.START_COMMAND_EXECUTION()"""
        self._log(f"Recording command start: {execution_id}/{command_type})", detail=VVERBOSE)
        self._debug(f"command_input: {command_input}")
        self._assert_valid_start_command_inputs(execution_id, command_type)
        prepared_input = self._prepare_command_parameters(command_input)
        prepared_parameters = self._prepare_command_parameters(parameters)
        command_execution_id = self._gateway.new_out_var(int)
        self._frontend_api.execute_function(
            "offload_repo.start_command_execution",
            arg_list=[
                execution_id.as_bytes(),
                command_type,
                self._messages.get_log_fh_name(),
                prepared_input,
                prepared_parameters,
                command_execution_id,
            ],
            log_level=VVERBOSE,
            not_when_dry_running=True,
        )
        command_execution_id = command_execution_id.getvalue()
        self._debug(f"command_execution_id: {command_execution_id})")
        return command_execution_id

    def end_command(self, command_execution_id: int, status: str) -> None:
        """Call into Oracle API function OFFLOAD_REPO.END_COMMAND_EXECUTION()"""
        self._log(
            f"Recording command {command_execution_id} status: {status}",
            detail=VVERBOSE,
        )
        self._assert_valid_command_status(status)
        self._frontend_api.execute_function(
            "offload_repo.end_command_execution",
            arg_list=[command_execution_id, status],
            log_level=VVERBOSE,
            not_when_dry_running=True,
        )

    def start_command_step(self, execution_id: ExecutionId, command_type: str, command_step: str) -> int:
        """Call into Oracle API function OFFLOAD_REPO.START_COMMAND_EXECUTION_STEP()"""
        self._log(
            f"Recording command step start: {execution_id}/{command_step}",
            detail=VVERBOSE,
        )
        self._assert_valid_start_step_inputs(execution_id, command_type, command_step)
        command_step_id = self._gateway.new_out_var(int)
        self._frontend_api.execute_function(
            "offload_repo.start_command_execution_step",
            arg_list=[
                execution_id.as_bytes(),
                command_type,
                command_step,
                command_step_id,
            ],
            log_level=VVERBOSE,
            not_when_dry_running=True,
        )
        command_step_id = command_step_id.getvalue()
        self._debug(f"command_step_id: {command_step_id})")
        return command_step_id

    def end_command_step(self, command_step_id: int, status: str, step_details: dict | None = None) -> None:
        """Call into Oracle API function OFFLOAD_REPO.END_COMMAND_EXECUTION_STEP()"""
        self._log(
            f"Recording command step {command_step_id} status: {status}",
            detail=VVERBOSE,
        )
        self._assert_valid_end_step_inputs(command_step_id, status, step_details)
        step_details_str = serialize_object(step_details) if step_details is not None else None
        self._frontend_api.execute_function(
            "offload_repo.end_command_execution_step",
            arg_list=[command_step_id, step_details_str, status],
            log_level=VVERBOSE,
            not_when_dry_running=True,
        )

    def start_offload_chunk(
        self,
        execution_id: ExecutionId,
        frontend_schema: str,
        frontend_table_name: str,
        backend_schema: str,
        backend_table_name: str,
        chunk_number: int = 1,
        offload_partitions: list | None = None,
        offload_partition_level: int | None = None,
    ) -> int:
        """Call into Oracle API function OFFLOAD_REPO.START_OFFLOAD_CHUNK()"""
        self._log(
            f"Recording command chunk start: {execution_id}/{chunk_number}",
            detail=VVERBOSE,
        )
        self._debug(f"frontend: {frontend_schema}/{frontend_table_name})")
        self._debug(f"backend: {backend_schema}/{backend_table_name})")
        self._assert_valid_start_chunk_inputs(
            execution_id,
            frontend_schema,
            frontend_table_name,
            backend_schema,
            backend_table_name,
            chunk_number,
            offload_partitions,
            offload_partition_level,
        )
        chunk_id = self._gateway.new_out_var(int)
        offload_partitions_ntt = self._offload_partitions_to_ora_object(
            offload_partitions,
            offload_partition_level,
            frontend_schema,
            frontend_table_name,
        )
        self._frontend_api.execute_function(
            "offload_repo.start_offload_chunk",
            arg_list=[
                execution_id.as_bytes(),
                frontend_schema,
                frontend_table_name,
                backend_schema,
                backend_table_name,
                chunk_number,
                offload_partitions_ntt,
                chunk_id,
            ],
            log_level=VVERBOSE,
            not_when_dry_running=True,
        )
        chunk_id = chunk_id.getvalue()
        self._debug(f"chunk_id: {chunk_id})")
        return chunk_id

    def end_offload_chunk(
        self,
        chunk_id: int,
        status: str,
        row_count: int | None = None,
        frontend_bytes: int | None = None,
        transport_bytes: int | None = None,
        backend_bytes: int | None = None,
    ) -> None:
        """Call into Oracle API function OFFLOAD_REPO.END_OFFLOAD_CHUNK()"""
        self._log(f"Recording chunk {chunk_id} status: {status}", detail=VVERBOSE)
        self._debug(f"row_count: {row_count})")
        self._debug(f"frontend_bytes: {frontend_bytes})")
        self._debug(f"transport_bytes: {transport_bytes})")
        self._debug(f"backend_bytes: {backend_bytes})")
        self._assert_valid_end_chunk_inputs(chunk_id, status)
        self._frontend_api.execute_function(
            "offload_repo.end_offload_chunk",
            arg_list=[
                chunk_id,
                row_count,
                frontend_bytes,
                transport_bytes,
                backend_bytes,
                status,
            ],
            log_level=VVERBOSE,
            not_when_dry_running=True,
        )

    def get_offloadable_schemas(self):
        """Return offloadable schema rows as dicts.

        User names are bound as ``str()`` values so a missing option keeps the legacy ``upper('None')`` comparison
        instead of a ``NOT IN (..., NULL)`` predicate that would exclude every schema.
        """
        rows = self._gateway.select_structs(
            "get_offloadable_schemas",
            OffloadableSchemaRow,
            {
                "adm_user": str(self._connection_options.ora_adm_user),
                "app_user": str(self._connection_options.ora_app_user),
                "repo_user": str(self._connection_options.ora_repo_user),
            },
        )
        return [msgspec.structs.asdict(row) for row in rows or []]

    def get_schema_tables(self, schema_name):
        """Return schema tables for the given schema using the backend's unsupported column pattern."""
        backend = self._connection_options.backend_distribution
        if backend == BACKEND_DISTRO_CDH:
            unsupported_column_pattern = "1"
        elif backend == BACKEND_DISTRO_GCP:
            unsupported_column_pattern = "2"
        elif backend == BACKEND_DISTRO_SNOWFLAKE:
            unsupported_column_pattern = "3"
        elif backend == BACKEND_DISTRO_MSAZURE:
            unsupported_column_pattern = "4"
        rows = self._gateway.select_structs(
            "get_schema_tables",
            SchemaTableRow,
            {"schema_name": schema_name},
            slots={
                "unsupported_col_name": f"unsupported_col_name_{unsupported_column_pattern}",
                "unsupported_col_name_count": f"unsupported_col_name_{unsupported_column_pattern}_count",
            },
        )
        return [msgspec.structs.asdict(row) for row in rows or []]

    def get_table_columns(self, schema_name, table_name):
        cols = self._frontend_api.get_columns(schema_name.upper(), table_name.upper())
        partition_columns = self._frontend_api.get_partition_columns(schema_name.upper(), table_name.upper())
        subpartition_columns = self._frontend_api.get_subpartition_columns(schema_name.upper(), table_name.upper())
        return_columns = [
            ColumnDetail(
                column_name=one_col.name,
                data_type=one_col.data_type,
                data_precision=one_col.data_precision,
                data_scale=one_col.data_scale,
                is_nullable=one_col.nullable,
                partition_position=None,
            )
            for one_col in cols
        ]
        part_pos = 1
        for part_col in partition_columns:
            for tab_col in return_columns:
                if tab_col.column_name == part_col.name:
                    tab_col.partition_position = part_pos
            part_pos += 1
        subpart_pos = 1
        for subpart_col in subpartition_columns:
            for tab_col in return_columns:
                if tab_col.column_name == subpart_col.name:
                    tab_col.subpartition_position = subpart_pos
            subpart_pos += 1
        return return_columns

    def get_table_partitions(self, schema_name, table_name):
        frontend_table = OffloadSourceTable.create(
            schema_name.upper(),
            table_name.upper(),
            self._connection_options,
            OffloadMessages(detail=QUIET),
            offload_by_subpartition=False,
        )
        try:
            table_partitions = frontend_table.get_partitions()
        except Exception as exc:
            logger.error(f"Table partition type is not supported: {exc.__class__.__qualname__}{exc.args}")
        else:
            if table_partitions:
                return [PartitionDetail.from_orm(table_partition).to_dict() for table_partition in table_partitions]

        return []

    def get_table_subpartitions(self, schema_name, table_name):
        frontend_table = OffloadSourceTable.create(
            schema_name.upper(),
            table_name.upper(),
            self._connection_options,
            OffloadMessages(detail=QUIET),
            offload_by_subpartition=False,
        )
        try:
            table_subpartitions = frontend_table.get_subpartitions()
        except Exception as exc:
            logger.error(f"Table subpartition type is not supported: {exc.__class__.__qualname__}{exc.args}")
        else:
            if table_subpartitions:
                return [SubPartitionDetail.from_orm(table_subpartition) for table_subpartition in table_subpartitions]
        return []

    def get_command_step_codes(self) -> list:
        self._log("Oracle SQL: %s" % self._gateway.statement_text("get_command_step_codes"), detail=QUIET)
        rows = self._gateway.select_tuples("get_command_step_codes")
        return [_[0] for _ in rows] if rows else []

    def get_command_executions(
        self,
    ) -> list[dict[str, str | Any]]:
        """Gets command execution stats"""
        rows = self._gateway.select_structs("get_command_executions", CommandExecutionRow)
        return [msgspec.structs.asdict(row) for row in rows or []]

    def get_command_execution(self, execution_id: ExecutionId) -> dict[str, Any] | None:
        """Gets command execution stats"""
        rows = self._gateway.select_structs(
            "get_command_execution", CommandExecutionRow, {"execution_id": execution_id.as_bytes()}
        )
        return msgspec.structs.asdict(rows[0]) if rows else None

    def get_command_execution_steps(
        self,
        execution_id: ExecutionId | None,
    ) -> list[dict[str, str | Any]]:
        """Gets command execution stats"""
        if execution_id:
            rows = self._gateway.select_structs(
                "get_command_execution_steps_by_id",
                CommandExecutionStepRow,
                {"execution_id": execution_id.as_bytes()},
            )
        else:
            rows = self._gateway.select_structs("get_command_execution_steps_all", CommandExecutionStepRow)
        return [msgspec.structs.asdict(row) for row in rows or []]

    def _drop_metadata(self, frontend_owner: str, frontend_name: str) -> None:
        logger.debug(f"Dropping metadata: {frontend_owner}, {frontend_name}")
        assert frontend_owner
        assert frontend_name
        frontend_owner = frontend_owner.upper()
        frontend_name = frontend_name.upper()
        self._frontend_api.execute_function(
            "offload_repo.delete_offload_metadata",
            arg_list=[frontend_owner, frontend_name],
            not_when_dry_running=True,
            commit=True,
        )

    def _get_metadata(self, frontend_owner: str, frontend_name: str) -> dict | None:
        logger.debug(f"Fetching metadata: {frontend_owner}, {frontend_name}")
        assert frontend_owner
        assert frontend_name
        frontend_owner = frontend_owner.upper()
        frontend_name = frontend_name.upper()
        metadata_obj = self._frontend_api.execute_function(
            "offload_repo.get_offload_metadata",
            return_type=oracledb.DB_TYPE_OBJECT,
            return_type_name=self._get_ora_type_object_name(OFFLOAD_METADATA_ORA_TYPE_NAME),
            arg_list=[frontend_owner, frontend_name],
            log_level=VVERBOSE,
        )
        if metadata_obj:
            return self._ora_object_to_metadata_dict(metadata_obj)
        return None

    def _get_offload_metadata_ora_type_object(self):
        """This subverts FrontendApi because it has knowledge about oracledb. We are in an Oracle only class
        so this is slightly less terrible but still not ideal.
        """
        return self._get_ora_type_object(OFFLOAD_METADATA_ORA_TYPE_NAME)

    def _get_ora_type_object(self, repo_type_name: str, owner_override: str | None = None) -> Any:
        qualified_name = self._get_ora_type_object_name(repo_type_name, owner_override=owner_override)
        return self._frontend_api.oracle_get_type_object(qualified_name)

    def _get_ora_type_object_name(self, repo_type_name: str, owner_override: str | None = None) -> str:
        return f'"{(owner_override or self._repo_user or "").upper()}"."{repo_type_name.upper()}"'

    def _metadata_dict_to_ora_object(self, metadata_dict):
        """Used to convert a Python dict of metadata to an Oracle object type ready for saving to the database."""
        logger.debug(f"Converting metadata: {metadata_dict}")
        metadata_obj = self._get_offload_metadata_ora_type_object()
        metadata_obj.FRONTEND_OBJECT_OWNER = metadata_dict[OFFLOADED_OWNER]
        metadata_obj.FRONTEND_OBJECT_NAME = metadata_dict[OFFLOADED_TABLE]
        metadata_obj.BACKEND_OBJECT_OWNER = metadata_dict[HADOOP_OWNER]
        metadata_obj.BACKEND_OBJECT_NAME = metadata_dict[HADOOP_TABLE]
        metadata_obj.OFFLOAD_TYPE = metadata_dict[OFFLOAD_TYPE]
        metadata_obj.OFFLOAD_RANGE_TYPE = metadata_dict[INCREMENTAL_RANGE]
        metadata_obj.OFFLOAD_KEY = metadata_dict[INCREMENTAL_KEY]
        metadata_obj.OFFLOAD_HIGH_VALUE = metadata_dict[INCREMENTAL_HIGH_VALUE]
        metadata_obj.OFFLOAD_PREDICATE_TYPE = metadata_dict[INCREMENTAL_PREDICATE_TYPE]
        if metadata_dict[INCREMENTAL_PREDICATE_VALUE] is None:
            metadata_obj.OFFLOAD_PREDICATE_VALUE = metadata_dict[INCREMENTAL_PREDICATE_VALUE]
        else:
            metadata_obj.OFFLOAD_PREDICATE_VALUE = self._metadata_dict_to_json_string(
                metadata_dict[INCREMENTAL_PREDICATE_VALUE]
            )
        metadata_obj.OFFLOAD_SNAPSHOT = metadata_dict[OFFLOAD_SNAPSHOT]
        metadata_obj.OFFLOAD_HASH_COLUMN = metadata_dict[OFFLOAD_BUCKET_COLUMN]
        metadata_obj.OFFLOAD_SORT_COLUMNS = metadata_dict[OFFLOAD_SORT_COLUMNS]
        metadata_obj.OFFLOAD_PARTITION_FUNCTIONS = metadata_dict[OFFLOAD_PARTITION_FUNCTIONS]
        metadata_obj.COMMAND_EXECUTION = metadata_dict[COMMAND_EXECUTION].as_bytes()
        return metadata_obj

    def _ora_object_to_metadata_dict(self, metadata_obj):
        """Converts the Oracle object type to a Python dict of metadata to be used in orchestration."""
        metadata_dict = {
            HADOOP_OWNER: metadata_obj.BACKEND_OBJECT_OWNER,
            HADOOP_TABLE: metadata_obj.BACKEND_OBJECT_NAME,
            OFFLOAD_TYPE: metadata_obj.OFFLOAD_TYPE,
            OFFLOADED_OWNER: metadata_obj.FRONTEND_OBJECT_OWNER,
            OFFLOADED_TABLE: metadata_obj.FRONTEND_OBJECT_NAME,
            INCREMENTAL_KEY: metadata_obj.OFFLOAD_KEY or None,
            INCREMENTAL_HIGH_VALUE: (
                metadata_obj.OFFLOAD_HIGH_VALUE.read() if metadata_obj.OFFLOAD_HIGH_VALUE else None
            ),
            INCREMENTAL_RANGE: metadata_obj.OFFLOAD_RANGE_TYPE or None,
            INCREMENTAL_PREDICATE_TYPE: metadata_obj.OFFLOAD_PREDICATE_TYPE or None,
            INCREMENTAL_PREDICATE_VALUE: (
                deserialize_object(metadata_obj.OFFLOAD_PREDICATE_VALUE.read())
                if metadata_obj.OFFLOAD_PREDICATE_VALUE
                else None
            ),
            OFFLOAD_BUCKET_COLUMN: metadata_obj.OFFLOAD_HASH_COLUMN or None,
            OFFLOAD_SORT_COLUMNS: metadata_obj.OFFLOAD_SORT_COLUMNS or None,
            OFFLOAD_SNAPSHOT: metadata_obj.OFFLOAD_SNAPSHOT or None,
            OFFLOAD_PARTITION_FUNCTIONS: metadata_obj.OFFLOAD_PARTITION_FUNCTIONS or None,
            COMMAND_EXECUTION: ExecutionId.from_bytes(metadata_obj.COMMAND_EXECUTION),
        }
        return metadata_dict

    def _offload_partitions_to_ora_object(
        self,
        offload_partitions: list | None,
        offload_partition_level: int | None,
        frontend_schema: str,
        frontend_table_name: str,
    ) -> Any:
        """Used to convert a Python dict of metadata to an Oracle object type ready for saving to the database."""
        logger.debug("Converting offload_partitions")
        partitions_ntt = self._get_ora_type_object(OFFLOAD_PARTITIONS_ORA_TYPE_NAME)
        if not offload_partitions:
            return partitions_ntt
        partition_obj = self._get_ora_type_object(OFFLOAD_PARTITION_ORA_TYPE_NAME)
        for partition in offload_partitions:
            partition_obj.TABLE_OWNER = frontend_schema
            partition_obj.TABLE_NAME = frontend_table_name
            partition_obj.PARTITION_NAME = partition.partition_name
            partition_obj.PARTITION_LEVEL = offload_partition_level
            partition_obj.PARTITION_BYTES = partition.size_in_bytes
            partition_obj.PARTITION_BOUNDARY = partition.partition_literal
            partitions_ntt.append(partition_obj)
        return partitions_ntt

    def _set_metadata(
        self,
        metadata: dict | OrchestrationMetadata,
    ) -> None:
        assert metadata
        metadata_dict: dict = metadata.as_dict() if isinstance(metadata, OrchestrationMetadata) else metadata
        frontend_owner = metadata_dict[OFFLOADED_OWNER].upper()
        frontend_name = metadata_dict[OFFLOADED_TABLE].upper()
        logger.debug(f"Writing metadata: {frontend_owner}, {frontend_name}")
        ora_metadata = self._metadata_dict_to_ora_object(metadata_dict)
        self._frontend_api.execute_function(
            "offload_repo.save_offload_metadata",
            arg_list=[frontend_owner, frontend_name, ora_metadata],
            not_when_dry_running=True,
            commit=True,
        )
        self._log(f"Saved metadata: {metadata_dict!s}", detail=VERBOSE)

    @property
    def _gateway(self) -> OracleGateway:
        """Return the lazily created gateway for ``oracle_repo.sql`` statements.

        Created on first use so constructing the client never validates ``ora_repo_user`` or touches a connection.
        """
        if self._repo_gateway is None:
            self._repo_gateway = OracleGateway(
                lambda: self._frontend_api.get_validated_oracle_connection(),
                load_sql_file(ORACLE_REPO_SQL_PATH),
                slots={"repo_user": self._repo_user},
            )
        return self._repo_gateway
