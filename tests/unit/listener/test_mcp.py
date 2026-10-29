# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for GOE Listener stateless MCPConfig, ConfirmationGate (MRTR + HMAC), and OTel hooks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import msgspec
from litestar.testing import TestClient
from litestar_mcp import MCPConfig, MCPInputRequiredResult
from litestar_security.authentication import AUTH_POLICY_OPT_KEY

import goe.listener.mcp as mcp_module
from goe.listener.app import create_app, get_confirmation_gate
from goe.listener.config import ListenerSettings, settings
from goe.listener.mcp import (
    CONFIRMATION_HEADER,
    DESTRUCTIVE_TOOL_ANNOTATIONS,
    IDEMPOTENT_MUTATION_ANNOTATIONS,
    READ_ONLY_TOOL_ANNOTATIONS,
    ConfirmationGate,
    build_mcp_config,
)
from goe.listener.schemas import ConfirmationChallenge, OffloadOptions
from goe.listener.telemetry import after_mcp_tool_call, before_mcp_tool_call
from goe.observability.runtime import ensure_observability

MCP_PROTOCOL_VERSION = "2026-07-28"


def test_build_mcp_config_returns_exact_mcp_config_and_annotations() -> None:
    """Verify build_mcp_config returns an exact MCPConfig with console-key auth, instructions, and annotations."""
    custom_settings = ListenerSettings(global_config=None, max_log_bytes=2_097_152)
    cfg = build_mcp_config(custom_settings)
    assert type(cfg) is MCPConfig
    assert cfg.name == "GOE Listener MCP"
    assert cfg.instructions and "offload" in cfg.instructions.lower()
    assert AUTH_POLICY_OPT_KEY in cfg.route_opt
    assert cfg.max_blob_bytes == 4_194_304
    assert cfg.before_tool_call is before_mcp_tool_call
    assert cfg.after_tool_call is after_mcp_tool_call
    assert READ_ONLY_TOOL_ANNOTATIONS["readOnlyHint"] is True
    assert DESTRUCTIVE_TOOL_ANNOTATIONS["destructiveHint"] is True
    assert IDEMPOTENT_MUTATION_ANNOTATIONS["idempotentHint"] is True
    assert not hasattr(mcp_module, "build_mcp_plugin")
    assert not hasattr(mcp_module, "ConfirmationRequiredError")
    assert not hasattr(mcp_module, "get_connectivity_report")
    assert not hasattr(mcp_module, "get_table_status_report")
    assert not hasattr(mcp_module, "list_offloaded_tables")
    assert not hasattr(mcp_module, "get_job_status")


def test_mcp_server_discover_and_tools_list_without_imperative_wrappers() -> None:
    """Verify POST /mcp server/discover and tools/list expose controller tools without duplicate imperative wrappers."""
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
            "get_offloadable_schemas",
            "get_offloadable_tables",
            "get_table_columns",
            "get_table_partitions",
            "get_table_offload_status",
            "preview_schema_drift",
            "get_command_executions",
            "get_command_execution",
            "get_command_execution_log",
            "execute_offload",
        }.issubset(tool_names)
        assert "get_connectivity_report" not in tool_names
        assert "get_table_status_report" not in tool_names
        assert "list_offloaded_tables" not in tool_names
        assert "get_job_status" not in tool_names


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


def test_confirmation_gate_ephemeral_secret_and_hmac_binding() -> None:
    """Verify ConfirmationGate uses random per-process secret when shared_token is unset and binds HMAC payloads."""
    unauthenticated_settings = ListenerSettings(global_config=None, shared_token=None, confirmation_ttl_seconds=300)
    gate = ConfirmationGate(unauthenticated_settings)
    assert len(mcp_module._EPHEMERAL_CONFIRMATION_SECRET) == 64
    assert mcp_module._EPHEMERAL_CONFIRMATION_SECRET != "goe-local-mcp-confirmation-key"
    assert isinstance(get_confirmation_gate(), ConfirmationGate)

    payload = {"owner_table": "SH.SALES", "execute": True, "reset_backend_table": False}
    challenge = gate.issue_challenge(
        tool_name="execute_offload",
        owner_table="sh.sales",
        payload=payload,
        now_epoch=1_700_000_000,
    )
    assert isinstance(challenge, ConfirmationChallenge)
    assert challenge.tool_name == "execute_offload"
    assert challenge.owner_table == "SH.SALES"
    assert challenge.expires_at_epoch == 1_700_000_300
    assert challenge.expires_in_seconds == 300
    assert challenge.instructions

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


def test_confirmation_gate_require_mcp_confirmation_mrtr_and_token_paths() -> None:
    """Verify require_mcp_confirmation bypasses non-MCP callers and enforces MRTR or signed confirmation_token."""
    gate = ConfirmationGate(secret="unit-test-hmac-secret", ttl_seconds=300)
    payload = {"owner_table": "SH.SALES", "execute": True, "reset_backend_table": False}

    assert (
        gate.require_mcp_confirmation(
            tool_name="execute_offload",
            owner_table="SH.SALES",
            payload=payload,
        )
        is None
    )

    fake_ctx_initial = SimpleNamespace(
        request=SimpleNamespace(headers={}),
        input_responses=None,
        request_state=None,
    )
    with patch("goe.listener.mcp.get_mcp_request_context", return_value=fake_ctx_initial):
        challenge_res = gate.require_mcp_confirmation(
            tool_name="execute_offload",
            owner_table="sh.sales",
            payload=payload,
            now_epoch=1_700_000_000,
        )
    assert isinstance(challenge_res, MCPInputRequiredResult)
    assert challenge_res.input_requests is not None
    assert "confirm" in challenge_res.input_requests
    assert "confirmation_token" in challenge_res.input_requests
    assert isinstance(challenge_res.request_state, str)
    issued_token = challenge_res.request_state
    assert challenge_res.input_requests["confirm"]["confirmation_challenge"]["confirmation_token"] == issued_token

    fake_ctx_mrtr = SimpleNamespace(
        request=SimpleNamespace(headers={}),
        input_responses={"confirm": True},
        request_state=challenge_res.request_state,
    )
    with patch("goe.listener.mcp.get_mcp_request_context", return_value=fake_ctx_mrtr):
        mrtr_res = gate.require_mcp_confirmation(
            tool_name="execute_offload",
            owner_table="SH.SALES",
            payload=payload,
            now_epoch=1_700_000_100,
        )
    assert mrtr_res is None

    fake_ctx_header = SimpleNamespace(
        request=SimpleNamespace(headers={CONFIRMATION_HEADER: issued_token}),
        input_responses=None,
        request_state=None,
    )
    with patch("goe.listener.mcp.get_mcp_request_context", return_value=fake_ctx_header):
        header_res = gate.require_mcp_confirmation(
            tool_name="execute_offload",
            owner_table="SH.SALES",
            payload=payload,
            now_epoch=1_700_000_100,
        )
    assert header_res is None

    with patch("goe.listener.mcp.get_mcp_request_context", return_value=fake_ctx_initial):
        rejected_res = gate.require_mcp_confirmation(
            tool_name="execute_offload",
            owner_table="SH.CUSTOMERS",
            payload={"owner_table": "SH.CUSTOMERS", "execute": True, "reset_backend_table": False},
            confirmation_token=issued_token,
            now_epoch=1_700_000_100,
        )
    assert isinstance(rejected_res, MCPInputRequiredResult)
    assert rejected_res.input_requests is not None
    assert "rejection_reason" in rejected_res.input_requests["confirm"]


def test_offload_options_strips_confirmation_token_from_params_dict() -> None:
    """Verify OffloadOptions.to_params_dict strips confirmation_token before EXPECTED_OFFLOAD_ARGS validation."""
    opts = OffloadOptions(owner_table="SH.SALES", execute=True, confirmation_token="1700000300.deadbeef")
    params = opts.to_params_dict()
    assert "confirmation_token" not in params
    assert params["owner_table"] == "SH.SALES"


def test_otel_hooks_are_purely_observational() -> None:
    """Verify before_mcp_tool_call and after_mcp_tool_call record spans cleanly without enforcing confirmation."""
    ensure_observability()
    request = SimpleNamespace(state=SimpleNamespace(), headers={})
    before_mcp_tool_call("execute_offload", {"data": {"owner_table": "SH.SALES", "execute": True}}, request)
    after_mcp_tool_call(
        "execute_offload",
        {"data": {"owner_table": "SH.SALES", "execute": True}},
        request,
        result={"status": "QUEUED"},
        exception=None,
        duration=0.01,
    )


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
