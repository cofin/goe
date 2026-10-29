# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for GOE Listener MCP authentication, ConfirmationGate, and read-only diagnostic tools."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import msgspec
import pytest
from litestar.testing import TestClient

from goe.connect.models import CheckResult, ConnectivityReport
from goe.listener.app import create_app
from goe.listener.config import settings
from goe.listener.jobs.store import SqliteJobStore
from goe.listener.mcp import (
    ConfirmationChallenge,
    ConfirmationGate,
    ConfirmationRequiredError,
    build_mcp_config,
    build_mcp_plugin,
    get_connectivity_report,
    get_job_status,
    get_table_status_report,
    list_offloaded_tables,
    preview_offload_plan,
)
from goe.listener.services.system import SystemService
from goe.report.models import TableStatusReport
from goe.typing import FrozenBaseStruct

MCP_PROTOCOL_VERSION = "2026-07-28"


def test_mcp_server_discover_and_tools_list() -> None:
    """Verify POST /mcp server/discover and tools/list expose controller and diagnostic MCP tools."""
    app = create_app(enable_background_worker=False)
    discover_headers, discover_payload = _mcp_request("server/discover", req_id=1)
    list_headers, list_payload = _mcp_request("tools/list", req_id=2)
    with TestClient(app=app) as client:
        discover_resp = client.post("/mcp", headers=discover_headers, json=discover_payload)
        assert discover_resp.status_code == 200
        data = discover_resp.json()
        assert data["result"]["supportedVersions"] == [MCP_PROTOCOL_VERSION]
        assert "tools" in data["result"]["capabilities"]

        list_resp = client.post("/mcp", headers=list_headers, json=list_payload)
        assert list_resp.status_code == 200
        tools = list_resp.json()["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        assert {
            "check_connectivity",
            "get_listener_config",
            "get_connectivity_report",
            "get_table_status_report",
            "list_offloaded_tables",
            "preview_offload_plan",
            "get_job_status",
        }.issubset(tool_names)


def test_mcp_console_key_authentication_enforcement() -> None:
    """Verify POST /mcp returns 401 when shared_token is configured and header is missing or invalid."""
    app = create_app(enable_background_worker=False)
    headers, payload = _mcp_request("tools/list", req_id=1)
    secured_settings = msgspec.structs.replace(settings, shared_token="mcp-secret-token")

    with patch("goe.listener.security.settings", secured_settings), TestClient(app=app) as client:
        unauth = client.post("/mcp", headers=headers, json=payload)
        assert unauth.status_code == 401

        wrong_headers = {**headers, "x-goe-console-key": "wrong-key"}
        wrong = client.post("/mcp", headers=wrong_headers, json=payload)
        assert wrong.status_code == 401

        valid_headers = {**headers, "x-goe-console-key": "mcp-secret-token"}
        valid = client.post("/mcp", headers=valid_headers, json=payload)
        assert valid.status_code == 200
        assert "tools" in valid.json()["result"]


def test_read_only_mcp_diagnostic_tools_do_not_mutate_state(tmp_path: Path) -> None:
    """Verify read-only MCP diagnostic tools return FrozenBaseStruct models and force execute=False."""
    mock_service = MagicMock(spec=SystemService)
    mock_service.check_connectivity.return_value = ConnectivityReport(
        environment_summary="ORACLE -> BIGQUERY",
        results=(CheckResult(name="oracle", category="frontend", status="passed", duration_ms=1.2),),
    )
    mock_service.get_table_offload_status.return_value = TableStatusReport(
        schema_name="SH",
        table_name="SALES",
        target_schema="sh",
        target_table="sales",
        offload_type="INCREMENTAL",
    )
    mock_service.get_schema_tables.return_value = [
        {"table_name": "SALES", "offload_status": "OFFLOADED", "table_size_in_bytes": 4096.0}
    ]

    conn_report = get_connectivity_report(system_service=mock_service)
    assert isinstance(conn_report, FrozenBaseStruct)
    assert conn_report.passed is True

    table_report = get_table_status_report("sh.sales", system_service=mock_service)
    assert isinstance(table_report, FrozenBaseStruct)
    assert table_report.schema_name == "SH"
    assert table_report.table_name == "SALES"

    tables_list = list_offloaded_tables("SH", system_service=mock_service)
    assert isinstance(tables_list, FrozenBaseStruct)
    assert tables_list.count == 1
    assert tables_list.results[0].table_name == "SALES"

    mock_runner = MagicMock()
    preview = preview_offload_plan(
        "sh.sales",
        options={"execute": True, "reset_backend_table": True},
        runner_factory=lambda: mock_runner,
    )
    assert isinstance(preview, FrozenBaseStruct)
    assert preview.execute is False
    assert preview.dry_run is True
    assert preview.planned_options["execute"] is False
    mock_runner.offload.assert_called_once()
    assert mock_runner.offload.call_args.args[0]["execute"] is False

    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    missing_status = get_job_status("exec-missing", job_store=store)
    assert isinstance(missing_status, FrozenBaseStruct)
    assert missing_status.found is False
    assert missing_status.status == "NOT_FOUND"

    now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    store.enqueue(
        execution_id="exec-present",
        owner_table="SH.SALES",
        payload={"owner_table": "SH.SALES", "execute": True},
        now=now,
    )
    present_status = get_job_status("exec-present", job_store=store)
    assert isinstance(present_status, FrozenBaseStruct)
    assert present_status.found is True
    assert present_status.status == "PENDING"
    assert present_status.table_key == "SH.SALES"


def test_confirmation_gate_hmac_verification_and_hook_enforcement() -> None:
    """Verify ConfirmationGate issues time-bounded HMAC tokens and blocks unconfirmed mutating MCP calls."""
    gate = ConfirmationGate(secret="unit-test-hmac-secret", ttl_seconds=300)
    payload = {"owner_table": "SH.SALES", "execute": True, "reset_backend_table": False}
    challenge = gate.issue_token(
        tool_name="execute_offload",
        owner_table="sh.sales",
        payload=payload,
        now_epoch=1_700_000_000,
    )
    assert isinstance(challenge, ConfirmationChallenge)
    assert challenge.confirmation_required is True
    assert challenge.owner_table == "SH.SALES"
    assert challenge.expires_at_epoch == 1_700_000_300

    assert (
        gate.verify_token(
            token=challenge.confirmation_token,
            tool_name="execute_offload",
            owner_table="SH.SALES",
            payload=payload,
            now_epoch=1_700_000_299,
        )
        is True
    )
    assert (
        gate.verify_token(
            token=challenge.confirmation_token,
            tool_name="execute_offload",
            owner_table="SH.SALES",
            payload=payload,
            now_epoch=1_700_000_300,
        )
        is False
    )
    assert (
        gate.verify_token(
            token=challenge.confirmation_token,
            tool_name="execute_offload",
            owner_table="SH.CUSTOMERS",
            payload=payload,
            now_epoch=1_700_000_100,
        )
        is False
    )
    assert (
        gate.verify_token(
            token=challenge.confirmation_token,
            tool_name="execute_offload",
            owner_table="SH.SALES",
            payload={**payload, "reset_backend_table": True},
            now_epoch=1_700_000_100,
        )
        is False
    )

    cfg = build_mcp_config(gate=gate)
    assert cfg.before_tool_call is not None
    request = SimpleNamespace(state=SimpleNamespace(), headers={})

    with pytest.raises(ConfirmationRequiredError) as exc_info:
        cfg.before_tool_call("execute_offload", {"data": dict(payload)}, request)
    issued = exc_info.value.challenge
    assert issued.confirmation_token

    confirmed_args = {"data": {**payload, "confirmation_token": issued.confirmation_token}}
    cfg.before_tool_call("execute_offload", confirmed_args, request)

    plugin = build_mcp_plugin(gate=gate)
    assert plugin is not None


def _mcp_request(
    method: str,
    *,
    req_id: int = 1,
    extra_params: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    params: dict[str, Any] = {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    }
    if extra_params:
        params.update(extra_params)
    headers = {
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }
    return headers, payload
