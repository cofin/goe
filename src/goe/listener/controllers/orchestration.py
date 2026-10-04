# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Orchestration controller for Litestar GOE Listener."""

from pathlib import Path
from typing import Any, ClassVar

from litestar import get, post
from litestar.di import NamedDependency
from litestar.params import FromPath, FromQuery, JSONBody
from litestar_queues import QueueService
from litestar_security import AuthenticationPolicy, SecureController, required

from goe.listener import exceptions, jobs, schemas, utils
from goe.listener.services.system import SystemService
from goe.orchestration.execution_id import ExecutionId
from goe.util.sync_tools import async_


class OrchestrationController(SecureController):
    """Controller for /api/orchestration endpoints."""

    path = "/api/orchestration"
    tags: ClassVar[list[str]] = ["Orchestration"]
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get("/executions/", mcp_tool="get_command_executions")
    async def get_command_executions(
        self,
        system_service: NamedDependency[SystemService],
        include_steps: FromQuery[bool] = False,
    ) -> schemas.CommandExecutions:
        """Fetch command executions from repo."""
        executions = await async_(system_service.get_command_executions)()
        if include_steps:
            all_steps = await async_(system_service.get_command_execution_steps)(execution_id=None)
            grouped = utils.groupby(
                lambda s: (
                    ExecutionId.from_bytes(s.get("execution_id")).as_str()
                    if isinstance(s.get("execution_id"), bytes)
                    else str(s.get("execution_id"))
                ),
                all_steps,
            )
            for item in executions:
                exec_key = (
                    ExecutionId.from_bytes(item["execution_id"]).as_str()
                    if isinstance(item["execution_id"], bytes)
                    else str(item["execution_id"])
                )
                item["steps"] = grouped.get(exec_key, [])
        return schemas.CommandExecutions(count=len(executions), results=executions)

    @get("/executions/{execution_id:str}/", mcp_tool="get_command_execution")
    async def get_command_execution(
        self,
        system_service: NamedDependency[SystemService],
        execution_id: FromPath[str],
        include_steps: FromQuery[bool] = False,
    ) -> dict[str, Any]:
        """Fetch details of a specific command execution."""
        execution_identifier = ExecutionId.from_str(execution_id)
        execution = await async_(system_service.get_command_execution)(execution_identifier)
        if not execution:
            raise exceptions.CommandExecutionNotFound(execution_id)

        if include_steps:
            steps = await async_(system_service.get_command_execution_steps)(execution_identifier)
            if steps:
                execution["steps"] = steps
        return execution

    @get("/executions/{execution_id:str}/execution-log/", mcp_tool="get_command_execution_log")
    async def get_command_execution_log(
        self,
        system_service: NamedDependency[SystemService],
        execution_id: FromPath[str],
    ) -> schemas.CommandExecutionLog:
        """Fetch log contents of a specific command execution."""
        execution_identifier = ExecutionId.from_str(execution_id)
        execution = await async_(system_service.get_command_execution)(execution_identifier)
        if not execution:
            raise exceptions.CommandExecutionNotFound(execution_id)

        log_path = Path(execution.get("command_log_path", ""))
        file_name = log_path.stem
        if log_path.exists():
            contents = log_path.read_text(errors="replace")
            return schemas.CommandExecutionLog(name=file_name, is_file=True, message=contents)

        return schemas.CommandExecutionLog(
            name=file_name,
            is_file=True,
            message=f"Log file for execution {execution_identifier.id} not found.",
        )

    @post("/offload/", mcp_tool="execute_offload")
    async def execute_offload_command(
        self,
        data: JSONBody[schemas.OffloadOptions],
        queue_service: NamedDependency[QueueService],
    ) -> schemas.CommandScheduled:
        """Submit a background offload operation."""
        utils.orchestrate.check_for_running_command(data.owner_table)
        execution_identifier = ExecutionId()
        params = data.to_params_dict()

        await queue_service.enqueue(
            jobs.run_offload_job,
            params=params,
            execution_id=execution_identifier.as_str(),
        )

        return schemas.CommandScheduled(execution_id=str(execution_identifier.id))
