---
type: Task
id: litestar_listener_overhaul_20260823:litestar_granian_and_mcp
title: Configure litestar-granian Runtime & Expose MCP Tools via litestar-mcp
description: Configure litestar-granian ASGI server runtime and expose GOE operations as MCP tools.
state: closed
priority: P2
verification_strategy: static_validation
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
  - tests/unit/listener/test_mcp.py
plan_revision: 1
plan_commit: 57f84ab
state_revision: 4
claimed_by: null
claimed_at: null
blocked_reason: null
unblock_condition: null
next_step: null
last_operation: null
operation_targets: []
last_verified_at: "2026-08-26T15:25:00Z"
last_verified_commit: 57f84ab
verification_evidence:
  - command: "uv run pytest tests/unit/listener/test_mcp.py -v"
    result: "passed"
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-26T15:25:00Z"
commit: 57f84ab
tags:
  - feature
  - litestar
  - granian
  - mcp
---

# Task: Configure litestar-granian Runtime & Expose MCP Tools via litestar-mcp

## Objective
Configure `litestar-granian[uvloop]` as the production ASGI web server runtime (replacing Gunicorn and Uvicorn) and expose GOE orchestration operations as Model Context Protocol (MCP) tools and resources via `litestar-mcp`.

## Context
Granian provides a high-performance Rust ASGI server with `uvloop` integration, while `litestar-mcp` exposes GOE capabilities to MCP clients.

## Steps
1. Create `src/goe/listener/server.py` with `run_granian_server(...)` initializing `Granian` with ASGI interface and `uvloop`.
2. Create `src/goe/listener/mcp.py` exposing offload, validation, and status MCP tools and resources.
3. Update `src/goe/cli/commands/listener.py` to invoke `run_granian_server`.

## Verification
- **Strategy**: `static_validation`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_mcp.py -v
  ```
- **Expected Output**: Granian server configuration and MCP tool tests pass green.

## Acceptance Criteria
- [x] `GranianPlugin` and `LitestarMCP` registered in `create_app()`.
- [x] `goe listener` starts the Granian ASGI runtime.

## Notes & Discoveries
- `2026-08-26T15:25:00Z` (`57f84ab`): Completed and verified in PR #5.\n