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
from goe.listener.mcp import ConfirmationGate
from goe.listener.services.system import SystemService
from goe.platform.locking import OrchestrationLockTimeout
from goe.serializers import decode_json


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


def test_orchestration_malformed_uuid_and_typed_job_inspection(tmp_path: Path) -> None:
    """Verify malformed UUID returns 400 and /jobs/ + /jobs/{execution_id}/ inspect durable jobs."""
    mock_service = MagicMock(spec=SystemService)
    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    exec_id = "00000000-0000-0000-0000-000000000010"
    store.enqueue(execution_id=exec_id, owner_table="SH.SALES", payload={"owner_table": "SH.SALES", "execute": True})

    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    with TestClient(app=app) as client:
        bad_exec = client.get("/api/orchestration/executions/not-a-uuid/")
        assert bad_exec.status_code == 400
        assert "Invalid execution_id UUID" in bad_exec.json()["detail"]

        bad_log = client.get("/api/orchestration/executions/not-a-uuid/execution-log/")
        assert bad_log.status_code == 400

        bad_link = client.get("/api/orchestration/executions/not-a-uuid/execution-log/link/")
        assert bad_link.status_code == 400

        jobs_resp = client.get("/api/orchestration/jobs/", params={"status": "PENDING", "limit": 10})
        assert jobs_resp.status_code == 200
        jobs_body = jobs_resp.json()
        assert jobs_body["count"] == 1
        assert jobs_body["results"][0]["execution_id"] == exec_id
        assert jobs_body["results"][0]["table_key"] == "SH.SALES"
        assert jobs_body["results"][0]["status"] == "PENDING"

        bad_status = client.get("/api/orchestration/jobs/", params={"status": "INVALID_STATE"})
        assert bad_status.status_code == 400

        job_detail = client.get(f"/api/orchestration/jobs/{exec_id}/")
        assert job_detail.status_code == 200
        assert job_detail.json()["execution_id"] == exec_id

        missing_job = client.get("/api/orchestration/jobs/00000000-0000-0000-0000-000000000099/")
        assert missing_job.status_code == 404


@patch("goe.listener.utils.orchestrate.check_for_running_command")
def test_mcp_orchestration_resources_log_link_and_mrtr_confirmation_gate(
    mock_check: MagicMock,
    tmp_path: Path,
) -> None:
    """Verify goe://executions* and goe://jobs* resources, get_execution_log_link, and MRTR offload gating."""
    exec_id = "00000000-0000-0000-0000-000000000011"
    mock_service = MagicMock(spec=SystemService)
    mock_service.get_command_executions.return_value = [
        {"execution_id": exec_id, "command_type_code": "OFFLOAD", "status_code": "SUCCESS", "status": "SUCCESS"}
    ]
    mock_service.get_command_execution.return_value = {
        "execution_id": exec_id,
        "command_type_code": "OFFLOAD",
        "status_code": "SUCCESS",
        "status": "SUCCESS",
        "command_log_path": None,
    }
    mock_service.get_dfs_client.return_value = None

    cache = ListenerCache()
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    store.enqueue(execution_id=exec_id, owner_table="SH.PROMOTIONS", payload={"owner_table": "SH.PROMOTIONS"})
    gate = ConfirmationGate(secret="test-orch-secret", ttl_seconds=300)

    app = create_app(
        dependencies={
            "system_service": Provide(lambda: mock_service, sync_to_thread=False),
            "listener_cache": Provide(lambda: cache, sync_to_thread=False),
            "job_store": Provide(lambda: store, sync_to_thread=False),
            "confirmation_gate": Provide(lambda: gate, sync_to_thread=False),
        },
        enable_background_worker=False,
    )

    base_meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }

    with TestClient(app=app) as client:
        openapi_resp = client.get("/schema/openapi.json")
        assert openapi_resp.status_code == 200

        res_list = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "resources/list"},
            json={"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {"_meta": base_meta}},
        )
        assert res_list.status_code == 200
        uris = {r["uri"] for r in res_list.json()["result"]["resources"]}
        assert {"goe://executions", "goe://jobs"}.issubset(uris)

        tmpl_list = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "resources/templates/list"},
            json={"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list", "params": {"_meta": base_meta}},
        )
        assert tmpl_list.status_code == 200
        tmpls = {t["uriTemplate"] for t in tmpl_list.json()["result"]["resourceTemplates"]}
        assert {
            "goe://executions/{execution_id}",
            "goe://executions/{execution_id}/log",
            "goe://jobs/{execution_id}",
        }.issubset(tmpls)

        for req_id, uri in enumerate(
            (
                "goe://executions",
                f"goe://executions/{exec_id}",
                f"goe://executions/{exec_id}/log",
                "goe://jobs",
                f"goe://jobs/{exec_id}",
            ),
            start=10,
        ):
            r_resp = client.post(
                "/mcp",
                headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "resources/read", "Mcp-Name": uri},
                json={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "resources/read",
                    "params": {"uri": uri, "_meta": base_meta},
                },
            )
            assert r_resp.status_code == 200
            text_body = r_resp.json()["result"]["contents"][0]["text"]
            assert isinstance(decode_json(text_body), dict)

        link_call = client.post(
            "/mcp",
            headers={
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "get_execution_log_link",
            },
            json={
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {
                    "name": "get_execution_log_link",
                    "arguments": {"execution_id": exec_id},
                    "_meta": base_meta,
                },
            },
        )
        assert link_call.status_code == 200
        link_block = link_call.json()["result"]["content"][0]
        assert link_block["type"] == "resource_link"
        assert link_block["uri"] == f"goe://executions/{exec_id}/log"

        round1_call = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "execute_offload"},
            json={
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tools/call",
                "params": {
                    "name": "execute_offload",
                    "arguments": {"data": {"owner_table": "SH.SALES", "execute": True}},
                    "_meta": base_meta,
                },
            },
        )
        assert round1_call.status_code == 200
        r1_result = round1_call.json()["result"]
        assert r1_result["resultType"] == "input_required"
        assert "confirm" in r1_result["inputRequests"]
        assert store.get_active_job_for_table("SH.SALES") is None

        round2_call = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "execute_offload"},
            json={
                "jsonrpc": "2.0",
                "id": 22,
                "method": "tools/call",
                "params": {
                    "name": "execute_offload",
                    "arguments": {"data": {"owner_table": "SH.SALES", "execute": True}},
                    "requestState": r1_result["requestState"],
                    "inputResponses": {"confirm": True},
                    "_meta": base_meta,
                },
            },
        )
        assert round2_call.status_code == 200
        r2_result = round2_call.json()["result"]
        assert r2_result["isError"] is False
        scheduled_id = r2_result["structuredContent"]["execution_id"]
        assert store.get_job_by_execution_id(scheduled_id) is not None
        content_uris = {b.get("uri") for b in r2_result["content"] if b.get("type") == "resource_link"}
        assert f"goe://jobs/{scheduled_id}" in content_uris
        assert f"goe://executions/{scheduled_id}/log" in content_uris

        dry_run_call = client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "execute_offload"},
            json={
                "jsonrpc": "2.0",
                "id": 23,
                "method": "tools/call",
                "params": {
                    "name": "execute_offload",
                    "arguments": {"data": {"owner_table": "SH.COSTS", "execute": False}},
                    "_meta": base_meta,
                },
            },
        )
        assert dry_run_call.status_code == 200
        assert dry_run_call.json()["result"]["resultType"] == "complete"
        assert store.get_active_job_for_table("SH.COSTS") is not None
