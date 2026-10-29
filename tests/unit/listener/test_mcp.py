# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for GOE Listener MCP endpoint and plugin configuration."""

from typing import Any

from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.mcp import build_mcp_config, build_mcp_plugin

MCP_PROTOCOL_VERSION = "2026-07-28"


def test_mcp_server_discover_and_server_info() -> None:
    """Verify POST /mcp server/discover returns GOE Listener MCP server metadata."""
    app = create_app()
    headers, payload = _mcp_request("server/discover", req_id=1)
    with TestClient(app=app) as client:
        response = client.post("/mcp", headers=headers, json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["supportedVersions"] == [MCP_PROTOCOL_VERSION]
        assert "tools" in data["result"]["capabilities"]


def test_mcp_tools_list_discovers_listener_endpoints() -> None:
    """Verify POST /mcp tools/list exposes discovered Listener MCP tools."""
    app = create_app()
    headers, payload = _mcp_request("tools/list", req_id=2)
    with TestClient(app=app) as client:
        response = client.post("/mcp", headers=headers, json=payload)
        assert response.status_code == 200
        tools = response.json()["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        assert "check_connectivity" in tool_names
        assert "get_listener_config" in tool_names


def test_mcp_plugin_builder() -> None:
    """Verify build_mcp_config and build_mcp_plugin return configured instances."""
    cfg = build_mcp_config()
    assert cfg.name == "GOE Listener MCP"
    plugin = build_mcp_plugin()
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
