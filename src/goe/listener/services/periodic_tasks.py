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

"""Periodic background tasks for schema synchronization and caching."""

import logging
from uuid import UUID

import anyio
import msgspec

from goe.listener import schemas, utils
from goe.listener.config import settings
from goe.listener.services.system import SystemService
from goe.orchestration.execution_id import ExecutionId
from goe.util.sync_tools import async_

system = SystemService()
group_id: UUID = system.generate_listener_group_id()
endpoint_id: UUID = system.generate_listener_endpoint_id()

logger = logging.getLogger()


async def publish_heartbeat(context) -> None:
    listener_group_id: UUID = context["listener_group_id"]
    endpoint_id_val: UUID = context["endpoint_id"]
    local_ip: str = utils.system.get_ip_address()
    await utils.cache.set(
        f"goe:listener:endpoints:{listener_group_id}:{endpoint_id_val}",
        f"{'https' if settings.ssl_enabled else 'http'}://{local_ip}:{settings.port}",
        settings.heartbeat_interval * 2,
    )
    logger.debug("Published Heartbeat")


async def publish_schemas(context) -> None:
    """Publish offloadable schemas."""
    listener_group_id: UUID = context["listener_group_id"]
    offloadable_schemas = await async_(system.get_schemas)()

    payload = msgspec.json.encode(
        schemas.OffloadableSchemas(count=len(offloadable_schemas), results=offloadable_schemas)
    ).decode()
    await utils.cache.set(
        f"goe:listener:metadata:{listener_group_id}:schemas",
        payload,
        ttl=10000,
    )
    concurrency_limit = anyio.Semaphore(4)
    async with anyio.create_task_group() as tg:
        for schema in offloadable_schemas:
            schema_name = schema.get("schema_name", None)
            if schema_name:
                tg.start_soon(_publish_schema, listener_group_id, schema_name, concurrency_limit)


async def publish_schema_tables(context) -> None:
    """Publish schema tables."""
    listener_group_id: UUID = context["listener_group_id"]
    offloadable_schemas = await async_(system.get_schemas)()

    payload = msgspec.json.encode(
        schemas.OffloadableSchemas(count=len(offloadable_schemas), results=offloadable_schemas)
    ).decode()
    await utils.cache.set(
        f"goe:listener:metadata:{listener_group_id}:schemas",
        payload,
        ttl=10000,
    )


async def publish_command_executions(context) -> None:
    """Publish command execution metadata."""
    listener_group_id: UUID = context["listener_group_id"]
    command_executions = await async_(system.get_command_executions)()
    all_steps = await async_(system.get_command_execution_steps)(execution_id=None)
    steps_by_execution_id = utils.groupby(
        lambda pair: (
            ExecutionId.from_bytes(pair.get("execution_id")).as_str()
            if isinstance(pair.get("execution_id"), bytes)
            else str(pair.get("execution_id"))
        ),
        all_steps,
    )
    for command_execution in command_executions:
        exec_key = (
            ExecutionId.from_bytes(command_execution["execution_id"]).as_str()
            if isinstance(command_execution["execution_id"], bytes)
            else str(command_execution["execution_id"])
        )
        command_execution["steps"] = steps_by_execution_id.get(exec_key, [])

    payload = msgspec.json.encode(
        schemas.CommandExecutions(count=len(command_executions), results=command_executions)
    ).decode()
    await utils.cache.set(
        f"goe:listener:metadata:{listener_group_id}:command-executions",
        payload,
        ttl=10000,
    )


async def _publish_schema(
    listener_group_id: UUID,
    schema_name: str,
    concurrency_limit: anyio.Semaphore,
) -> None:
    async with concurrency_limit:
        schema_tables = await async_(system.get_schema_tables)(schema_name)
        payload = msgspec.json.encode(schemas.TableDetails(count=len(schema_tables), results=schema_tables)).decode()
        await utils.cache.set(
            f"goe:listener:metadata:{listener_group_id}:schemas:{schema_name}",
            payload,
            ttl=86400,
        )
