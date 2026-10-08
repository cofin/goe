# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Model Context Protocol (MCP) configuration for GOE Listener."""

from litestar_mcp import LitestarMCP, MCPConfig


def build_mcp_config() -> MCPConfig:
    """Build the LitestarMCP configuration for GOE Listener."""
    return MCPConfig(name="GOE Listener MCP")


def build_mcp_plugin() -> LitestarMCP:
    """Build the LitestarMCP plugin instance."""
    return LitestarMCP(build_mcp_config())
