# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OrchestrationController endpoints and console-key security."""

from unittest.mock import MagicMock, patch
from uuid import UUID

from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.config import settings
from goe.listener.services.system import SystemService
from goe.orchestration.orchestration_lock import OrchestrationLockTimeout


def test_orchestration_executions() -> None:
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

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/orchestration/executions/?include_steps=true")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["execution_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["results"][0]["steps"][0]["execution_id"] == "00000000-0000-0000-0000-000000000001"


def test_orchestration_execution_by_id() -> None:
    """Verify /api/orchestration/executions/{id}/ returns a single execution."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = {
        "execution_id": UUID("00000000-0000-0000-0000-000000000001").bytes,
        "command_type_code": "OFFLOAD",
        "status": "SUCCESS",
    }

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000001/")
        assert response.status_code == 200
        data = response.json()
        assert data["execution_id"] == "00000000-0000-0000-0000-000000000001"


def test_orchestration_execution_not_found() -> None:
    """Verify /api/orchestration/executions/{id}/ returns 404 when missing."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = None

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000002/")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


def test_orchestration_execution_log_null_or_empty_path() -> None:
    """Verify /api/orchestration/executions/{id}/execution-log/ handles None or empty command_log_path."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_execution.return_value = {
        "execution_id": "00000000-0000-0000-0000-000000000001",
        "command_log_path": None,
    }

    app = create_app(dependencies={"system_service": Provide(lambda: mock_service, sync_to_thread=False)})

    with TestClient(app=app) as client:
        response = client.get("/api/orchestration/executions/00000000-0000-0000-0000-000000000001/execution-log/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == ""
        assert "not found" in data["message"].lower()


@patch("goe.listener.utils.orchestrate.check_for_running_command")
@patch("goe.listener.services.orchestrate.orchestration_runner.offload")
def test_orchestration_post_offload(mock_offload: MagicMock, mock_check: MagicMock) -> None:
    """Verify POST /api/orchestration/offload/ dispatches an offload job."""
    app = create_app()
    with TestClient(app=app) as client:
        response = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert response.status_code in (200, 201)
        data = response.json()
        assert "execution_id" in data


@patch("goe.listener.utils.orchestrate.orchestration_lock_for_table")
def test_orchestration_post_offload_lock_timeout_and_invalid_table(mock_lock_factory: MagicMock) -> None:
    """Verify check_for_running_command raises ApplicationError on lock timeout and malformed owner_table."""
    mock_lock = MagicMock()
    mock_lock.acquire.side_effect = OrchestrationLockTimeout("locked")
    mock_lock_factory.return_value = mock_lock

    app = create_app()
    with TestClient(app=app) as client:
        locked_resp = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert locked_resp.status_code == 500
        assert "Another job has locked the table SH.SALES" in locked_resp.json()["detail"]

        invalid_resp = client.post("/api/orchestration/offload/", json={"owner_table": "MALFORMED", "execute": True})
        assert invalid_resp.status_code == 500
        assert "Could not determine owner and table" in invalid_resp.json()["detail"]


@patch("goe.listener.utils.orchestrate.check_for_running_command")
@patch("goe.listener.services.orchestrate.orchestration_runner.offload")
def test_orchestration_console_key_enforcement(mock_offload: MagicMock, mock_check: MagicMock) -> None:
    """Verify POST /api/orchestration/offload/ enforces x-goe-console-key when shared_token is set."""
    app = create_app()
    with patch.object(settings, "shared_token", "orch-secret-key"), TestClient(app=app) as client:
        unauth = client.post("/api/orchestration/offload/", json={"owner_table": "SH.SALES", "execute": True})
        assert unauth.status_code == 401

        auth = client.post(
            "/api/orchestration/offload/",
            json={"owner_table": "SH.SALES", "execute": True},
            headers={"x-goe-console-key": "orch-secret-key"},
        )
        assert auth.status_code in (200, 201)
        assert "execution_id" in auth.json()
