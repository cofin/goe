# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Orchestration controller for Litestar GOE Listener."""

from pathlib import Path
from typing import Annotated, Any

import msgspec
from litestar import Controller, get, post
from litestar.params import Dependency, Parameter
from litestar_queues import QueueService

from goe.listener import exceptions, jobs, schemas, utils
from goe.listener.services.system import SystemService
from goe.orchestration.execution_id import ExecutionId
from goe.util.sync_tools import async_


class OrchestrationController(Controller):
    """Controller for /api/orchestration endpoints."""

    path = "/api/orchestration"
    tags = ["Orchestration"]

    @get("/executions/")
    async def get_command_executions(
        self,
        system_service: Annotated[SystemService, Dependency(skip_validation=True)],
        include_steps: Annotated[bool, Parameter(query="include_steps", default=False)] = False,
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

    @get("/executions/{execution_id:str}/")
    async def get_command_execution(
        self,
        system_service: Annotated[SystemService, Dependency(skip_validation=True)],
        execution_id: Annotated[str, Parameter(title="Execution ID")],
        include_steps: Annotated[bool, Parameter(query="include_steps", default=False)] = False,
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

    @get("/executions/{execution_id:str}/execution-log/")
    async def get_command_execution_log(
        self,
        system_service: Annotated[SystemService, Dependency(skip_validation=True)],
        execution_id: Annotated[str, Parameter(title="Execution ID")],
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

    @post("/offload/")
    async def execute_offload_command(
        self,
        data: schemas.OffloadOptions,
        queue_service: Annotated[QueueService, Dependency(skip_validation=True)],
    ) -> schemas.CommandScheduled:
        """Submit a background offload operation."""
        utils.orchestrate.check_for_running_command(data.owner_table)
        execution_identifier = ExecutionId()
        params = {k: v for k, v in msgspec.structs.asdict(data).items() if v is not None}

        # Enqueue background task
        await queue_service.enqueue(
            jobs.run_offload_job,
            params=params,
            execution_id=execution_identifier.as_str(),
        )

        return schemas.CommandScheduled(execution_id=str(execution_identifier.id))
