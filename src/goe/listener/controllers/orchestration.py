# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Orchestration controller for Litestar GOE Listener."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from litestar import get, post
from litestar.di import NamedDependency
from litestar.params import FromPath, FromQuery, JSONBody
from litestar_security import AuthenticationPolicy, SecureController, required
from opentelemetry import trace

from goe.listener import exceptions, schemas, utils
from goe.listener.cache import ListenerCache
from goe.listener.jobs.store import DuplicateActiveTableJobError, JobStoreProtocol
from goe.listener.services.system import SystemService
from goe.orchestration.execution_id import ExecutionId
from goe.util.concurrency import async_

__all__ = ("OrchestrationController",)


class OrchestrationController(SecureController):
    """Controller for /api/orchestration endpoints."""

    path = "/api/orchestration"
    tags = ["Orchestration"]
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get("/executions/", mcp_tool="get_command_executions")
    async def get_command_executions(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        include_steps: FromQuery[bool] = False,
    ) -> schemas.CommandExecutions:
        """Fetch command executions from repository backed by ListenerCache."""
        cache_key = f"executions:list:steps={int(bool(include_steps))}"

        async def _load_executions() -> list[schemas.CommandExecution]:
            executions = await async_(system_service.get_command_executions)()
            grouped_steps: dict[str, list[schemas.CommandExecutionStep]] = {}
            if include_steps:
                all_steps = await async_(system_service.get_command_execution_steps)(execution_id=None)
                for raw_step in all_steps or []:
                    step_obj = schemas.CommandExecutionStep.from_item(raw_step)
                    exec_key = step_obj.execution_id or ""
                    grouped_steps.setdefault(exec_key, []).append(step_obj)

            results: list[schemas.CommandExecution] = []
            for item in executions or []:
                base = schemas.CommandExecution.from_item(item)
                steps = grouped_steps.get(base.execution_id, base.steps) if include_steps else base.steps
                results.append(schemas.CommandExecution.from_item(item, steps=steps))
            return results

        typed_results = await listener_cache.get_or_load(cache_key, _load_executions)
        return schemas.CommandExecutions(count=len(typed_results), results=typed_results)

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

        result = dict(execution)
        if "execution_id" in result and result["execution_id"] is not None:
            result["execution_id"] = _normalize_execution_id(result["execution_id"])

        if include_steps:
            steps = await async_(system_service.get_command_execution_steps)(execution_identifier)
            if steps:
                normalized_steps: list[dict[str, Any]] = []
                for step in steps:
                    step_copy = dict(step)
                    if "execution_id" in step_copy and step_copy["execution_id"] is not None:
                        step_copy["execution_id"] = _normalize_execution_id(step_copy["execution_id"])
                    normalized_steps.append(step_copy)
                result["steps"] = normalized_steps
        return result

    @get("/executions/{execution_id:str}/execution-log/", mcp_tool="get_command_execution_log")
    async def get_command_execution_log(
        self,
        system_service: NamedDependency[SystemService],
        execution_id: FromPath[str],
    ) -> schemas.CommandExecutionLog:
        """Fetch bounded log contents of a specific command execution."""
        execution_identifier = ExecutionId.from_str(execution_id)
        execution = await async_(system_service.get_command_execution)(execution_identifier)
        if not execution:
            raise exceptions.CommandExecutionNotFound(execution_id)

        raw_log_path = str(execution.get("command_log_path") or "")
        dfs_client = getattr(system_service, "get_dfs_client", lambda: None)()
        file_name, is_file, message = await asyncio.to_thread(
            utils.orchestrate.read_execution_log_bounded,
            raw_log_path,
            execution_id=str(execution_identifier.id),
            dfs_client=dfs_client,
        )
        return schemas.CommandExecutionLog(
            name=file_name,
            is_file=is_file,
            message=message,
        )

    @post("/offload/", mcp_tool="execute_offload")
    async def execute_offload_command(
        self,
        data: JSONBody[schemas.OffloadOptions],
        job_store: NamedDependency[JobStoreProtocol],
    ) -> schemas.CommandScheduled:
        """Submit a durable background offload operation."""
        utils.orchestrate.check_for_running_command(data.owner_table)
        execution_identifier = ExecutionId()
        trace.get_current_span().set_attribute("goe.execution.id", execution_identifier.as_str())
        params = data.to_params_dict()

        try:
            await asyncio.to_thread(
                job_store.enqueue,
                execution_id=execution_identifier.as_str(),
                owner_table=data.owner_table,
                payload=params,
            )
        except DuplicateActiveTableJobError as exc:
            raise exceptions.ApplicationError(status_code=409, message=str(exc)) from exc

        return schemas.CommandScheduled(execution_id=str(execution_identifier.id))


def _normalize_execution_id(raw_id: Any) -> str:
    """Convert raw bytes or UUID execution_id values into canonical string form."""
    if isinstance(raw_id, bytes):
        return ExecutionId.from_bytes(raw_id).as_str()
    return str(raw_id)
