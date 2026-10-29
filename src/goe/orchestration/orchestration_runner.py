# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OrchestrationRunner: Stateless entry point for orchestration commands utilized by CLI and Listener."""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from goe.config.orchestration_config import OrchestrationConfig
from goe.observability.runtime import ensure_observability
from goe.observability.spans import current_trace_ids, traced_command
from goe.offload.offload_messages import (
    NORMAL,
    VVERBOSE,
    OffloadMessages,
)
from goe.offload.registry import (
    create_repository_client,
    create_source_table,
)
from goe.orchestration import command_steps, orchestration_constants
from goe.orchestration.context import (
    ExecutionContext,
    bind_execution_context,
    current_execution_context,
)
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.logging_init import get_log_fh, init, init_log
from goe.orchestration.pipeline import get_offload_target_table, offload_table
from goe.orchestration.sinks import ExecutionSink
from goe.orchestration.stages.plan_resolution import OffloadOperation
from goe.platform.locking import orchestration_lock_for_table

if TYPE_CHECKING:
    from goe.persistence.oracle.oracle_repository import OracleRepositoryService


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OrchestrationRunnerException(Exception):
    """Exception raised for OrchestrationRunner initialization or execution errors."""


COMMAND_ID_CONNECT = "CONNECT"

LOG_FILE_PREFIXES = {
    COMMAND_ID_CONNECT: "connect",
    orchestration_constants.COMMAND_OFFLOAD: "offload",
    orchestration_constants.COMMAND_SCHEMA_SYNC: "schema_sync",
}


class OrchestrationRunner:
    """OrchestrationRunner: Stateless entry point for orchestration commands."""

    def __init__(
        self,
        config_overrides: dict[str, Any] | None = None,
        suppress_stdout: bool = False,
        *,
        settings: Any = None,
        sinks: Sequence[ExecutionSink] = (),
    ) -> None:
        """Initialize the runner with configuration settings and optional execution sinks."""
        self._config = (
            settings if settings is not None else self._gen_config(config_overrides, suppress_stdout=suppress_stdout)
        )
        self._sinks: tuple[ExecutionSink, ...] = tuple(sinks)
        ensure_observability(self._config)

    def offload(
        self,
        params: Any,
        execution_id: ExecutionId | None = None,
        reuse_log: bool = False,
        messages_override: OffloadMessages | None = None,
    ) -> Any:
        """Run an offload based on incoming params under a command-scoped ExecutionContext."""
        dry_run = bool(not self._execute_from_params(params))
        exec_id, messages, repo_client = self._init_command(
            orchestration_constants.COMMAND_OFFLOAD,
            params,
            execution_id=execution_id,
            reuse_log=reuse_log,
            messages_override=messages_override,
        )

        with bind_execution_context(messages.context):
            operation = self._gen_offload_operation(params, repo_client, exec_id, messages)
            with traced_command(
                orchestration_constants.COMMAND_OFFLOAD,
                exec_id,
                backend=self._config.target,
                dry_run=dry_run,
                source_owner=operation.owner,
                source_table=operation.table_name,
            ):
                command_id = self._command_begin(
                    orchestration_constants.COMMAND_OFFLOAD,
                    params,
                    repo_client,
                    operation,
                    execution_id=exec_id,
                    messages=messages,
                )
                try:
                    offload_source_table = self._build_offload_source_table(operation, messages)
                    offload_target_table = get_offload_target_table(operation, self._config, messages)

                    self._log(
                        f"Offloading to {self._target_version_string(offload_target_table)}",
                        messages=messages,
                    )

                    status = self._offload(
                        operation,
                        offload_source_table,
                        offload_target_table,
                        messages,
                    )
                    self._log_final_messages(
                        orchestration_constants.COMMAND_OFFLOAD,
                        dry_run,
                        messages=messages,
                    )

                    self._command_end(command_id, repo_client, messages=messages)
                    self._cleanup_objects(
                        repo_client,
                        frontend_table=offload_source_table,
                        backend_table=offload_target_table,
                        messages=messages,
                    )
                except Exception as exc:
                    self._command_fail(command_id, exc, repo_client, messages=messages)
                    repo_client.close(force=True)
                    raise
                finally:
                    if not reuse_log:
                        messages.close_log()

        return status

    def schema_sync(
        self,
        params: Any,
        execution_id: ExecutionId | None = None,
        reuse_log: bool = False,
        messages_override: OffloadMessages | None = None,
    ) -> Any:
        """Run Schema Sync using incoming params under a command-scoped ExecutionContext."""
        exec_id, messages, repo_client = self._init_command(
            orchestration_constants.COMMAND_SCHEMA_SYNC,
            params,
            execution_id=execution_id,
            reuse_log=reuse_log,
            messages_override=messages_override,
        )

        with bind_execution_context(messages.context):
            command_id = self._command_begin(
                orchestration_constants.COMMAND_SCHEMA_SYNC,
                params,
                repo_client,
                execution_id=exec_id,
                messages=messages,
            )
            try:
                raise OrchestrationRunnerException("Schema Sync no longer exists")
            except Exception as exc:
                self._command_fail(command_id, exc, repo_client, messages=messages)
                raise

    def _build_offload_source_table(
        self,
        operation: Any,
        messages: OffloadMessages,
    ) -> Any:
        return create_source_table(
            operation.owner,
            operation.table_name,
            self._config,
            messages,
            dry_run=(not operation.execute),
        )

    def _build_repo_client(self, messages: Any, dry_run: bool = False) -> OracleRepositoryService:
        return create_repository_client(
            self._config,
            messages,
            dry_run=dry_run,
            trace_action="repo_client(OrchestrationRunner)",
        )

    def _cleanup_objects(
        self,
        repo_client: Any,
        frontend_table: Any = None,
        backend_table: Any = None,
        messages: OffloadMessages | None = None,
    ) -> None:
        try:
            if frontend_table:
                frontend_table.close()
            if backend_table:
                backend_table.close()
            repo_client.close()
        except Exception as exc:
            self._log_error(
                f"Exception cleaning up connections: {exc!s}",
                detail=VVERBOSE,
                messages=messages,
            )

    def _command_begin(
        self,
        command_type: str,
        params: Any,
        repo_client: OracleRepositoryService,
        operation: Any = None,
        execution_id: ExecutionId | None = None,
        messages: OffloadMessages | None = None,
    ) -> int | None:
        assert command_type
        assert params
        assert repo_client
        active_ctx = current_execution_context()
        resolved_exec_id = (
            execution_id
            or getattr(self, "_execution_id", None)
            or (active_ctx.execution_id if active_ctx is not None else None)
        )
        assert resolved_exec_id

        try:
            command_input: Any
            if isinstance(params, dict):
                command_input = params
            else:
                command_input = " ".join(sys.argv)

            operation_dict = operation if isinstance(operation, (dict, type(None))) else operation.vars()
            trace_ids = current_trace_ids()
            if trace_ids:
                operation_dict = {**(operation_dict or {}), **trace_ids}

            command_id = repo_client.start_command(
                resolved_exec_id,
                command_type,
                command_input,
                operation_dict,
            )
            self._log(
                f"Command id for execution {resolved_exec_id}: {command_id}",
                detail=VVERBOSE,
                messages=messages,
            )
        except Exception as exc:
            self._log_error(
                f"Exception starting command {resolved_exec_id}: {exc!s}",
                detail=VVERBOSE,
                messages=messages,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE, messages=messages)
            raise
        return command_id

    def _command_end(
        self,
        command_id: int | None,
        repo_client: OracleRepositoryService,
        messages: OffloadMessages | None = None,
    ) -> None:
        assert repo_client
        try:
            repo_client.end_command(command_id, orchestration_constants.COMMAND_SUCCESS)
        except Exception as exc:
            self._log_error(
                f"Exception closing command {command_id}: {exc!s}",
                detail=VVERBOSE,
                messages=messages,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE, messages=messages)
            raise

    def _command_fail(
        self,
        command_id: int | None,
        external_exc: Exception,
        repo_client: OracleRepositoryService,
        messages: OffloadMessages | None = None,
    ) -> None:
        assert repo_client
        self._log_error(
            f"Failing command due to exception: {external_exc!s}",
            detail=VVERBOSE,
            messages=messages,
        )
        self._log(
            f"External exception stack: {traceback.format_tb(external_exc.__traceback__)}",
            detail=VVERBOSE,
            messages=messages,
        )
        try:
            repo_client.end_command(command_id, orchestration_constants.COMMAND_ERROR)
        except Exception as local_exc:
            self._log_error(
                f"Exception failing command {command_id}: {local_exc!s}",
                detail=VVERBOSE,
                messages=messages,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE, messages=messages)
            raise

    def _execute_from_params(self, params: Any) -> bool:
        if isinstance(params, dict):
            return bool(params["execute"])
        return bool(params.execute)

    def _gen_config(self, config_overrides: Any, suppress_stdout: bool = False) -> OrchestrationConfig:
        overrides = dict(config_overrides) if config_overrides else {}
        if suppress_stdout:
            overrides["suppress_stdout"] = suppress_stdout
        return OrchestrationConfig.from_dict(overrides)

    def _gen_messages(
        self,
        execution_id: ExecutionId,
        command_type: str,
        context: ExecutionContext | None = None,
    ) -> OffloadMessages:
        return OffloadMessages.from_options(
            self._config,
            log_fh=get_log_fh(),
            execution_id=execution_id,
            command_type=command_type,
            context=context,
        )

    def _gen_offload_operation(
        self,
        params: Any,
        repo_client: OracleRepositoryService,
        execution_id: ExecutionId,
        messages: OffloadMessages,
    ) -> Any:
        """Return an OffloadOperation object based on either a parameter dict or options object."""
        try:
            if isinstance(params, dict):
                return OffloadOperation.from_dict(
                    params,
                    self._config,
                    messages,
                    repo_client=repo_client,
                    execution_id=execution_id,
                )
            return OffloadOperation.from_options(
                params,
                self._config,
                messages,
                repo_client=repo_client,
                execution_id=execution_id,
            )
        except Exception as exc:
            self._log_error(
                f"Exception generating offload operation {execution_id}: {exc!s}",
                detail=VVERBOSE,
                messages=messages,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE, messages=messages)
            raise

    def _get_execution_id(self, execution_id: ExecutionId | None = None) -> ExecutionId:
        """Return an ID to uniquely identify an orchestration command."""
        if execution_id is None:
            execution_id = ExecutionId()
        return execution_id

    def _init_command(
        self,
        command: str,
        params: Any,
        execution_id: ExecutionId | None = None,
        reuse_log: bool = False,
        messages_override: OffloadMessages | None = None,
    ) -> tuple[ExecutionId, OffloadMessages, OracleRepositoryService]:
        """Initialize an orchestration command without mutating runner instance state."""
        exec_id = self._get_execution_id(execution_id=execution_id)
        self._init_command_log(command, params, reuse_log=reuse_log)
        base_ctx = current_execution_context() or ExecutionContext.for_console(
            detail=OffloadMessages.detail_from_options(self._config),
            ansi=bool(getattr(self._config, "ansi", True)),
        )
        base_ctx = base_ctx.with_execution(execution_id=exec_id, command_type=command)
        if self._sinks:
            base_ctx = base_ctx.with_sinks(*self._sinks)

        messages = messages_override or self._gen_messages(exec_id, command, context=base_ctx)
        try:
            if messages_override is not None:
                if messages.execution_id is None:
                    messages.set_execution_id(exec_id)
                if self._sinks:
                    messages._extra_sinks = (*getattr(messages, "_extra_sinks", ()), *self._sinks)
                    messages._ctx = messages._build_context()
            self._log(
                "{} ExecutionId: {}".format(
                    "Using overridden" if execution_id else "Generated",
                    exec_id,
                ),
                detail=VVERBOSE,
                messages=messages,
            )
            repo_client = self._build_repo_client(
                messages,
                dry_run=(not self._execute_from_params(params)),
            )
            messages.setup_offload_step(repo_client=repo_client, command_type=command)
            return exec_id, messages, repo_client
        except Exception as exc:
            self._log_error(
                f"Exception initializing command {command}: {exc!s}",
                detail=VVERBOSE,
                messages=messages,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE, messages=messages)
            raise

    def _init_command_log(self, command: str, params: Any, reuse_log: bool = False) -> None:
        """Create a log file for the orchestration command and bind it to the active ExecutionContext."""

        def get_owner_table_for_command() -> str | None:
            if command == COMMAND_ID_CONNECT:
                return None
            param_name = "owner_table"
            owner_table = params.get(param_name) if isinstance(params, dict) else getattr(params, param_name, None)
            if not owner_table:
                raise OrchestrationRunnerException(f"Missing owner/table parameter for command: {command}")
            return str(owner_table)

        init(self._config)
        if not reuse_log:
            owner_table_token = get_owner_table_for_command()
            log_prefix = LOG_FILE_PREFIXES[command]
            if owner_table_token:
                init_log(f"{log_prefix}_{owner_table_token}")
            else:
                init_log(f"{log_prefix}")

    def _debug(self, msg: str, messages: OffloadMessages | None = None) -> None:
        logger.debug(msg)
        if messages is not None:
            messages.debug(msg)

    def _log(
        self,
        msg: str,
        detail: int = NORMAL,
        ansi_code: Any = None,
        messages: OffloadMessages | None = None,
    ) -> None:
        """Write to offload log file."""
        if detail == VVERBOSE:
            logger.debug(msg)
        else:
            logger.info(msg)
        if messages is not None:
            messages.log(msg, detail=detail, ansi_code=ansi_code)

    def _log_error(
        self,
        msg: str,
        detail: int = NORMAL,
        messages: OffloadMessages | None = None,
    ) -> None:
        logger.error(msg)
        if messages is not None:
            messages.log(msg, detail=detail)

    def _log_final_messages(
        self,
        command_type: str,
        dry_run: bool,
        *,
        messages: OffloadMessages,
    ) -> None:
        messages.log_step_deltas()
        if messages.get_messages():
            messages.offload_step(
                command_steps.STEP_MESSAGES,
                messages.log_messages,
                command_type=command_type,
                execute=(not dry_run),
            )

    def _offload(
        self,
        operation: Any,
        offload_source_table: Any,
        offload_target_table: Any,
        messages: OffloadMessages,
    ) -> Any:
        with orchestration_lock_for_table(
            offload_source_table.owner,
            offload_source_table.table_name,
            dry_run=(not operation.execute),
        ):
            try:
                return offload_table(
                    self._config,
                    operation,
                    offload_source_table,
                    offload_target_table,
                    messages,
                )
            except Exception as exc:
                try:
                    self._log_error(f"Unhandled exception in offload_table(): {exc!s}", messages=messages)
                    self._log_error(traceback.format_exc(), detail=VVERBOSE, messages=messages)
                except Exception:
                    pass
                raise

    def _target_version_string(self, backend_table: Any) -> str:
        target_version = backend_table.target_version()
        ver_str = f" ({target_version})" if target_version else ""
        return "%s%s" % (backend_table.backend_db_name(), ver_str)
