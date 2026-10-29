# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OrchestrationController endpoints and console-key security."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import msgspec
from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.cache import ListenerCache
from goe.listener.config import settings
from goe.listener.jobs.store import SqliteJobStore
from goe.listener.services.system import SystemService
from goe.platform.locking import OrchestrationLockTimeout


def test_orchestration_executions(tmp_path: Path) -> None:
    """Verify /api/orchestration/executions/ returns command executions and normalizes bytes execution_id."""
    mock_service = MagicMock(spec=SystemService)
    raw_uuid = UUID("00000000-0000-0000-0000-000000000001").bytes
    mock_service.get_command_executions.return_value = [
        {
            "execution_id": raw_uuid,
            "command_type_code": "OFFLOAD",
            "command_type": "offload",
            "status_code": "SUCCESS",
            "status": "SUCCESS",
        }
    ]
    mock_service.get_command_execution_steps.return_value = [
        {
            "execution_id": raw_uuid,
            "step_id": 1,
            "step_code": "VERIFY",
            "step_title": "Verify",
            "status_code": "SUCCESS",
            "status": "SUCCESS",
        }
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
        response = client.get("/api/orchestration/executions/?include_steps=true")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["execution_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["results"][0]["steps"][0]["execution_id"] == "00000000-0000-0000-0000-000000000001"


def test_orchestration_execution_by_id(tmp_path: Path) -> None:
    """Verify /api/orchestration/executions/{id}/ returns a single execution."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = {
        "execution_id": UUID("00000000-0000-0000-0000-000000000001").bytes,
        "command_type_code": "OFFLOAD",
        "status": "SUCCESS",
    }

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
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000001/")
        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == "00000000-0000-0000-0000-000000000001"


def test_orchestration_execution_not_found(tmp_path: Path) -> None:
    """Verify /api/orchestration/executions/{id}/ returns 404 when missing."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = None

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
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000002/")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


def test_orchestration_execution_log_null_or_empty_path(tmp_path: Path) -> None:
    """Verify /api/orchestration/executions/{id}/execution-log/ handles None or empty command_log_path."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = {
        "execution_id": "00000000-0000-0000-0000-000000000001",
        "command_log_path": None,
    }
    mock_service.get_dfs_client.return_value = None

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
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000001/execution-log/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == ""
        assert data["is_file"] is False
        assert "not found" in data["message"].lower()


@patch("goe.listener.utils.orchestrate.check_for_running_command")
def test_orchestration_post_offload(mock_check: MagicMock, tmp_path: Path) -> None:
    """Verify POST /api/orchestration/offload/ dispatches an offload job into JobStore."""
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
    with TestClient(app=app) as client:
        response = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert response.status_code in (200, 201)
        data = response.json()
        assert "execution_id" in data


@patch("goe.listener.utils.orchestrate.orchestration_lock_for_table")
def test_orchestration_post_offload_lock_timeout_and_invalid_table(
    mock_lock_factory: MagicMock,
    tmp_path: Path,
) -> None:
    """Verify check_for_running_command raises 409 on lock timeout and 400 on malformed owner_table."""
    mock_lock = MagicMock()
    mock_lock.acquire.side_effect = OrchestrationLockTimeout("locked")
    mock_lock_factory.return_value = mock_lock

    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
    with TestClient(app=app) as client:
        locked_resp = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert locked_resp.status_code == 409
        assert "Another job has locked the table SH.SALES" in locked_resp.json()["detail"]

        invalid_resp = client.post("/api/orchestration/offload/", json={"owner_table": "MALFORMED", "execute": True})
        assert invalid_resp.status_code == 400
        assert "Could not determine owner and table" in invalid_resp.json()["detail"]


@patch("goe.listener.utils.orchestrate.check_for_running_command")
def test_orchestration_console_key_enforcement(mock_check: MagicMock, tmp_path: Path) -> None:
    """Verify POST /api/orchestration/offload/ enforces x-goe-console-key when shared_token is set."""
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
    secured_settings = msgspec.structs.replace(settings, shared_token="orch-secret-key")
    with patch("goe.listener.security.settings", secured_settings), TestClient(app=app) as client:
        unauth = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert unauth.status_code == 401

        auth = client.post(
            "/api/orchestration/offload/",
            json={"owner_table": "SH.SALES", "execute": True},
            headers={"x-goe-console-key": "orch-secret-key"},
        )
        assert auth.status_code in (200, 201)
        assert "execution_id" in auth.json()
