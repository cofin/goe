# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from litestar.testing import TestClient

from goe.listener.app import create_app


def test_mcp_agent_card():
    app = create_app()
    with TestClient(app=app) as client:
        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "GOE Listener MCP"
        assert data["capabilities"]["mcp"] is True


def test_mcp_oauth_protected_resource():
    app = create_app()
    with TestClient(app=app) as client:
        response = client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
