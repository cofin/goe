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

from unittest.mock import MagicMock, patch

from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.services.system import SystemService


def test_orchestration_executions():
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_executions.return_value = [
        {
            "execution_id": "00000000-0000-0000-0000-000000000001",
            "command_type_code": "OFFLOAD",
            "command_type": "offload",
            "status_code": "SUCCESS",
            "status": "SUCCESS",
        }
    ]

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/orchestration/executions/")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["command_type_code"] == "OFFLOAD"


def test_orchestration_execution_by_id():
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = {
        "execution_id": "00000000-0000-0000-0000-000000000001",
        "command_type_code": "OFFLOAD",
        "status": "SUCCESS",
    }

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000001/")
        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == "00000000-0000-0000-0000-000000000001"


def test_orchestration_execution_not_found():
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = None

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000002/")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


@patch("goe.listener.utils.orchestrate.check_for_running_command")
@patch("goe.listener.services.orchestrate.orchestration_runner.offload")
def test_orchestration_post_offload(mock_offload, mock_check):
    app = create_app()
    with TestClient(app=app) as client:
        response = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert response.status_code in (200, 201)
        data = response.json()
        assert "execution_id" in data
