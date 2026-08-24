---
type: Task
id: litestar_listener_overhaul_20260823:litestar_granian_and_mcp
title: Configure litestar-granian Runtime & Expose MCP Tools via litestar-mcp
description: Configure litestar-granian ASGI server runtime and expose GOE operations as MCP tools.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - feature
  - litestar
  - granian
  - mcp
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
  - litestar_listener_overhaul_20260823:litestar_security_and_autowire
files:
  - src/goe/listener/server.py
  - src/goe/listener/mcp.py
tests:
  - tests/unit/listener/
verification_strategy: static_validation
---

# Task: Configure litestar-granian Runtime & Expose MCP Tools via litestar-mcp

## Objective
Configure `litestar-granian[uvloop]` as the authoritative ASGI web server runtime and expose GOE orchestration operations as Model Context Protocol (MCP) tools and resources via `litestar-mcp`.

## Implementation Details

1. Create `src/goe/listener/server.py`:
   - Configure Granian options (threads, workers, uvloop, HTTP/1 & HTTP/2 support).
   - Integrate with CLI command `goe listener start`.
2. Create `src/goe/listener/mcp.py`:
   - Configure `LitestarMCP` plugin.
   - Expose tools: `execute_offload`, `validate_table_aggregation`, `inspect_schema_drift`, `get_execution_status`.
   - Expose resources: `offload_metadata`, `system_health`.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: Missing Granian runner and MCP endpoints.
- **Final Evidence**: `uv run goe listener --help` displays Granian server options; MCP tool list introspectable via MCP protocol handler.
