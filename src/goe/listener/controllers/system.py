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

"""System controller for Litestar GOE Listener."""

from typing import Annotated

from litestar import Controller, get
from litestar.params import Dependency, Parameter

from goe.listener import schemas, utils
from goe.listener.services.system import SystemService
from goe.util.sync_tools import async_


class SystemController(Controller):
    """Controller for /api/system endpoints."""

    path = "/api/system"
    tags = ["System"]

    @get("/status/")
    async def health_check(self) -> schemas.HealthCheck:
        """Run basic application health check."""
        return schemas.HealthCheck(status="OK")

    @get("/config/")
    async def get_configuration(
        self, system_service: Annotated[SystemService, Dependency(skip_validation=True)]
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

    @get("/schemas/")
    async def get_offloadable_schemas(
        self, system_service: Annotated[SystemService, Dependency(skip_validation=True)]
    ) -> schemas.OffloadableSchemas:
        """Get list of offloadable schemas."""
        schemas_list = await async_(system_service.get_schemas)()
        return schemas.OffloadableSchemas(count=len(schemas_list), results=schemas_list)

    @get("/schemas/{schema_name:str}/")
    async def get_offloadable_tables(
        self,
        system_service: Annotated[SystemService, Dependency(skip_validation=True)],
        schema_name: Annotated[str, Parameter(title="Schema Name")],
    ) -> schemas.TableDetails:
        """Get list of tables for a schema."""
        tables = await async_(system_service.get_schema_tables)(schema_name)
        return schemas.TableDetails(count=len(tables), results=tables)

    @get("/schemas/{schema_name:str}/{table_name:str}/columns/")
    async def get_table_columns(
        self,
        system_service: Annotated[SystemService, Dependency(skip_validation=True)],
        schema_name: Annotated[str, Parameter(title="Schema Name")],
        table_name: Annotated[str, Parameter(title="Table Name")],
    ) -> schemas.ColumnDetails:
        """Get list of columns for a table."""
        columns = await async_(system_service.get_table_columns)(schema_name, table_name)
        return schemas.ColumnDetails(count=len(columns), results=columns)

    @get("/schemas/{schema_name:str}/{table_name:str}/partitions/")
    async def get_table_partitions(
        self,
        system_service: Annotated[SystemService, Dependency(skip_validation=True)],
        schema_name: Annotated[str, Parameter(title="Schema Name")],
        table_name: Annotated[str, Parameter(title="Table Name")],
    ) -> schemas.PartitionDetails:
        """Get list of partitions and subpartitions for a table."""
        partitions = await async_(system_service.get_table_partitions)(schema_name, table_name)
        subpartitions = await async_(system_service.get_table_subpartitions)(schema_name, table_name)
        grouped = utils.groupby(lambda p: p.get("partition_name"), subpartitions)
        for partition in partitions:
            partition["subpartitions"] = grouped.get(partition.get("partition_name"), [])
        return schemas.PartitionDetails(count=len(partitions), results=partitions)
