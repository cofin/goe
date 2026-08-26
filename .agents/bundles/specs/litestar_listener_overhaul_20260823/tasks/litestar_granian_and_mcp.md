---
type: Task
id: litestar_listener_overhaul_20260823:litestar_granian_and_mcp
title: Configure litestar-granian Runtime & Expose MCP Tools via litestar-mcp
description: Configure litestar-granian ASGI server runtime and expose GOE operations as MCP tools.
state: closed
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
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
  - src/goe/listener/__main__.py
  - src/goe/cli/commands/listener.py
  - src/goe/listener/app.py
tests:
  - tests/unit/listener/test_granian_server.py
  - tests/unit/listener/test_mcp_tools.py
verification_strategy: static_validation
---

# Task: Configure litestar-granian Runtime & Expose MCP Tools via litestar-mcp

## Objective
Configure `litestar-granian[uvloop]` as the production ASGI web server runtime (replacing Gunicorn and Uvicorn in `src/goe/listener/wsgi.py`) and expose GOE orchestration operations as Model Context Protocol (MCP) tools and resources via `litestar-mcp`.

## Implementation Details
1. Create `src/goe/listener/server.py` with `run_granian_server(...)` initializing `Granian(target="goe.listener.app:create_app", interface=Interfaces.ASGI, loop=Loops.uvloop)`.
2. Create `src/goe/listener/mcp.py` exposing `@tool execute_offload`, `@tool validate_table_aggregation`, `@tool get_execution_status`, and `@resource` definitions.
3. Update `src/goe/cli/commands/listener.py` to invoke `run_granian_server`.

## Verification Strategy
- **Strategy**: `static_validation`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_granian_server.py tests/unit/listener/test_mcp_tools.py -v
  ```
- **Expected Output**: Granian server configuration and MCP tool tests pass green.\n