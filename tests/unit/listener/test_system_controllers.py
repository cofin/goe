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

from unittest.mock import MagicMock

from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.services.system import SystemService


def test_system_status():
    app = create_app()
    with TestClient(app=app) as client:
        response = client.get("/api/system/status/")
        assert response.status_code == 200
        assert response.json() == {"status": "OK"}


def test_system_config():
    mock_service = MagicMock(spec=SystemService)
    mock_service.generate_listener_endpoint_id.return_value = "00000000-0000-0000-0000-000000000001"
    mock_service.generate_listener_group_id.return_value = "00000000-0000-0000-0000-000000000002"
    mock_service.get_db_unique_name.return_value = "ORCL"
    mock_service.get_version.return_value = "1.1.1"
    mock_service.get_frontend_type.return_value = "ORACLE"
    mock_service.get_backend_type.return_value = "BIGQUERY"

    async def mock_active_endpoints():
        return []

    mock_service.get_active_listener_endpoints = mock_active_endpoints

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/system/config/")
        assert response.status_code == 200
        data = response.json()
        assert data["endpoint_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["db_unique_name"] == "ORCL"
        assert data["frontend_type"] == "ORACLE"


def test_system_schemas():
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_schemas.return_value = [
        {"schema_name": "SH", "hybrid_schema_exists": True, "table_count": 5, "schema_size_in_bytes": 1024.0}
    ]

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/system/schemas/")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["schema_name"] == "SH"
