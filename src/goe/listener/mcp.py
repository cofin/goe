# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Model Context Protocol (MCP) configuration for GOE Listener."""

from litestar_mcp import LitestarMCP, MCPConfig

from goe.listener.telemetry import after_mcp_tool_call, before_mcp_tool_call


def build_mcp_config() -> MCPConfig:
    """Build the LitestarMCP configuration for GOE Listener."""
    return MCPConfig(
        name="GOE Listener MCP",
        before_tool_call=before_mcp_tool_call,
        after_tool_call=after_mcp_tool_call,
    )


def build_mcp_plugin() -> LitestarMCP:
    """Build the LitestarMCP plugin instance."""
    return LitestarMCP(build_mcp_config())
