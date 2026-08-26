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
