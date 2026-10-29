# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OrchestrationRunner: Library providing simple entry point for orchestration commands.
Utilized by both CLI and Orchestration Listener.
"""

import logging
import sys
import traceback
from typing import TYPE_CHECKING, Any

from goe.config.orchestration_config import OrchestrationConfig
from goe.goe import (
    OffloadOperation,
    get_log_fh,
    get_offload_target_table,
    init,
    init_log,
    offload_table,
)
from goe.observability.runtime import ensure_observability
from goe.observability.spans import current_trace_ids, traced_command
from goe.offload.offload_messages import (
    NORMAL,
    VVERBOSE,
    OffloadMessages,
)
from goe.offload.registry import (
    create_frontend_api,
    create_repository_client,
    create_source_table,
)
from goe.orchestration import command_steps, orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.platform.locking import orchestration_lock_for_table

if TYPE_CHECKING:
    from goe.persistence.orchestration_repo_client import (
        OrchestrationRepoClientInterface,
    )


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OrchestrationRunnerException(Exception):
    pass


COMMAND_ID_CONNECT = "CONNECT"

LOG_FILE_PREFIXES = {
    COMMAND_ID_CONNECT: "connect",
    orchestration_constants.COMMAND_OFFLOAD: "offload",
    orchestration_constants.COMMAND_SCHEMA_SYNC: "schema_sync",
}


class OrchestrationRunner:
    """OrchestrationRunner: Library providing simple entry point for orchestration commands."""

    def __init__(self, config_overrides=None, suppress_stdout=False):
        self._config = self._gen_config(config_overrides, suppress_stdout=suppress_stdout)
        ensure_observability(self._config)
        self._execution_id: ExecutionId | None = None
        self._messages: OffloadMessages | None = None
        self._max_hybrid_name_length: int | None = None

    def offload(
        self,
        params: Any,
        execution_id: ExecutionId | None = None,
        reuse_log: bool = False,
        messages_override: OffloadMessages | None = None,
    ) -> Any:
        """Run an offload based on incoming params.

        params: Can be a dict or an OptParse object.
        execution_id: A UUID used to uniquely identify the Offload. Can be generted internally or provided as
                      an override.
        reuse_log: True indicates that there is already a log file installed in goe.py for us to integrate with.
        messages_override: Allows us to pass in an existing messages object so a parent can inspect the messages,
                           used for testing.
        """
        dry_run = bool(not self._execute_from_params(params))
        repo_client = self._init_command(
            orchestration_constants.COMMAND_OFFLOAD,
            params,
            execution_id=execution_id,
            reuse_log=reuse_log,
            messages_override=messages_override,
        )

        operation = self._gen_offload_operation(params, repo_client)
        with traced_command(
            orchestration_constants.COMMAND_OFFLOAD,
            self._execution_id,
            backend=self._config.target,
            dry_run=dry_run,
            source_owner=operation.owner,
            source_table=operation.table_name,
        ):
            command_id = self._command_begin(orchestration_constants.COMMAND_OFFLOAD, params, repo_client, operation)
            try:
                offload_source_table = self._build_offload_source_table(operation)
                offload_target_table = get_offload_target_table(operation, self._config, self._messages)

                self._log(f"Offloading to {self._target_version_string(offload_target_table)}")

                status = self._offload(operation, offload_source_table, offload_target_table)
                self._log_final_messages(orchestration_constants.COMMAND_OFFLOAD, dry_run)

                self._command_end(command_id, repo_client)
                self._cleanup_objects(
                    repo_client,
                    frontend_table=offload_source_table,
                    backend_table=offload_target_table,
                )
            except Exception as exc:
                self._command_fail(command_id, exc, repo_client)
                repo_client.close(force=True)
                raise
            finally:
                if not reuse_log and self._messages is not None:
                    self._messages.close_log()

        return status

    def schema_sync(
        self,
        params: Any,
        execution_id: ExecutionId | None = None,
        reuse_log: bool = False,
        messages_override: OffloadMessages | None = None,
    ) -> Any:
        """Run Schema Sync using incoming params."""
        repo_client = self._init_command(
            orchestration_constants.COMMAND_SCHEMA_SYNC,
            params,
            execution_id=execution_id,
            reuse_log=reuse_log,
            messages_override=messages_override,
        )

        command_id = self._command_begin(orchestration_constants.COMMAND_SCHEMA_SYNC, params, repo_client)
        try:
            raise OrchestrationRunnerException("Schema Sync no longer exists")
        except Exception as exc:
            self._command_fail(command_id, exc, repo_client)
            raise

    def _build_offload_source_table(self, operation):
        return create_source_table(
            operation.owner,
            operation.table_name,
            self._config,
            self._messages,
            dry_run=(not operation.execute),
        )

    def _build_repo_client(self, messages: Any, dry_run: bool = False) -> "OrchestrationRepoClientInterface":
        return create_repository_client(
            self._config,
            messages,
            dry_run=dry_run,
            trace_action="repo_client(OrchestrationRunner)",
        )

    def _cleanup_objects(self, repo_client, frontend_table=None, backend_table=None):
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
            )

    def _command_begin(
        self,
        command_type: str,
        params: Any,
        repo_client: "OrchestrationRepoClientInterface",
        operation: Any = None,
    ) -> int:
        assert command_type
        assert params
        assert repo_client
        assert self._execution_id

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
                self._execution_id,
                command_type,
                command_input,
                operation_dict,
            )
            self._log(
                f"Command id for execution {self._execution_id}: {command_id}",
                detail=VVERBOSE,
            )
        except Exception as exc:
            self._log_error(
                f"Exception starting command {self._execution_id}: {exc!s}",
                detail=VVERBOSE,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE)
            raise
        return command_id

    def _command_end(self, command_id: int, repo_client: "OrchestrationRepoClientInterface") -> None:
        assert repo_client
        try:
            repo_client.end_command(command_id, orchestration_constants.COMMAND_SUCCESS)
        except Exception as exc:
            self._log_error(f"Exception closing command {command_id}: {exc!s}", detail=VVERBOSE)
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE)
            raise

    def _command_fail(
        self,
        command_id: int,
        external_exc: Exception,
        repo_client: "OrchestrationRepoClientInterface",
    ) -> None:
        assert repo_client
        self._log_error(f"Failing command due to exception: {external_exc!s}", detail=VVERBOSE)
        self._log(
            f"External exception stack: {traceback.format_tb(external_exc.__traceback__)}",
            detail=VVERBOSE,
        )
        try:
            repo_client.end_command(command_id, orchestration_constants.COMMAND_ERROR)
        except Exception as local_exc:
            self._log_error(
                f"Exception failing command {command_id}: {local_exc!s}",
                detail=VVERBOSE,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE)
            raise

    def _execute_from_params(self, params: Any) -> bool:
        if isinstance(params, dict):
            return bool(params["execute"])
        return bool(params.execute)

    def _gen_config(self, config_overrides: Any, suppress_stdout: bool = False) -> OrchestrationConfig:
        overrides = config_overrides or {}
        if suppress_stdout:
            overrides["suppress_stdout"] = suppress_stdout
        return OrchestrationConfig.from_dict(overrides)

    def _gen_messages(self, execution_id, command_type):
        return OffloadMessages.from_options(
            self._config,
            log_fh=get_log_fh(),
            execution_id=execution_id,
            command_type=command_type,
        )

    def _gen_offload_operation(
        self,
        params: Any,
        repo_client: "OrchestrationRepoClientInterface",
    ) -> Any:
        """Return an OffloadOperation object based on either a parameter dict or OptParse object."""
        try:
            max_hybrid_name_length = self._get_max_hybrid_identifier_length(
                dry_run=bool(not self._execute_from_params(params))
            )
            if isinstance(params, dict):
                op = OffloadOperation.from_dict(
                    params,
                    self._config,
                    self._messages,
                    repo_client=repo_client,
                    execution_id=self._execution_id,
                    max_hybrid_name_length=max_hybrid_name_length,
                )
            else:
                op = OffloadOperation.from_options(
                    params,
                    self._config,
                    self._messages,
                    repo_client=repo_client,
                    execution_id=self._execution_id,
                    max_hybrid_name_length=max_hybrid_name_length,
                )
            return op
        except Exception as exc:
            self._log_error(
                f"Exception generating offload operation {self._execution_id}: {exc!s}",
                detail=VVERBOSE,
            )
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE)
            raise

    def _get_execution_id(self, execution_id: ExecutionId | None = None) -> ExecutionId:
        """Return an ID to uniquely identify an orchestration command."""
        if execution_id is None:
            execution_id = ExecutionId()
        return execution_id

    def _get_max_hybrid_identifier_length(self, dry_run: bool) -> int:
        """Get the max supported hybrid identifier (table/view/column) length for the frontend RDBMS.
        This is not ideal because it is making a frontend connection just to get this information but at the point
        this is called we don't already have a connection we can use.
        By storing self._max_hybrid_name_length in state we should not need to make the connection a second time.
        """
        if self._max_hybrid_name_length is None:
            frontend_api = create_frontend_api(
                self._config.db_type,
                self._config,
                self._messages,
                dry_run=dry_run,
                trace_action="_get_max_hybrid_identifier_length",
            )
            self._max_hybrid_name_length = frontend_api.max_table_name_length()
            frontend_api.close()
        return self._max_hybrid_name_length

    def _init_command(
        self,
        command: str,
        params: Any,
        execution_id: ExecutionId | None = None,
        reuse_log: bool = False,
        messages_override: OffloadMessages | None = None,
    ) -> "OrchestrationRepoClientInterface":
        """Initialize an orchestration command.
        Sets execution_id, messages in state and returns repo_client.
        We do NOT store repo_client in state because of multiprocess issues with oracledb.
        """
        self._init_command_log(command, params, reuse_log=reuse_log)
        self._execution_id = self._get_execution_id(execution_id=execution_id)
        self._messages = messages_override or self._gen_messages(self._execution_id, command)
        try:
            if messages_override and self._messages.execution_id is None:
                self._messages.set_execution_id(self._execution_id)
            self._log(
                "{} ExecutionId: {}".format(
                    "Using overridden" if execution_id else "Generated",
                    self._execution_id,
                ),
                detail=VVERBOSE,
            )
            return self._build_repo_client(self._messages, dry_run=(not self._execute_from_params(params)))
        except Exception as exc:
            self._log_error(f"Exception initializing command {command}: {exc!s}", detail=VVERBOSE)
            self._log(f"Exception stack: {traceback.format_exc()}", detail=VVERBOSE)
            raise

    def _init_command_log(self, command: str, params: Any, reuse_log: bool = False) -> None:
        """Create a log file for the orchestration command and set the global file handle in goe.py."""

        def get_owner_table_for_command():
            if command == COMMAND_ID_CONNECT:
                return None
            param_name = "owner_table"
            owner_table = params.get(param_name) if isinstance(params, dict) else getattr(params, param_name, None)
            if not owner_table:
                raise OrchestrationRunnerException(f"Missing owner/table parameter for command: {command}")
            return owner_table

        init(self._config)
        if not reuse_log:
            owner_table_token = get_owner_table_for_command()
            log_prefix = LOG_FILE_PREFIXES[command]
            if owner_table_token:
                init_log(f"{log_prefix}_{owner_table_token}")
            else:
                init_log(f"{log_prefix}")

    def _debug(self, msg):
        logger.debug(msg)
        if self._messages:
            self._messages.debug(msg)

    def _log(self, msg, detail=NORMAL, ansi_code=None):
        """Write to offload log file"""
        if detail == VVERBOSE:
            logger.debug(msg)
        else:
            logger.info(msg)
        if self._messages:
            self._messages.log(msg, detail=detail, ansi_code=ansi_code)

    def _log_error(self, msg, detail=NORMAL):
        logger.error(msg)
        if self._messages is not None:
            self._messages.log(msg, detail=detail)

    def _log_final_messages(self, command_type, dry_run):
        assert self._messages is not None
        self._messages.log_step_deltas()
        if self._messages.get_messages():
            self._messages.offload_step(
                command_steps.STEP_MESSAGES,
                self._messages.log_messages,
                command_type=command_type,
                execute=(not dry_run),
            )

    def _offload(self, operation, offload_source_table, offload_target_table):
        assert self._messages is not None
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
                    self._messages,
                )
            except Exception as exc:
                try:
                    self._log_error(f"Unhandled exception in offload_table(): {exc!s}")
                    self._log_error(traceback.format_exc(), detail=VVERBOSE)
                except:
                    pass
                raise

    def _target_version_string(self, backend_table):
        target_version = backend_table.target_version()
        ver_str = f" ({target_version})" if target_version else ""
        return "%s%s" % (backend_table.backend_db_name(), ver_str)
