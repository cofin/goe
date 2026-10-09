# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""System controller for Litestar GOE Listener."""

from typing import ClassVar

from litestar import get
from litestar.di import NamedDependency
from litestar.params import FromPath
from litestar_security import AuthenticationPolicy, SecureController, public, required

from goe.listener import schemas, utils
from goe.listener.services.system import SystemService
from goe.util.sync_tools import async_


class SystemController(SecureController):
    """Controller for /api/system endpoints."""

    path = "/api/system"
    tags: ClassVar[list[str]] = ["System"]
    auth: ClassVar[AuthenticationPolicy] = required("console-key")

    @get("/status/", auth=public())
    async def health_check(self) -> schemas.HealthCheck:
        """Run basic application health check."""
        return schemas.HealthCheck(status="OK")

    @get("/config/", mcp_tool="get_listener_config")
    async def get_configuration(
        self,
        system_service: NamedDependency[SystemService],
    ) -> schemas.ListenerConfig:
        """Get listener configuration metadata."""
        active_listeners = await system_service.get_active_listener_endpoints()
        return schemas.ListenerConfig(
            endpoint_id=str(system_service.generate_listener_endpoint_id()),
            listener_group_id=str(system_service.generate_listener_group_id()),
            db_unique_name=system_service.get_db_unique_name(),
            active_listeners=active_listeners or [],
            version=system_service.get_version(),
            frontend_type=system_service.get_frontend_type(),
            backend_type=system_service.get_backend_type(),
        )

    @get("/schemas/", mcp_tool="get_offloadable_schemas")
    async def get_offloadable_schemas(
        self,
        system_service: NamedDependency[SystemService],
    ) -> schemas.OffloadableSchemas:
        """Get list of offloadable schemas."""
        schemas_list = await async_(system_service.get_schemas)()
        return schemas.OffloadableSchemas(count=len(schemas_list), results=schemas_list)

    @get("/schemas/{schema_name:str}/", mcp_tool="get_offloadable_tables")
    async def get_offloadable_tables(
        self,
        system_service: NamedDependency[SystemService],
        schema_name: FromPath[str],
    ) -> schemas.TableDetails:
        """Get list of tables for a schema."""
        tables = await async_(system_service.get_schema_tables)(schema_name)
        return schemas.TableDetails(count=len(tables), results=tables)

    @get("/schemas/{schema_name:str}/{table_name:str}/columns/", mcp_tool="get_table_columns")
    async def get_table_columns(
        self,
        system_service: NamedDependency[SystemService],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.ColumnDetails:
        """Get list of columns for a table."""
        columns = await async_(system_service.get_table_columns)(schema_name, table_name)
        return schemas.ColumnDetails(count=len(columns), results=columns)

    @get("/schemas/{schema_name:str}/{table_name:str}/partitions/", mcp_tool="get_table_partitions")
    async def get_table_partitions(
        self,
        system_service: NamedDependency[SystemService],
        schema_name: FromPath[str],
        table_name: FromPath[str],
    ) -> schemas.PartitionDetails:
        """Get list of partitions and subpartitions for a table."""
        partitions = await async_(system_service.get_table_partitions)(schema_name, table_name)
        subpartitions = await async_(system_service.get_table_subpartitions)(schema_name, table_name)
        normalized_subpartitions = [
            item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in (subpartitions or [])
        ]
        grouped = utils.groupby(lambda p: p.get("partition_name"), normalized_subpartitions)
        normalized_partitions = [
            partition.to_dict() if hasattr(partition, "to_dict") else dict(partition)
            for partition in (partitions or [])
        ]
        for partition in normalized_partitions:
            partition["subpartitions"] = grouped.get(partition.get("partition_name"), [])
        return schemas.PartitionDetails(count=len(normalized_partitions), results=normalized_partitions)
