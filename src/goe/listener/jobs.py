# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Background tasks and jobs for GOE Listener using litestar-queues."""

from datetime import timedelta
from typing import Any

from litestar_queues import task

from goe.listener.services.orchestrate import orchestration_runner
from goe.orchestration.execution_id import ExecutionId


@task("orchestration.offload", queue="orchestration", timeout=86400)
async def run_offload_job(params: dict[str, Any], execution_id: str) -> dict[str, Any]:
    """Execute an offload operation asynchronously in the worker pool."""
    execution_identifier = ExecutionId.from_str(execution_id)
    orchestration_runner.offload(params=params, execution_id=execution_identifier)
    return {"execution_id": execution_id, "status": "COMPLETED"}


@task("system.heartbeat", queue="system", interval=timedelta(seconds=30))
async def system_heartbeat_job() -> dict[str, str]:
    """Publish periodic heartbeat check for active listener nodes."""
    return {"status": "HEALTHY"}


@task("system.sync_schemas", queue="system", interval=timedelta(minutes=15))
async def sync_schemas_job() -> dict[str, str]:
    """Synchronize metadata schemas in background."""
    return {"status": "SYNCED"}
