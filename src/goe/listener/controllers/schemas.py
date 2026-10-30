# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Schemas controller for Litestar GOE Listener."""

from __future__ import annotations

from typing import ClassVar

from litestar import get
from litestar.di import NamedDependency
from litestar.params import FromPath
from litestar_mcp import mcp_tool
from litestar_security import AuthenticationPolicy, SecureController, required

from goe.listener import schemas
from goe.listener.cache import ListenerCache
from goe.listener.mcp import READ_ONLY_TOOL_ANNOTATIONS
from goe.listener.services.system import SystemService
from goe.util.concurrency import async_

__all__ = ("SchemasController",)


class SchemasController(SecureController):
    """Controller for /api/system/schemas endpoints."""

    path = "/api/system/schemas"
    tags = ["Schemas"]
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get("/")
    @mcp_tool(
        "get_offloadable_schemas",
        description="List database schemas eligible for GOE offload along with hybrid schema existence and sizes.",
        when_to_use="When discovering schemas available for table offloading or readiness auditing.",
        returns="OffloadableSchemas with count and per-schema OffloadableSchema details.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_offloadable_schemas(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
    ) -> schemas.OffloadableSchemas:
        """Get list of offloadable schemas backed by ListenerCache."""
        raw_schemas = await listener_cache.get_or_load(
            "schemas:all",
            lambda: async_(system_service.get_schemas)(),
        )
        typed_results = [schemas.OffloadableSchema.from_item(item) for item in (raw_schemas or [])]
        return schemas.OffloadableSchemas(count=len(typed_results), results=typed_results)

    @get("/{schema_name:str}/")
    @mcp_tool(
        "get_offloadable_tables",
        description="List tables in a frontend schema with offload status, partitioning, and byte sizes.",
        when_to_use="When inspecting candidate or already-offloaded tables within a specific schema.",
        returns="TableDetails with count and per-table TableDetail metadata.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_offloadable_tables(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
    ) -> schemas.TableDetails:
        """Get list of tables for a schema backed by ListenerCache."""
        cache_key = f"schemas:{schema_name.upper()}:tables"
        raw_tables = await listener_cache.get_or_load(
            cache_key,
            lambda: async_(system_service.get_schema_tables)(schema_name),
        )
        typed_results = [schemas.TableDetail.from_item(item) for item in (raw_tables or [])]
        return schemas.TableDetails(count=len(typed_results), results=typed_results)
