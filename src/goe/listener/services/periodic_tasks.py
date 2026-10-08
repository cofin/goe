# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Periodic background tasks for schema synchronization and caching."""

import logging
from typing import Any
from uuid import UUID

import anyio
import msgspec

from goe.listener import schemas, utils
from goe.listener.config import settings
from goe.listener.services.system import SystemService, get_system_service
from goe.orchestration.execution_id import ExecutionId
from goe.util.sync_tools import async_

logger = logging.getLogger(__name__)


def _resolve_context(
    context: dict[str, Any] | None = None,
    system_service: SystemService | None = None,
) -> tuple[SystemService, UUID, UUID]:
    """Resolve the active SystemService and listener group/endpoint identifiers."""
    service = system_service or get_system_service()
    ctx = context or {}
    listener_group_id: UUID = ctx.get("listener_group_id") or service.generate_listener_group_id()
    endpoint_id_val: UUID = ctx.get("endpoint_id") or service.generate_listener_endpoint_id()
    return service, listener_group_id, endpoint_id_val


async def publish_heartbeat(
    context: dict[str, Any] | None = None,
    system_service: SystemService | None = None,
) -> None:
    """Publish active listener endpoint heartbeat to the in-process cache."""
    _, listener_group_id, endpoint_id_val = _resolve_context(context, system_service)
    local_ip: str = utils.system.get_ip_address()
    await utils.cache.set(
        f"goe:listener:endpoints:{listener_group_id}:{endpoint_id_val}",
        f"{'https' if settings.ssl_enabled else 'http'}://{local_ip}:{settings.port}",
        settings.heartbeat_interval * 2,
    )
    logger.debug("Published Heartbeat")


async def publish_schemas(
    context: dict[str, Any] | None = None,
    system_service: SystemService | None = None,
) -> None:
    """Publish offloadable schemas and per-schema table metadata to the cache."""
    service, listener_group_id, _ = _resolve_context(context, system_service)
    if service.config is None:
        return
    offloadable_schemas = await async_(service.get_schemas)()

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
                tg.start_soon(_publish_schema, service, listener_group_id, schema_name, concurrency_limit)


async def publish_schema_tables(
    context: dict[str, Any] | None = None,
    system_service: SystemService | None = None,
) -> None:
    """Publish offloadable schema list to the cache."""
    service, listener_group_id, _ = _resolve_context(context, system_service)
    if service.config is None:
        return
    offloadable_schemas = await async_(service.get_schemas)()

    payload = msgspec.json.encode(
        schemas.OffloadableSchemas(count=len(offloadable_schemas), results=offloadable_schemas)
    ).decode()
    await utils.cache.set(
        f"goe:listener:metadata:{listener_group_id}:schemas",
        payload,
        ttl=10000,
    )


async def publish_command_executions(
    context: dict[str, Any] | None = None,
    system_service: SystemService | None = None,
) -> None:
    """Publish command execution metadata to the cache."""
    service, listener_group_id, _ = _resolve_context(context, system_service)
    if service.config is None:
        return
    command_executions = await async_(service.get_command_executions)()
    all_steps = await async_(service.get_command_execution_steps)(execution_id=None)
    for step in all_steps:
        if isinstance(step.get("execution_id"), bytes):
            step["execution_id"] = ExecutionId.from_bytes(step["execution_id"]).as_str()
    steps_by_execution_id = utils.groupby(
        lambda pair: str(pair.get("execution_id")),
        all_steps,
    )
    for command_execution in command_executions:
        exec_key = (
            ExecutionId.from_bytes(command_execution["execution_id"]).as_str()
            if isinstance(command_execution["execution_id"], bytes)
            else str(command_execution["execution_id"])
        )
        command_execution["execution_id"] = exec_key
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
    service: SystemService,
    listener_group_id: UUID,
    schema_name: str,
    concurrency_limit: anyio.Semaphore,
) -> None:
    async with concurrency_limit:
        schema_tables = await async_(service.get_schema_tables)(schema_name)
        payload = msgspec.json.encode(schemas.TableDetails(count=len(schema_tables), results=schema_tables)).decode()
        await utils.cache.set(
            f"goe:listener:metadata:{listener_group_id}:schemas:{schema_name}",
            payload,
            ttl=86400,
        )
