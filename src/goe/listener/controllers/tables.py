# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Tables controller for Litestar GOE Listener."""

from __future__ import annotations

from typing import ClassVar

from litestar import get
from litestar.di import NamedDependency
from litestar.params import FromPath
from litestar_mcp import mcp_tool
from litestar_security import AuthenticationPolicy, SecureController, required

from goe.listener import schemas
from goe.listener.cache import ListenerCache
from goe.listener.exceptions import TableMetadataNotFound
from goe.listener.mcp import READ_ONLY_TOOL_ANNOTATIONS
from goe.listener.services.system import SystemService
from goe.report.models import TableStatusReport
from goe.sync.differ import SchemaDiff
from goe.util.concurrency import async_

__all__ = ("TablesController",)


class TablesController(SecureController):
    """Controller for /api/system/schemas/{schema_name}/{table_name} endpoints."""

    path = "/api/system/schemas/{schema_name:str}/{table_name:str}"
    tags = ["Tables"]
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get("/columns/")
    @mcp_tool(
        "get_table_columns",
        description="Retrieve frontend column names, data types, precision, scale, and nullability for a table.",
        when_to_use="When inspecting column types, partition keys, or decimal/timestamp conversion candidates.",
        returns="ColumnDetails containing count and ordered ColumnDetail entries.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_table_columns(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.ColumnDetails:
        """Get list of columns for a table backed by ListenerCache."""
        cache_key = f"tables:{schema_name.upper()}:{table_name.upper()}:columns"
        raw_columns = await listener_cache.get_or_load(
            cache_key,
            lambda: async_(system_service.get_table_columns)(schema_name, table_name),
        )
        typed_results = [schemas.ColumnDetail.from_item(item) for item in (raw_columns or [])]
        return schemas.ColumnDetails(count=len(typed_results), results=typed_results)

    @get("/partitions/")
    @mcp_tool(
        "get_table_partitions",
        description="Retrieve frontend partitions and nested subpartitions with high-water-mark values and sizes.",
        when_to_use="When selecting partition boundaries (--less-than-value, --partition-names-csv) for offload.",
        returns="PartitionDetails containing count and PartitionDetail entries with nested subpartitions.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_table_partitions(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.PartitionDetails:
        """Get list of partitions and subpartitions for a table backed by ListenerCache."""
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

    @get("/status/")
    @mcp_tool(
        "get_table_offload_status",
        description="Retrieve the offload status report for a single frontend table.",
        when_to_use="When checking offloaded vs retained row/byte counts and high-water marks for one table.",
        returns="TableStatusReport with source, offloaded, and reclaimable metrics.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_table_offload_status(
        self,
        system_service: NamedDependency[SystemService],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> TableStatusReport:
        """Return offload status report for a single table."""
        return await async_(system_service.get_table_offload_status)(schema_name, table_name)

    @get("/drift/")
    @mcp_tool(
        "preview_schema_drift",
        description="Compare frontend and backend table columns to detect added, dropped, or widened columns.",
        when_to_use="Before running apply_schema_sync or after RDBMS DDL changes on an offloaded table.",
        returns="SchemaDiff with added/dropped/widened columns and generated evolution DDL.",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def preview_schema_drift(
        self,
        system_service: NamedDependency[SystemService],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> SchemaDiff:
        """Preview schema drift between source and target for a single table."""
        return await async_(system_service.preview_schema_drift)(schema_name, table_name)

    @get("/metadata/")
    @mcp_tool(
        "get_table_offload_metadata",
        description="Retrieve persisted GOE repository offload metadata (HWM, offload_type, backend target) for a table.",
        when_to_use="When checking whether a table is offloaded and inspecting its high-water mark or predicate.",
        returns="TableOffloadMetadataResponse (or 404 when the table has not been offloaded).",
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )
    async def get_table_offload_metadata(
        self,
        system_service: NamedDependency[SystemService],
        listener_cache: NamedDependency[ListenerCache],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.TableOffloadMetadataResponse:
        """Return persisted repository offload metadata for a table or raise 404 when not offloaded."""
        cache_key = f"tables:{schema_name.upper()}:{table_name.upper()}:metadata"
        metadata = await listener_cache.get_or_load(
            cache_key,
            lambda: async_(system_service.get_table_offload_metadata)(schema_name, table_name),
        )
        if metadata is None:
            raise TableMetadataNotFound(schema_name, table_name)
        return schemas.TableOffloadMetadataResponse.from_metadata(metadata)
