# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Orchestration controller for Litestar GOE Listener."""

from __future__ import annotations

import asyncio
from typing import ClassVar, cast

import msgspec
from litestar import get, post
from litestar.di import NamedDependency
from litestar.params import FromPath, FromQuery, JSONBody
from litestar_mcp import MCPResourceLink, MCPToolResult, get_mcp_request_context, mcp_tool
from litestar_security import AuthenticationPolicy, SecureController, required
from opentelemetry import trace

from goe.listener import exceptions, schemas, utils
from goe.listener.cache import ListenerCache
from goe.listener.jobs.models import JobState
from goe.listener.jobs.store import DuplicateActiveTableJobError, JobStoreProtocol
from goe.listener.mcp import (
    DESTRUCTIVE_TOOL_ANNOTATIONS,
    READ_ONLY_TOOL_ANNOTATIONS,
    ConfirmationGate,
)
from goe.listener.services.operations import ListenerOperationsService
from goe.listener.services.system import SystemService
from goe.orchestration.execution_id import ExecutionId
from goe.util.concurrency import async_

__all__ = ("OrchestrationController",)


class OrchestrationController(SecureController):
    """Controller for /api/orchestration endpoints."""

    path = "/api/orchestration"
    tags = ["Orchestration"]
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get("/executions/")
    @mcp_tool(
        "get_command_executions",
        description="List historical and active GOE command executions recorded in the repository.",
        when_to_use="When auditing recent offload or schema operations and their completion statuses.",
        returns="CommandExecutions containing count and typed CommandExecution records.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
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

    @get("/executions/{execution_id:str}/")
    @mcp_tool(
        "get_command_execution",
        description="Retrieve detailed status, parameters, and optional step timings for a single command execution.",
        when_to_use="When inspecting step-by-step progress or failure details for a known execution_id.",
        returns="CommandExecution with status, parameters, log path, and optional steps.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_command_execution(
        self,
        system_service: NamedDependency[SystemService],
        execution_id: FromPath[str],
        include_steps: FromQuery[bool] = False,
    ) -> schemas.CommandExecution:
        """Fetch typed details of a specific command execution."""
        execution_identifier = _parse_execution_id(execution_id)
        execution = await async_(system_service.get_command_execution)(execution_identifier)
        if not execution:
            raise exceptions.CommandExecutionNotFound(execution_id)

        resolved_steps: list[schemas.CommandExecutionStep] | None = None
        if include_steps:
            raw_steps = await async_(system_service.get_command_execution_steps)(execution_identifier)
            resolved_steps = [schemas.CommandExecutionStep.from_item(step) for step in (raw_steps or [])]
        return schemas.CommandExecution.from_item(execution, steps=resolved_steps)

    @get("/executions/{execution_id:str}/execution-log/")
    @mcp_tool(
        "get_command_execution_log",
        description="Read the bounded tail of a command execution log file from local disk or cloud storage.",
        when_to_use="When diagnosing a failed or running execution and inspecting its log output.",
        returns="CommandExecutionLog with bounded log text and goe:// resource URI.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_command_execution_log(
        self,
        system_service: NamedDependency[SystemService],
        execution_id: FromPath[str],
    ) -> schemas.CommandExecutionLog:
        """Fetch bounded log contents of a specific command execution."""
        execution_identifier = _parse_execution_id(execution_id)
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
            log_resource_uri=f"goe://executions/{execution_identifier.as_str()}/log",
        )

    @get("/executions/{execution_id:str}/execution-log/link/")
    @mcp_tool(
        "get_execution_log_link",
        description="Return an MCPResourceLink pointer to the execution log resource without inlining the log body.",
        when_to_use="When referencing an execution log URI for on-demand client fetching via resources/read.",
        returns="MCPResourceLink pointing to goe://executions/{execution_id}/log.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_execution_log_link(
        self,
        execution_id: FromPath[str],
    ) -> MCPResourceLink:
        """Return an MCPResourceLink pointing to goe://executions/{execution_id}/log."""
        execution_identifier = _parse_execution_id(execution_id)
        canonical_id = execution_identifier.as_str()
        return MCPResourceLink(
            name=f"execution-{canonical_id}.log",
            uri=f"goe://executions/{canonical_id}/log",
            mime_type="application/json",
            description=f"Bounded GOE command execution log for {canonical_id}.",
        )

    @get("/jobs/")
    @mcp_tool(
        "list_offload_jobs",
        description="List durable GOE Listener background jobs ordered by creation time descending.",
        when_to_use="When monitoring queued, running, failed, or cancelled background offload jobs.",
        returns="JobListResponse with count and JobStatusResponse entries.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def list_offload_jobs(
        self,
        job_store: NamedDependency[JobStoreProtocol],
        status: FromQuery[str | None] = None,
        limit: FromQuery[int] = 100,
    ) -> schemas.JobListResponse:
        """List recent durable offload jobs from JobStoreProtocol."""
        parsed_status: JobState | None = None
        if status is not None:
            try:
                parsed_status = JobState(status.strip().upper())
            except ValueError as exc:
                raise exceptions.ApplicationError(
                    status_code=400,
                    message=f"Invalid job status: {status}",
                ) from exc
        bounded_limit = max(1, min(limit, 500))
        records = await asyncio.to_thread(job_store.list_jobs, limit=bounded_limit, status=parsed_status)
        results = [schemas.JobStatusResponse.from_record(record) for record in records]
        return schemas.JobListResponse(count=len(results), results=results)

    @get("/jobs/{execution_id:str}/")
    @mcp_tool(
        "get_offload_job",
        description="Retrieve the durable queue status, lease, retry attempt, and error message for a job.",
        when_to_use="When polling the lifecycle state of a queued or running offload job by execution_id.",
        returns="JobStatusResponse for the requested execution_id.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_offload_job(
        self,
        job_store: NamedDependency[JobStoreProtocol],
        execution_id: FromPath[str],
    ) -> schemas.JobStatusResponse:
        """Return durable job queue status for execution_id or raise 404 when absent."""
        execution_identifier = _parse_execution_id(execution_id)
        record = await asyncio.to_thread(job_store.get_job_by_execution_id, execution_identifier.as_str())
        if record is None:
            raise exceptions.CommandExecutionNotFound(execution_id)
        return schemas.JobStatusResponse.from_record(record)

    @post("/offload/preview/")
    @mcp_tool(
        "preview_offload_plan",
        description="Compute a side-effect-free dry-run OffloadPlanPreview and mint a confirmation_token.",
        agent_instructions=(
            "Call this read-only preview tool before execute_offload to inspect target DDL, partitions, "
            "and estimated row/byte volume, and to obtain a signed confirmation_token."
        ),
        when_to_use="Before executing any table offload to verify the staged OffloadPlan and DDL.",
        returns="OffloadPlanPreview with DDL, partition list, estimates, and signed ConfirmationChallenge.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def preview_offload_plan(
        self,
        data: JSONBody[schemas.OffloadOptions],
        operations_service: NamedDependency[ListenerOperationsService],
    ) -> schemas.OffloadPlanPreview:
        """Compute a side-effect-free dry-run OffloadPlanPreview off the asyncio event loop."""
        return await async_(operations_service.preview_offload)(data)

    @post("/offload/")
    @mcp_tool(
        "execute_offload",
        description="Enqueue a durable GOE table offload operation into the background job worker.",
        agent_instructions=(
            "Always run preview_offload_plan first to inspect the staged OffloadPlan and obtain a signed "
            "confirmation_token, or complete the two-round MRTR confirmation challenge when execute=True."
        ),
        when_to_use="After verifying connectivity, table metadata, and preview_offload_plan for the target table.",
        returns="CommandScheduled with execution_id and QUEUED status (plus job/log resource links in MCP).",
        annotations=DESTRUCTIVE_TOOL_ANNOTATIONS,
        task_support="optional",
        task_input_before_start=True,
    )
    async def execute_offload_command(
        self,
        data: JSONBody[schemas.OffloadOptions],
        job_store: NamedDependency[JobStoreProtocol],
        confirmation_gate: NamedDependency[ConfirmationGate],
    ) -> schemas.CommandScheduled:
        """Submit a durable background offload operation."""
        try:
            ctx = get_mcp_request_context()
        except RuntimeError:
            ctx = None

        params = data.to_params_dict()
        should_execute = data.execute is not False
        if ctx is not None and should_execute:
            challenge_result = confirmation_gate.require_mcp_confirmation(
                tool_name="execute_offload",
                owner_table=data.owner_table,
                payload=params,
                confirmation_token=data.confirmation_token,
            )
            if challenge_result is not None:
                return cast("schemas.CommandScheduled", challenge_result)

        utils.orchestrate.check_for_running_command(data.owner_table)
        execution_identifier = ExecutionId()
        canonical_id = execution_identifier.as_str()
        trace.get_current_span().set_attribute("goe.execution.id", canonical_id)

        try:
            await asyncio.to_thread(
                job_store.enqueue,
                execution_id=canonical_id,
                owner_table=data.owner_table,
                payload=params,
            )
        except DuplicateActiveTableJobError as exc:
            raise exceptions.ApplicationError(status_code=409, message=str(exc)) from exc

        scheduled = schemas.CommandScheduled(execution_id=canonical_id)
        if ctx is not None:
            return cast(
                "schemas.CommandScheduled",
                MCPToolResult(
                    content=[
                        MCPResourceLink(
                            name=f"job-{canonical_id}",
                            uri=f"goe://jobs/{canonical_id}",
                            mime_type="application/json",
                            description=f"Durable job status for {canonical_id}.",
                        ),
                        MCPResourceLink(
                            name=f"execution-{canonical_id}.log",
                            uri=f"goe://executions/{canonical_id}/log",
                            mime_type="application/json",
                            description=f"Bounded command execution log for {canonical_id}.",
                        ),
                    ],
                    structured_content=msgspec.structs.asdict(scheduled),
                ),
            )
        return scheduled


def _parse_execution_id(raw_id: str) -> ExecutionId:
    """Parse raw_id into an ExecutionId or raise HTTP 400 ApplicationError on invalid UUID syntax."""
    try:
        return ExecutionId.from_str(raw_id)
    except (ValueError, TypeError, AssertionError) as exc:
        raise exceptions.ApplicationError(
            status_code=400,
            message=f"Invalid execution_id UUID: {raw_id}",
        ) from exc
