# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for litestar-queues background tasks and periodic cache publishers."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from goe.listener import utils
from goe.listener.jobs import (
    run_offload_job,
    sync_command_executions_job,
    sync_schemas_job,
    system_heartbeat_job,
)
from goe.listener.services.periodic_tasks import (
    publish_command_executions,
    publish_heartbeat,
    publish_schemas,
)
from goe.listener.services.system import SystemService


@pytest.mark.anyio
@patch("goe.listener.jobs.orchestration_runner.offload")
async def test_run_offload_job(mock_offload: MagicMock) -> None:
    """Verify run_offload_job executes orchestration_runner.offload in a worker thread."""
    result = await run_offload_job(
        params={"owner_table": "SH.SALES", "execute": True},
        execution_id="00000000-0000-0000-0000-000000000001",
    )
    assert result["execution_id"] == "00000000-0000-0000-0000-000000000001"
    assert result["status"] == "COMPLETED"
    assert mock_offload.called


@pytest.mark.anyio
async def test_heartbeat_job_populates_cache() -> None:
    """Verify publish_heartbeat and system_heartbeat_job store endpoint metadata in MemoryCache."""
    await utils.cache.clear()
    mock_service = MagicMock(spec=SystemService)
    group_id = UUID("00000000-0000-0000-0000-000000000010")
    endpoint_id = UUID("00000000-0000-0000-0000-000000000020")
    mock_service.generate_listener_group_id.return_value = group_id
    mock_service.generate_listener_endpoint_id.return_value = endpoint_id

    await publish_heartbeat(
        context={"listener_group_id": group_id, "endpoint_id": endpoint_id},
        system_service=mock_service,
    )
    cached = await utils.cache.get(f"goe:listener:endpoints:{group_id}:{endpoint_id}")
    assert cached is not None
    assert "http" in cached

    with patch("goe.listener.jobs.periodic_tasks.publish_heartbeat") as mock_pub:
        result = await system_heartbeat_job()
        assert result["status"] == "HEALTHY"
        assert mock_pub.called


@pytest.mark.anyio
async def test_sync_schemas_job_populates_cache() -> None:
    """Verify publish_schemas and sync_schemas_job store schemas in MemoryCache."""
    await utils.cache.clear()
    mock_service = MagicMock(spec=SystemService)
    mock_service.config = MagicMock()
    group_id = UUID("00000000-0000-0000-0000-000000000010")
    endpoint_id = UUID("00000000-0000-0000-0000-000000000020")
    mock_service.get_schemas.return_value = [
        {"schema_name": "SH", "hybrid_schema_exists": True, "table_count": 3, "schema_size_in_bytes": 512.0}
    ]
    mock_service.get_schema_tables.return_value = []

    await publish_schemas(
        context={"listener_group_id": group_id, "endpoint_id": endpoint_id},
        system_service=mock_service,
    )
    cached = await utils.cache.get(f"goe:listener:metadata:{group_id}:schemas")
    assert cached is not None

    with patch("goe.listener.jobs.periodic_tasks.publish_schemas") as mock_pub:
        result = await sync_schemas_job()
        assert result["status"] == "SYNCED"
        assert mock_pub.called


@pytest.mark.anyio
async def test_sync_command_executions_job_populates_cache() -> None:
    """Verify publish_command_executions and sync_command_executions_job store executions in MemoryCache."""
    await utils.cache.clear()
    mock_service = MagicMock(spec=SystemService)
    mock_service.config = MagicMock()
    group_id = UUID("00000000-0000-0000-0000-000000000010")
    endpoint_id = UUID("00000000-0000-0000-0000-000000000020")
    mock_service.get_command_executions.return_value = [
        {
            "execution_id": "00000000-0000-0000-0000-000000000001",
            "command_type_code": "OFFLOAD",
            "command_type": "offload",
            "status_code": "SUCCESS",
            "status": "SUCCESS",
        }
    ]
    mock_service.get_command_execution_steps.return_value = []

    await publish_command_executions(
        context={"listener_group_id": group_id, "endpoint_id": endpoint_id},
        system_service=mock_service,
    )
    cached = await utils.cache.get(f"goe:listener:metadata:{group_id}:command-executions")
    assert cached is not None

    with patch("goe.listener.jobs.periodic_tasks.publish_command_executions") as mock_pub:
        result = await sync_command_executions_job()
        assert result["status"] == "SYNCED"
        assert mock_pub.called
