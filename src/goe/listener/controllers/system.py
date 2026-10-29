# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""System controller for Litestar GOE Listener."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from litestar import get, head
from litestar.di import NamedDependency
from litestar.params import FromQuery
from litestar_mcp import mcp_tool
from litestar_security import AuthenticationPolicy, SecureController, public, required

from goe.connect.models import ConnectivityReport
from goe.listener import schemas
from goe.listener.cache import ListenerCache
from goe.listener.jobs.store import JobStoreProtocol
from goe.listener.mcp import READ_ONLY_TOOL_ANNOTATIONS
from goe.listener.services.system import SystemService
from goe.report.models import StatusReportEnvelope
from goe.util.concurrency import async_

__all__ = ("SystemController",)


class SystemController(SecureController):
    """Controller for /api/system status, connectivity, and configuration endpoints."""

    path = "/api/system"
    tags = ["System"]
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get("/status/", auth=public())
    async def health_check(self) -> schemas.HealthCheck:
        """Run basic application health check."""
        return schemas.HealthCheck(status="OK")

    @head("/status/", auth=public(), status_code=200)
    async def health_check_head(self) -> None:
        """Respond to HEAD /api/system/status/ health probes with an empty body."""
        return None

    @get("/connectivity/")
    @mcp_tool(
        "check_connectivity",
        description="Execute frontend, backend, and staging storage connectivity probes.",
        when_to_use="Before planning or executing an offload or schema sync to verify database and storage reachability.",
        returns="ConnectivityReport with overall ok status and per-probe latency and error details.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def check_connectivity(
        self,
        system_service: NamedDependency[SystemService],
    ) -> ConnectivityReport:
        """Run connectivity probes off the ASGI event loop and return the report."""
        return await asyncio.to_thread(system_service.check_connectivity)

    @get("/config/")
    @mcp_tool(
        "get_listener_config",
        description="Retrieve GOE Listener endpoint metadata, database unique name, and frontend/backend types.",
        when_to_use="When inspecting the active GOE environment, frontend RDBMS type, or backend target.",
        returns="ListenerConfig with endpoint_id, listener_group_id, db_unique_name, active_listeners, and types.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_configuration(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        job_store: NamedDependency[JobStoreProtocol],
    ) -> schemas.ListenerConfig:
        """Get listener configuration metadata without blocking the event loop."""
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

    @get("/reports/status/")
    @mcp_tool(
        "generate_status_report",
        description="Generate an aggregated Offload Status Report across schemas or for a specific schema/table.",
        when_to_use="When auditing offloaded row/byte volumes, reclaimable RDBMS storage, and partition coverage.",
        returns="StatusReportEnvelope containing database rollup totals and per-table TableStatusReport entries.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
        task_support="optional",
    )
    async def generate_status_report(
        self,
        system_service: NamedDependency[SystemService],
        schema_name: FromQuery[str | None] = None,
        table_name: FromQuery[str | None] = None,
        demo: FromQuery[bool] = False,
    ) -> StatusReportEnvelope:
        """Generate an Offload Status Report envelope off the event loop."""
        return await async_(system_service.get_status_report)(
            schema_name=schema_name,
            table_name=table_name,
            demo=demo,
        )
