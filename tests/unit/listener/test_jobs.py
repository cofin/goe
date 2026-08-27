# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

import pytest

from goe.listener.jobs import run_offload_job, sync_schemas_job, system_heartbeat_job


@pytest.mark.anyio
@patch("goe.listener.jobs.orchestration_runner.offload")
async def test_run_offload_job(mock_offload):
    result = await run_offload_job(
        params={"owner_table": "SH.SALES", "execute": True},
        execution_id="00000000-0000-0000-0000-000000000001",
    )
    assert result["execution_id"] == "00000000-0000-0000-0000-000000000001"
    assert result["status"] == "COMPLETED"
    assert mock_offload.called


@pytest.mark.anyio
async def test_heartbeat_job():
    result = await system_heartbeat_job()
    assert result["status"] == "HEALTHY"


@pytest.mark.anyio
async def test_sync_schemas_job():
    result = await sync_schemas_job()
    assert result["status"] == "SYNCED"
