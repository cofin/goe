# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the GOE Listener ASGI entrypoint and environment initialization."""

from unittest.mock import MagicMock

from litestar import Litestar
from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.asgi import app, create_app
from goe.listener.services.system import SystemService
from goe.persistence.schemas import SubPartitionDetail


def test_asgi_app_instance() -> None:
    """Verify that goe.listener.asgi exports a valid Litestar app instance and factory."""
    assert isinstance(app, Litestar)
    custom_app = create_app()
    assert isinstance(custom_app, Litestar)


def test_asgi_app_status_route() -> None:
    """Verify that the exported ASGI app responds to the health check endpoint."""
    with TestClient(app=app) as client:
        response = client.get("/api/system/status/")
        assert response.status_code == 200
        assert response.json()["status"] == "OK"


def test_get_table_partitions_with_subpartition_detail_structs() -> None:
    """Verify GET /api/system/schemas/{schema}/{table}/partitions/ handles SubPartitionDetail structs."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_table_partitions.return_value = [
        {"partition_name": "P_2025", "partition_position": 1, "high_value": "2025-12-31"}
    ]

    class DummyOrmSubpart:
        partition_name = "P_2025"
        partition_position = 1
        subpartition_name = "SP_2025_Q1"
        subpartition_position = 1
        high_value = "2025-03-31"

    mock_service.get_table_subpartitions.return_value = [SubPartitionDetail.from_orm(DummyOrmSubpart())]

    custom_app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})
    with TestClient(app=custom_app) as client:
        response = client.get("/api/system/schemas/SH/SALES/partitions/")
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        assert payload["results"][0]["partition_name"] == "P_2025"
        assert len(payload["results"][0]["subpartitions"]) == 1
        assert payload["results"][0]["subpartitions"][0]["subpartition_name"] == "SP_2025_Q1"
