# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Dedicated MCP resources controller exposing goe:// static and templated resources."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from litestar import get
from litestar.di import NamedDependency
from litestar.params import FromPath
from litestar_mcp import mcp_resource
from litestar_security import AuthenticationPolicy, SecureController, required

from goe.connect.models import ConnectivityReport
from goe.listener import exceptions, schemas, utils
from goe.listener.cache import ListenerCache
from goe.listener.exceptions import TableMetadataNotFound
from goe.listener.jobs.store import JobStoreProtocol
from goe.listener.mcp import ConfirmationGate
from goe.listener.services.system import SystemService
from goe.orchestration.execution_id import ExecutionId
from goe.report.models import StatusReportEnvelope, TableStatusReport
from goe.sync.differ import SchemaDiff
from goe.util.concurrency import async_

__all__ = ("GOEResourcesController",)


class GOEResourcesController(SecureController):
    """Hidden Litestar controller publishing static goe:// resources and RFC 6570 resource templates."""

    path = "/api/_mcp/resources"
    tags = ["MCP Resources"]
    include_in_schema = False
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get(
        "/system/status/",
        mcp_resource_uri="goe://system/status",
    )
    @mcp_resource(
        "system_status",
        description="GOE Listener application liveness and health status.",
        mime_type="application/json",
    )
    async def read_system_status(self) -> schemas.HealthCheck:
        """Return goe://system/status health resource."""
        return schemas.HealthCheck(status="OK")

    @get(
        "/system/connectivity/",
        mcp_resource_uri="goe://system/connectivity",
    )
    @mcp_resource(
        "system_connectivity",
        description="Frontend, backend, and staging storage connectivity probe results.",
        mime_type="application/json",
    )
    async def read_system_connectivity(
        self,
        system_service: NamedDependency[SystemService],
    ) -> ConnectivityReport:
        """Return goe://system/connectivity probe report."""
        return await asyncio.to_thread(system_service.check_connectivity)

    @get(
        "/system/config/",
        mcp_resource_uri="goe://system/config",
    )
    @mcp_resource(
        "system_config",
        description="GOE Listener endpoint configuration, database unique name, and frontend/backend types.",
        mime_type="application/json",
    )
    async def read_system_config(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        job_store: NamedDependency[JobStoreProtocol],
    ) -> schemas.ListenerConfig:
        """Return goe://system/config metadata resource."""
        heartbeats = await asyncio.to_thread(job_store.list_active_heartbeats)
        active_urls = [hb.host_url for hb in heartbeats if hb.host_url]
        if not active_urls and hasattr(system_service, "get_active_listener_endpoints"):
            fallback_endpoints = await system_service.get_active_listener_endpoints()
            active_urls = [str(item) for item in (fallback_endpoints or []) if item is not None]

        db_unique_name = await listener_cache.get_or_load(
            "system:db_unique_name",
            lambda: async_(system_service.get_db_unique_name)(),
        )
        return schemas.ListenerConfig(
            endpoint_id=str(system_service.generate_listener_endpoint_id()),
            listener_group_id=str(system_service.generate_listener_group_id()),
            db_unique_name=str(db_unique_name),
            active_listeners=active_urls,
            version=system_service.get_version(),
            frontend_type=system_service.get_frontend_type(),
            backend_type=system_service.get_backend_type(),
        )

    @get(
        "/reports/status/",
        mcp_resource_uri="goe://reports/status",
    )
    @mcp_resource(
        "status_report",
        description="Aggregated GOE Offload Status Report across schemas and tables.",
        mime_type="application/json",
    )
    async def read_status_report(
        self,
        system_service: NamedDependency[SystemService],
    ) -> StatusReportEnvelope:
        """Return goe://reports/status envelope resource."""
        return await async_(system_service.get_status_report)()

    @get(
        "/schemas/",
        mcp_resource_uri="goe://schemas",
    )
    @mcp_resource(
        "offloadable_schemas",
        description="Offloadable frontend database schemas and hybrid schema metadata.",
        mime_type="application/json",
    )
    async def read_schemas(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
    ) -> schemas.OffloadableSchemas:
        """Return goe://schemas catalog resource."""
        raw_schemas = await listener_cache.get_or_load(
            "schemas:all",
            lambda: async_(system_service.get_schemas)(),
        )
        typed_results = [schemas.OffloadableSchema.from_item(item) for item in (raw_schemas or [])]
        return schemas.OffloadableSchemas(count=len(typed_results), results=typed_results)

    @get(
        "/schemas/{schema_name:str}/tables/",
        mcp_resource="schema_tables",
        mcp_resource_template="goe://schemas/{schema_name}/tables",
        mcp_resource_description="Tables in a frontend schema with offload status and sizes.",
        mcp_resource_mime_type="application/json",
    )
    async def read_schema_tables(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
    ) -> schemas.TableDetails:
        """Return goe://schemas/{schema_name}/tables templated resource."""
        cache_key = f"schemas:{schema_name.upper()}:tables"
        raw_tables = await listener_cache.get_or_load(
            cache_key,
            lambda: async_(system_service.get_schema_tables)(schema_name),
        )
        typed_results = [schemas.TableDetail.from_item(item) for item in (raw_tables or [])]
        return schemas.TableDetails(count=len(typed_results), results=typed_results)

    @get(
        "/schemas/{schema_name:str}/{table_name:str}/columns/",
        mcp_resource="table_columns",
        mcp_resource_template="goe://schemas/{schema_name}/{table_name}/columns",
        mcp_resource_description="Column definitions, precision, scale, and nullability for a table.",
        mcp_resource_mime_type="application/json",
    )
    async def read_table_columns(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.ColumnDetails:
        """Return goe://schemas/{schema_name}/{table_name}/columns templated resource."""
        cache_key = f"tables:{schema_name.upper()}:{table_name.upper()}:columns"
        raw_columns = await listener_cache.get_or_load(
            cache_key,
            lambda: async_(system_service.get_table_columns)(schema_name, table_name),
        )
        typed_results = [schemas.ColumnDetail.from_item(item) for item in (raw_columns or [])]
        return schemas.ColumnDetails(count=len(typed_results), results=typed_results)

    @get(
        "/schemas/{schema_name:str}/{table_name:str}/partitions/",
        mcp_resource="table_partitions",
        mcp_resource_template="goe://schemas/{schema_name}/{table_name}/partitions",
        mcp_resource_description="Partitions and nested subpartitions for a frontend table.",
        mcp_resource_mime_type="application/json",
    )
    async def read_table_partitions(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.PartitionDetails:
        """Return goe://schemas/{schema_name}/{table_name}/partitions templated resource."""
        cache_key = f"tables:{schema_name.upper()}:{table_name.upper()}:partitions"

        async def _load_partitions() -> list[schemas.PartitionDetail]:
            partitions = await async_(system_service.get_table_partitions)(schema_name, table_name)
            subpartitions = await async_(system_service.get_table_subpartitions)(schema_name, table_name)
            grouped: dict[str, list[schemas.SubPartitionSummary]] = {}
            for raw_sub in subpartitions or []:
                summary = schemas.SubPartitionSummary.from_item(raw_sub)
                key = summary.partition_name or ""
                grouped.setdefault(key, []).append(summary)
            results: list[schemas.PartitionDetail] = []
            for raw_part in partitions or []:
                base = schemas.PartitionDetail.from_item(raw_part)
                sub_list = grouped.get(base.partition_name, base.subpartitions)
                results.append(schemas.PartitionDetail.from_item(raw_part, subpartitions=sub_list))
            return results

        typed_partitions = await listener_cache.get_or_load(cache_key, _load_partitions)
        return schemas.PartitionDetails(count=len(typed_partitions), results=typed_partitions)

    @get(
        "/schemas/{schema_name:str}/{table_name:str}/status/",
        mcp_resource="table_status",
        mcp_resource_template="goe://schemas/{schema_name}/{table_name}/status",
        mcp_resource_description="Offload status report for a single frontend table.",
        mcp_resource_mime_type="application/json",
    )
    async def read_table_status(
        self,
        system_service: NamedDependency[SystemService],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> TableStatusReport:
        """Return goe://schemas/{schema_name}/{table_name}/status templated resource."""
        return await async_(system_service.get_table_offload_status)(schema_name, table_name)

    @get(
        "/schemas/{schema_name:str}/{table_name:str}/drift/",
        mcp_resource="table_drift",
        mcp_resource_template="goe://schemas/{schema_name}/{table_name}/drift",
        mcp_resource_description="Schema drift comparison between frontend and backend table columns.",
        mcp_resource_mime_type="application/json",
    )
    async def read_table_drift(
        self,
        system_service: NamedDependency[SystemService],
        confirmation_gate: NamedDependency[ConfirmationGate],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> SchemaDiff:
        """Return goe://schemas/{schema_name}/{table_name}/drift templated resource."""
        return await async_(system_service.preview_schema_drift)(
            schema_name,
            table_name,
            confirmation_gate=confirmation_gate,
        )

    @get(
        "/schemas/{schema_name:str}/{table_name:str}/metadata/",
        mcp_resource="table_metadata",
        mcp_resource_template="goe://schemas/{schema_name}/{table_name}/metadata",
        mcp_resource_description="Persisted GOE repository offload metadata for a hybrid table.",
        mcp_resource_mime_type="application/json",
    )
    async def read_table_metadata(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.TableOffloadMetadataResponse:
        """Return goe://schemas/{schema_name}/{table_name}/metadata templated resource."""
        cache_key = f"tables:{schema_name.upper()}:{table_name.upper()}:metadata"
        metadata = await listener_cache.get_or_load(
            cache_key,
            lambda: async_(system_service.get_table_offload_metadata)(schema_name, table_name),
        )
        if metadata is None:
            raise TableMetadataNotFound(schema_name, table_name)
        return schemas.TableOffloadMetadataResponse.from_metadata(metadata)

    @get(
        "/executions/",
        mcp_resource_uri="goe://executions",
    )
    @mcp_resource(
        "command_executions",
        description="Recent GOE command executions recorded in the repository.",
        mime_type="application/json",
    )
    async def read_executions(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
    ) -> schemas.CommandExecutions:
        """Return goe://executions list resource."""
        executions = await listener_cache.get_or_load(
            "executions:list:steps=0",
            lambda: async_(system_service.get_command_executions)(),
        )
        typed_results = [schemas.CommandExecution.from_item(item) for item in (executions or [])]
        return schemas.CommandExecutions(count=len(typed_results), results=typed_results)

    @get(
        "/executions/{execution_id:str}/",
        mcp_resource="command_execution",
        mcp_resource_template="goe://executions/{execution_id}",
        mcp_resource_description="Command execution detail and step records by execution_id.",
        mcp_resource_mime_type="application/json",
    )
    async def read_execution(
        self,
        system_service: NamedDependency[SystemService],
        execution_id: FromPath[str],
    ) -> schemas.CommandExecution:
        """Return goe://executions/{execution_id} templated resource."""
        execution_identifier = _parse_resource_execution_id(execution_id)
        execution = await async_(system_service.get_command_execution)(execution_identifier)
        if not execution:
            raise exceptions.CommandExecutionNotFound(execution_id)
        return schemas.CommandExecution.from_item(execution)

    @get(
        "/executions/{execution_id:str}/log/",
        mcp_resource="command_execution_log",
        mcp_resource_template="goe://executions/{execution_id}/log",
        mcp_resource_description="Bounded command execution log tail by execution_id.",
        mcp_resource_mime_type="application/json",
    )
    async def read_execution_log(
        self,
        system_service: NamedDependency[SystemService],
        execution_id: FromPath[str],
    ) -> schemas.CommandExecutionLog:
        """Return goe://executions/{execution_id}/log templated resource."""
        execution_identifier = _parse_resource_execution_id(execution_id)
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

    @get(
        "/jobs/",
        mcp_resource_uri="goe://jobs",
    )
    @mcp_resource(
        "offload_jobs",
        description="Durable GOE Listener background offload jobs.",
        mime_type="application/json",
    )
    async def read_jobs(
        self,
        job_store: NamedDependency[JobStoreProtocol],
    ) -> schemas.JobListResponse:
        """Return goe://jobs list resource."""
        records = await asyncio.to_thread(job_store.list_jobs, limit=100, status=None)
        results = [schemas.JobStatusResponse.from_record(rec) for rec in records]
        return schemas.JobListResponse(count=len(results), results=results)

    @get(
        "/jobs/{execution_id:str}/",
        mcp_resource="offload_job",
        mcp_resource_template="goe://jobs/{execution_id}",
        mcp_resource_description="Durable background job record by execution_id.",
        mcp_resource_mime_type="application/json",
    )
    async def read_job(
        self,
        job_store: NamedDependency[JobStoreProtocol],
        execution_id: FromPath[str],
    ) -> schemas.JobStatusResponse:
        """Return goe://jobs/{execution_id} templated resource."""
        execution_identifier = _parse_resource_execution_id(execution_id)
        record = await asyncio.to_thread(job_store.get_job_by_execution_id, execution_identifier.as_str())
        if record is None:
            raise exceptions.CommandExecutionNotFound(execution_id)
        return schemas.JobStatusResponse.from_record(record)


def _parse_resource_execution_id(raw_id: str) -> ExecutionId:
    """Parse raw_id into an ExecutionId or raise HTTP 400 ApplicationError on invalid UUID syntax."""
    try:
        return ExecutionId.from_str(raw_id)
    except (ValueError, TypeError, AssertionError) as exc:
        raise exceptions.ApplicationError(
            status_code=400,
            message=f"Invalid execution_id UUID: {raw_id}",
        ) from exc
