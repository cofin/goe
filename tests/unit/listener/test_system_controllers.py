# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SystemController endpoints and console-key authentication."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec
from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.cache import ListenerCache
from goe.listener.config import settings
from goe.listener.jobs.store import SqliteJobStore
from goe.listener.services.system import SystemService


def test_system_status(tmp_path: Path) -> None:
    """Verify /api/system/status/ returns 200 OK."""
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
    with TestClient(app=app) as client:
        response = client.get("/api/system/status/")
        assert response.status_code == 200
        assert response.json() == {"status": "OK"}


def test_system_config(tmp_path: Path) -> None:
    """Verify /api/system/config/ returns listener and database metadata."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.generate_listener_endpoint_id.return_value = "00000000-0000-0000-0000-000000000001"
    mock_service.generate_listener_group_id.return_value = "00000000-0000-0000-0000-000000000002"
    mock_service.get_db_unique_name.return_value = "ORCL"
    mock_service.get_version.return_value = "1.1.1"
    mock_service.get_frontend_type.return_value = "ORACLE"
    mock_service.get_backend_type.return_value = "BIGQUERY"

    async def mock_active_endpoints() -> list:
        return []

    mock_service.get_active_listener_endpoints = mock_active_endpoints

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with TestClient(app=app) as client:
        response = client.get("/api/system/config/")
        assert response.status_code == 200
        data = response.json()
        assert data["endpoint_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["db_unique_name"] == "ORCL"
        assert data["frontend_type"] == "ORACLE"


def test_system_schemas(tmp_path: Path) -> None:
    """Verify /api/system/schemas/ returns offloadable schemas."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_schemas.return_value = [
        {"schema_name": "SH", "hybrid_schema_exists": True, "table_count": 5, "schema_size_in_bytes": 1024.0}
    ]

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with TestClient(app=app) as client:
        response = client.get("/api/system/schemas/")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["schema_name"] == "SH"


def test_system_console_key_enforcement(tmp_path: Path) -> None:
    """Verify x-goe-console-key header enforcement when settings.shared_token is configured."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_schemas.return_value = [
        {"schema_name": "SH", "hybrid_schema_exists": True, "table_count": 5, "schema_size_in_bytes": 1024.0}
    ]

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    secured_settings = msgspec.structs.replace(settings, shared_token="secret-token-123")
    with patch("goe.listener.security.settings", secured_settings), TestClient(app=app) as client:
        status_resp = client.get("/api/system/status/")
        assert status_resp.status_code == 200

        unauth_resp = client.get("/api/system/schemas/")
        assert unauth_resp.status_code == 401

        invalid_resp = client.get("/api/system/schemas/", headers={"x-goe-console-key": "wrong-token"})
        assert invalid_resp.status_code == 401

        valid_resp = client.get("/api/system/schemas/", headers={"x-goe-console-key": "secret-token-123"})
        assert valid_resp.status_code == 200
        assert valid_resp.json()["count"] == 1
