# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Oracle repository service executing named SQL and OFFLOAD_REPO procedures over pooled SQLSpec sessions."""

import logging
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import msgspec

from goe.offload.offload_constants import (
    BACKEND_DISTRO_CDH,
    BACKEND_DISTRO_GCP,
    BACKEND_DISTRO_MSAZURE,
    BACKEND_DISTRO_SNOWFLAKE,
    DBTYPE_ORACLE,
)
from goe.offload.offload_messages import QUIET, VERBOSE, VVERBOSE, OffloadMessages
from goe.offload.offload_source_data import OffloadSourcePartition
from goe.offload.registry import create_frontend_api, create_source_table
from goe.orchestration import command_steps, orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.models import (
    CommandExecutionRecord,
    CommandStepRecord,
    OffloadMetadata,
    OffloadMetadataRow,
)
from goe.persistence.registry import OracleDatabaseRegistry
from goe.persistence.retry import run_with_session_retry
from goe.persistence.schemas import (
    ColumnDetail,
    CommandExecutionRow,
    CommandExecutionStepRow,
    OffloadableSchemaRow,
    PartitionDetail,
    SchemaTableRow,
    SubPartitionDetail,
)
from goe.persistence.statements import NamedStatements
from goe.serializers import encode_json
from goe.typing import FrozenBaseStruct

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig

__all__ = (
    "OFFLOAD_METADATA_ORA_TYPE_NAME",
    "OFFLOAD_PARTITIONS_ORA_TYPE_NAME",
    "OFFLOAD_PARTITION_ORA_TYPE_NAME",
    "ORACLE_REPO_SQL_PATH",
    "OracleRepositoryService",
)

logger = logging.getLogger(__name__)

OFFLOAD_METADATA_ORA_TYPE_NAME: Final = "OFFLOAD_METADATA_OT"
OFFLOAD_PARTITION_ORA_TYPE_NAME: Final = "OFFLOAD_PARTITION_OT"
OFFLOAD_PARTITIONS_ORA_TYPE_NAME: Final = "OFFLOAD_PARTITION_NTT"
ORACLE_REPO_SQL_PATH: Final = Path(__file__).resolve().parents[1] / "sql" / "oracle_repo.sql"


class OracleRepositoryService:
    """Pooled SQLSpec repository service for Oracle ``OFFLOAD_REPO`` metadata and execution tracking."""

    def __init__(
        self,
        connection_options: "OrchestrationConfig",
        messages: OffloadMessages | None = None,
        *,
        dry_run: bool = False,
        trace_action: str | None = None,
        registry: OracleDatabaseRegistry | None = None,
    ) -> None:
        assert connection_options
        self._connection_options = connection_options
        self._messages = messages or OffloadMessages(detail=QUIET)
        self._dry_run = dry_run
        self._trace_action = trace_action or self.__class__.__name__
        self._repo_user = str(connection_options.ora_repo_user or "")
        self._registry = registry
        self._repo_statements: NamedStatements | None = None
        self._weak_udt_cache: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()
        self._id_udt_cache: dict[tuple[int, str], Any] = {}

    def close(self, force: bool = False) -> None:
        """No-op close hook kept for caller symmetry because sessions are returned per operation."""

    def get_offload_metadata(self, frontend_owner: str, frontend_name: str) -> OffloadMetadata | None:
        """Load offload metadata for ``frontend_owner.frontend_name`` in one round trip from ``offload_metadata_v``."""
        assert frontend_owner and frontend_name
        binds = {
            "frontend_owner": frontend_owner.upper(),
            "frontend_name": frontend_name.upper(),
        }
        sql = self._statements.text("get_offload_metadata")

        def _query() -> OffloadMetadataRow | None:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                rows = driver.select(sql, binds, schema_type=OffloadMetadataRow)
                return rows[0] if rows else None

        row = run_with_session_retry(_query)
        return OffloadMetadata.from_repo_row(row) if row is not None else None

    def list_offload_metadata_by_owner(self, frontend_owner: str) -> list[OffloadMetadata]:
        """Return all offload metadata records for ``frontend_owner`` in one round trip."""
        assert frontend_owner
        binds = {"frontend_owner": frontend_owner.upper()}
        sql = self._statements.text("list_offload_metadata_by_owner")

        def _query() -> list[OffloadMetadataRow]:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                return driver.select(sql, binds, schema_type=OffloadMetadataRow)

        rows = run_with_session_retry(_query)
        return [OffloadMetadata.from_repo_row(row) for row in rows]

    def set_offload_metadata(self, metadata: OffloadMetadata | dict[str, Any]) -> None:
        """Persist ``metadata`` via ``offload_repo.save_offload_metadata`` using cached connection UDT descriptors."""
        assert metadata
        model = OffloadMetadata.from_legacy_dict(metadata)
        frontend_owner = model.offloaded_owner.upper()
        frontend_name = model.offloaded_table.upper()
        self._log_call("offload_repo.save_offload_metadata", [frontend_owner, frontend_name, model.as_dict()], VERBOSE)
        if self._dry_run:
            return

        def _save() -> None:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                conn = driver.connection
                ora_obj = self._build_metadata_ora_object(conn, model)
                self._call_proc(conn, "offload_repo.save_offload_metadata", [frontend_owner, frontend_name, ora_obj])
                conn.commit()

        run_with_session_retry(_save)
        self._log(f"Saved metadata: {model.as_dict()}", detail=VERBOSE)

    def drop_offload_metadata(self, frontend_owner: str, frontend_name: str) -> None:
        """Delete offload metadata for ``frontend_owner.frontend_name`` via ``offload_repo.delete_offload_metadata``."""
        assert frontend_owner and frontend_name
        owner_upper = frontend_owner.upper()
        name_upper = frontend_name.upper()
        self._log_call("offload_repo.delete_offload_metadata", [owner_upper, name_upper], VERBOSE)
        if self._dry_run:
            return

        def _drop() -> None:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                conn = driver.connection
                self._call_proc(conn, "offload_repo.delete_offload_metadata", [owner_upper, name_upper])
                conn.commit()

        run_with_session_retry(_drop)

    def start_command(
        self,
        execution_id: ExecutionId,
        command_type: str,
        command_input: str | dict[str, Any] | None,
        parameters: dict[str, Any] | None,
    ) -> int | None:
        """Record the start of an orchestration command via ``offload_repo.start_command_execution``."""
        self._log(f"Recording command start: {execution_id}/{command_type})", detail=VVERBOSE)
        self._debug(f"command_input: {command_input}")
        self._assert_valid_start_command_inputs(execution_id, command_type)
        prepared_input = self._prepare_command_parameters(command_input)
        prepared_parameters = self._prepare_command_parameters(parameters)
        if self._dry_run:
            return None

        def _start() -> int:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                conn = driver.connection
                cursor = conn.cursor()
                try:
                    out_id = cursor.var(int)
                    args = [
                        execution_id.as_bytes(),
                        command_type,
                        self._messages.get_log_fh_name(),
                        prepared_input,
                        prepared_parameters,
                        out_id,
                    ]
                    self._log_call("offload_repo.start_command_execution", args, VVERBOSE)
                    cursor.callproc("offload_repo.start_command_execution", args)
                    val = out_id.getvalue()
                    return int(val[0] if isinstance(val, list) else val)
                finally:
                    cursor.close()

        return run_with_session_retry(_start)

    def end_command(self, command_execution_id: int | None, status: str) -> None:
        """Record the completion of an orchestration command via ``offload_repo.end_command_execution``."""
        self._log(f"Recording command {command_execution_id} status: {status}", detail=VVERBOSE)
        self._assert_valid_command_status(status)
        if self._dry_run:
            return

        def _end() -> None:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                self._call_proc(driver.connection, "offload_repo.end_command_execution", [command_execution_id, status])

        run_with_session_retry(_end)

    def start_command_step(self, execution_id: ExecutionId, command_type: str, command_step: str) -> int | None:
        """Record the start of an orchestration command step via ``offload_repo.start_command_execution_step``."""
        self._log(f"Recording command step start: {execution_id}/{command_step}", detail=VVERBOSE)
        self._assert_valid_start_step_inputs(execution_id, command_type, command_step)
        if self._dry_run:
            return None

        def _start_step() -> int:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                conn = driver.connection
                cursor = conn.cursor()
                try:
                    out_step_id = cursor.var(int)
                    args = [execution_id.as_bytes(), command_type, command_step, out_step_id]
                    self._log_call("offload_repo.start_command_execution_step", args, VVERBOSE)
                    cursor.callproc("offload_repo.start_command_execution_step", args)
                    val = out_step_id.getvalue()
                    return int(val[0] if isinstance(val, list) else val)
                finally:
                    cursor.close()

        return run_with_session_retry(_start_step)

    def end_command_step(
        self,
        command_step_id: int | None,
        status: str,
        step_details: dict[str, Any] | None = None,
    ) -> None:
        """Record the completion of an orchestration command step via ``offload_repo.end_command_execution_step``."""
        self._log(f"Recording command step {command_step_id} status: {status}", detail=VVERBOSE)
        self._assert_valid_end_step_inputs(command_step_id, status, step_details)
        step_details_str = encode_json(step_details) if step_details is not None else None
        if self._dry_run:
            return

        def _end_step() -> None:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                self._call_proc(
                    driver.connection,
                    "offload_repo.end_command_execution_step",
                    [command_step_id, step_details_str, status],
                )

        run_with_session_retry(_end_step)

    def start_offload_chunk(
        self,
        execution_id: ExecutionId,
        frontend_schema: str,
        frontend_table_name: str,
        backend_schema: str,
        backend_table_name: str,
        chunk_number: int = 1,
        offload_partitions: list[Any] | None = None,
        offload_partition_level: int | None = None,
    ) -> int | None:
        """Record the start of an offload transport chunk via ``offload_repo.start_offload_chunk``."""
        self._log(f"Recording command chunk start: {execution_id}/{chunk_number}", detail=VVERBOSE)
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
        if self._dry_run:
            return None

        def _start_chunk() -> int:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                conn = driver.connection
                cursor = conn.cursor()
                try:
                    out_chunk_id = cursor.var(int)
                    partitions_ntt = self._build_partitions_ora_object(
                        conn,
                        offload_partitions,
                        offload_partition_level,
                        frontend_schema,
                        frontend_table_name,
                    )
                    args = [
                        execution_id.as_bytes(),
                        frontend_schema,
                        frontend_table_name,
                        backend_schema,
                        backend_table_name,
                        chunk_number,
                        partitions_ntt,
                        out_chunk_id,
                    ]
                    self._log_call("offload_repo.start_offload_chunk", args, VVERBOSE)
                    cursor.callproc("offload_repo.start_offload_chunk", args)
                    val = out_chunk_id.getvalue()
                    return int(val[0] if isinstance(val, list) else val)
                finally:
                    cursor.close()

        return run_with_session_retry(_start_chunk)

    def end_offload_chunk(
        self,
        chunk_id: int | None,
        status: str,
        row_count: int | None = None,
        frontend_bytes: int | None = None,
        transport_bytes: int | None = None,
        backend_bytes: int | None = None,
    ) -> None:
        """Record the completion of an offload transport chunk via ``offload_repo.end_offload_chunk``."""
        self._log(f"Recording chunk {chunk_id} status: {status}", detail=VVERBOSE)
        self._assert_valid_end_chunk_inputs(chunk_id, status)
        if self._dry_run:
            return

        def _end_chunk() -> None:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                self._call_proc(
                    driver.connection,
                    "offload_repo.end_offload_chunk",
                    [chunk_id, row_count, frontend_bytes, transport_bytes, backend_bytes, status],
                )

        run_with_session_retry(_end_chunk)

    def get_offloadable_schemas(self) -> list[dict[str, Any]]:
        """Return offloadable schema rows as dictionaries."""
        binds = {
            "adm_user": str(self._connection_options.ora_adm_user),
            "app_user": str(self._connection_options.ora_app_user),
            "repo_user": str(self._connection_options.ora_repo_user),
        }
        rows = self._select_rows("get_offloadable_schemas", OffloadableSchemaRow, binds)
        return [msgspec.structs.asdict(row) for row in rows]

    def get_schema_tables(self, schema_name: str) -> list[dict[str, Any]]:
        """Return schema tables for ``schema_name`` using the configured backend's unsupported column pattern."""
        backend = self._connection_options.backend_distribution
        pattern_map = {
            BACKEND_DISTRO_CDH: "1",
            BACKEND_DISTRO_GCP: "2",
            BACKEND_DISTRO_SNOWFLAKE: "3",
            BACKEND_DISTRO_MSAZURE: "4",
        }
        pattern = pattern_map.get(backend or "", "2")
        slots = {
            "unsupported_col_name": f"unsupported_col_name_{pattern}",
            "unsupported_col_name_count": f"unsupported_col_name_{pattern}_count",
        }
        rows = self._select_rows("get_schema_tables", SchemaTableRow, {"schema_name": schema_name}, slots=slots)
        return [msgspec.structs.asdict(row) for row in rows]

    def get_table_columns(self, schema_name: str, table_name: str) -> list[ColumnDetail]:
        """Return column metadata with partition and subpartition positions for ``schema_name.table_name``."""
        frontend_api = create_frontend_api(
            DBTYPE_ORACLE,
            self._connection_options,
            self._messages,
            dry_run=self._dry_run,
            trace_action=self._trace_action,
        )
        try:
            owner_upper = schema_name.upper()
            name_upper = table_name.upper()
            cols = frontend_api.get_columns(owner_upper, name_upper)
            partition_columns = frontend_api.get_partition_columns(owner_upper, name_upper)
            subpartition_columns = frontend_api.get_subpartition_columns(owner_upper, name_upper)
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
            for part_pos, part_col in enumerate(partition_columns, start=1):
                for tab_col in return_columns:
                    if tab_col.column_name == part_col.name:
                        tab_col.partition_position = part_pos
            for subpart_pos, subpart_col in enumerate(subpartition_columns, start=1):
                for tab_col in return_columns:
                    if tab_col.column_name == subpart_col.name:
                        tab_col.subpartition_position = subpart_pos
            return return_columns
        finally:
            frontend_api.close()

    def get_table_partitions(self, schema_name: str, table_name: str) -> list[dict[str, Any]]:
        """Return partition details for ``schema_name.table_name``."""
        frontend_table = create_source_table(
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
            return []
        else:
            if table_partitions:
                return [PartitionDetail.from_orm(table_partition).to_dict() for table_partition in table_partitions]
            return []
        finally:
            if hasattr(frontend_table, "close"):
                frontend_table.close()

    def get_table_subpartitions(self, schema_name: str, table_name: str) -> list[SubPartitionDetail]:
        """Return subpartition details for ``schema_name.table_name``."""
        frontend_table = create_source_table(
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
            return []
        else:
            if table_subpartitions:
                return [SubPartitionDetail.from_orm(table_subpartition) for table_subpartition in table_subpartitions]
            return []
        finally:
            if hasattr(frontend_table, "close"):
                frontend_table.close()

    def get_command_step_codes(self) -> list[str]:
        """Return sorted command step codes from ``COMMAND_STEP``."""
        sql = self._statements.text("get_command_step_codes")
        self._log(f"Oracle SQL: {sql}", detail=QUIET)
        rows = self._select_rows("get_command_step_codes", _CommandStepCodeRow)
        return [row.code for row in rows]

    def get_command_executions(self) -> list[dict[str, Any]]:
        """Return all command execution records as dictionaries."""
        rows = self._select_rows("get_command_executions", CommandExecutionRow)
        return [msgspec.structs.asdict(row) for row in rows]

    def get_command_execution_records(self) -> list[CommandExecutionRecord]:
        """Return all command execution records as typed ``CommandExecutionRecord`` structs."""
        rows = self._select_rows("get_command_executions", CommandExecutionRow)
        return [CommandExecutionRecord.from_row(row) for row in rows]

    def get_command_execution(self, execution_id: ExecutionId) -> dict[str, Any] | None:
        """Return a single command execution record as a dictionary or None."""
        rows = self._select_rows(
            "get_command_execution",
            CommandExecutionRow,
            {"execution_id": execution_id.as_bytes()},
        )
        return msgspec.structs.asdict(rows[0]) if rows else None

    def get_command_execution_steps(self, execution_id: ExecutionId | None) -> list[dict[str, Any]]:
        """Return command execution step records for ``execution_id`` (or all executions when None)."""
        if execution_id:
            rows = self._select_rows(
                "get_command_execution_steps_by_id",
                CommandExecutionStepRow,
                {"execution_id": execution_id.as_bytes()},
            )
        else:
            rows = self._select_rows("get_command_execution_steps_all", CommandExecutionStepRow)
        return [msgspec.structs.asdict(row) for row in rows]

    def get_command_step_records(self, execution_id: ExecutionId | None = None) -> list[CommandStepRecord]:
        """Return command execution step records as typed ``CommandStepRecord`` structs."""
        if execution_id:
            rows = self._select_rows(
                "get_command_execution_steps_by_id",
                CommandExecutionStepRow,
                {"execution_id": execution_id.as_bytes()},
            )
        else:
            rows = self._select_rows("get_command_execution_steps_all", CommandExecutionStepRow)
        return [CommandStepRecord.from_row(row) for row in rows]

    @property
    def _adm_registry(self) -> OracleDatabaseRegistry:
        """Return the lazily resolved ``OracleDatabaseRegistry`` for the configured connection options."""
        if self._registry is None:
            self._registry = OracleDatabaseRegistry.for_options(self._connection_options)
        return self._registry

    @property
    def _statements(self) -> NamedStatements:
        """Return lazily validated ``NamedStatements`` for ``oracle_repo.sql``."""
        if self._repo_statements is None:
            self._repo_statements = NamedStatements(ORACLE_REPO_SQL_PATH, slots={"repo_user": self._repo_user})
        return self._repo_statements

    def _select_rows[S: msgspec.Struct](
        self,
        name: str,
        schema_type: type[S],
        params: dict[str, Any] | None = None,
        *,
        slots: dict[str, str] | None = None,
    ) -> list[S]:
        """Execute a named repository statement with lost-session retry and return hydrated struct rows."""
        sql = self._statements.text(name, slots)
        binds = dict(params or {})

        def _run() -> list[S]:
            with self._adm_registry.adm_session(action=self._trace_action) as driver:
                if binds:
                    return driver.select(sql, binds, schema_type=schema_type)
                return driver.select(sql, schema_type=schema_type)

        return run_with_session_retry(_run)

    def _get_ora_type(self, connection: Any, repo_type_name: str) -> Any:
        """Return a cached ``DbObjectType`` for ``repo_type_name`` on ``connection``."""
        qualified = f'"{self._repo_user.upper()}"."{repo_type_name.upper()}"'
        try:
            conn_cache = self._weak_udt_cache.setdefault(connection, {})
            if qualified not in conn_cache:
                conn_cache[qualified] = connection.gettype(qualified)
            return conn_cache[qualified]
        except TypeError:
            key = (id(connection), qualified)
            if key not in self._id_udt_cache:
                self._id_udt_cache[key] = connection.gettype(qualified)
            return self._id_udt_cache[key]

    def _build_metadata_ora_object(self, connection: Any, metadata: OffloadMetadata) -> Any:
        """Construct and populate an ``OFFLOAD_METADATA_OT`` instance from ``metadata``."""
        ora_type = self._get_ora_type(connection, OFFLOAD_METADATA_ORA_TYPE_NAME)
        obj = ora_type.newobject()
        for attr_name, attr_val in metadata.to_repo_binds().items():
            setattr(obj, attr_name, attr_val)
        return obj

    def _build_partitions_ora_object(
        self,
        connection: Any,
        offload_partitions: list[Any] | None,
        offload_partition_level: int | None,
        frontend_schema: str,
        frontend_table_name: str,
    ) -> Any:
        """Construct and populate an ``OFFLOAD_PARTITION_NTT`` collection from ``offload_partitions``."""
        ntt_type = self._get_ora_type(connection, OFFLOAD_PARTITIONS_ORA_TYPE_NAME)
        partitions_ntt = ntt_type.newobject()
        if not offload_partitions:
            return partitions_ntt
        elem_type = self._get_ora_type(connection, OFFLOAD_PARTITION_ORA_TYPE_NAME)
        for partition in offload_partitions:
            part_obj = elem_type.newobject()
            part_obj.TABLE_OWNER = frontend_schema
            part_obj.TABLE_NAME = frontend_table_name
            part_obj.PARTITION_NAME = partition.partition_name
            part_obj.PARTITION_LEVEL = offload_partition_level
            part_obj.PARTITION_BYTES = partition.size_in_bytes
            part_obj.PARTITION_BOUNDARY = partition.partition_literal
            partitions_ntt.append(part_obj)
        return partitions_ntt

    def _call_proc(self, connection: Any, proc_name: str, args: list[Any]) -> None:
        """Execute a PL/SQL procedure on ``connection`` and close its cursor."""
        self._log_call(proc_name, args, VVERBOSE)
        cursor = connection.cursor()
        try:
            cursor.callproc(proc_name, args)
        finally:
            cursor.close()

    @staticmethod
    def _prepare_command_parameters(command_params: str | dict[str, Any] | None) -> str | None:
        """Serialize command input or parameter dictionaries to JSON strings."""
        if command_params is None:
            return None
        if isinstance(command_params, str):
            return command_params
        return encode_json(command_params)

    def _log_call(self, sql_fn: str, args: list[Any], detail: int) -> None:
        """Log PL/SQL procedure name and arguments to ``OffloadMessages``."""
        self._log(f"Oracle SQL: {sql_fn}", detail=detail)
        self._log(f"Arguments: {args}", detail=detail)

    def _log(self, msg: str, detail: int | None = None, ansi_code: str | None = None) -> None:
        """Write message to the offload log and standard logger."""
        self._messages.log(msg, detail=detail, ansi_code=ansi_code)
        if detail == VVERBOSE:
            logger.debug(msg)
        else:
            logger.info(msg)

    def _debug(self, msg: str) -> None:
        """Write debug message to the offload log and standard logger."""
        self._messages.debug(msg)
        logger.debug(msg)

    @staticmethod
    def _assert_valid_start_command_inputs(execution_id: ExecutionId, command_type: str) -> None:
        assert isinstance(execution_id, ExecutionId), f"{type(execution_id)} is not ExecutionId"
        assert command_type in orchestration_constants.ALL_COMMAND_CODES, f"{command_type} not in ALL_COMMAND_CODES"

    @staticmethod
    def _assert_valid_start_step_inputs(execution_id: ExecutionId, command_type: str, command_step: str) -> None:
        assert isinstance(execution_id, ExecutionId), f"{type(execution_id)} is not ExecutionId"
        assert command_type in orchestration_constants.ALL_COMMAND_CODES, f"{command_type} not in ALL_COMMAND_CODES"
        assert command_step in command_steps.STEP_TITLES, f"{command_step} not in STEP_TITLES"

    @staticmethod
    def _assert_valid_start_chunk_inputs(
        execution_id: ExecutionId,
        frontend_schema: str,
        frontend_table_name: str,
        backend_schema: str,
        backend_table_name: str,
        chunk_number: int,
        offload_partitions: list[Any] | None,
        offload_partition_level: int | None,
    ) -> None:
        assert isinstance(execution_id, ExecutionId), f"{type(execution_id)} is not ExecutionId"
        assert isinstance(frontend_schema, str), f"{type(frontend_schema)} is not str"
        assert isinstance(frontend_table_name, str), f"{type(frontend_table_name)} is not str"
        assert isinstance(backend_schema, str), f"{type(backend_schema)} is not str"
        assert isinstance(backend_table_name, str), f"{type(backend_table_name)} is not str"
        assert isinstance(chunk_number, int) and chunk_number > 0, f"{chunk_number} is not a positive int"
        if offload_partitions:
            assert isinstance(offload_partitions, list), f"{type(offload_partitions)} is not list"
            assert isinstance(offload_partitions[0], OffloadSourcePartition), (
                f"{type(offload_partitions[0])} is not OffloadSourcePartition"
            )
            assert isinstance(offload_partition_level, int) and offload_partition_level > 0, (
                f"{offload_partition_level} is not a positive int"
            )

    def _assert_valid_end_step_inputs(
        self, command_step_id: int | None, status: str, step_details: dict[str, Any] | None
    ) -> None:
        if not self._dry_run:
            assert isinstance(command_step_id, int), f"{type(command_step_id)} is not int"
        self._assert_valid_command_status(status)
        if step_details is not None:
            assert isinstance(step_details, dict), f"{type(step_details)} is not dict"

    def _assert_valid_end_chunk_inputs(self, chunk_id: int | None, status: str) -> None:
        if not self._dry_run:
            assert isinstance(chunk_id, int), f"{type(chunk_id)} is not int"
        self._assert_valid_command_status(status)

    @staticmethod
    def _assert_valid_command_status(status: str) -> None:
        assert status in (
            orchestration_constants.COMMAND_SUCCESS,
            orchestration_constants.COMMAND_ERROR,
        )


class _CommandStepCodeRow(FrozenBaseStruct, frozen=True, kw_only=True):
    """Single-column projection for ``get_command_step_codes``."""

    code: str
