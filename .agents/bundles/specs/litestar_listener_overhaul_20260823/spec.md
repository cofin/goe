---
type: Spec
flow_id: litestar_listener_overhaul_20260823
title: Next-Generation Litestar Listener Service & Ecosystem
state: planned
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
description: Complete rebuild of the GOE Listener service with Litestar 2.8+, Granian ASGI runtime, litestar-queues, litestar-security, litestar-autowire, and litestar-mcp.
tags:
  - spec
  - litestar
  - granian
  - queues
  - security
  - mcp
  - autowire
parent_prd: modernization_overhaul_20260823
research:
  - modernization_overhaul_20260822
---

# Flow: Next-Generation Litestar Listener Service & Ecosystem

**Flow ID:** `litestar_listener_overhaul_20260823`

## Specification

### Code Analysis Summary
- **Current Listener**: Legacy FastAPI 0.77.0, Uvicorn 0.17.6, and Gunicorn 20.1.0 in `src/goe/listener/asgi.py`. Custom background worker supervisor daemon (`worker.py` and `goelib_contrib.worker`).
- **Target Stack**:
  - `litestar[jinja,jwt,structlog]>=2.8.0`
  - `litestar-granian[uvloop]` (high-performance Rust ASGI runtime)
  - `litestar-queues[sqlspec]` (task queue and cron workers, replacing SAQ and custom daemons)
  - `litestar-security[argon2,mfa,passkeys]` (API key and token authentication)
  - `litestar-autowire[dishka,queues]` (declarative autowiring and dependency injection)
  - `litestar-mcp` (Model Context Protocol agent integration)
  - `MsgspecDTO` for zero-overhead validation and auto-generated OpenAPI documentation.

### Requirements

#### Functional Requirements
1. Remove all dependencies on `fastapi`, `uvicorn`, and `gunicorn`.
2. Implement native `Litestar` application factory in `src/goe/listener/app.py`.
3. Configure `litestar-granian` for server startup (`goe listener start`).
4. Rebuild background tasks using `litestar-queues` for periodic Redis synchronization (`publish-command-executions`, `publish-schemas`) and asynchronous offload jobs.
5. Implement `litestar-security` API key guard for `x-goe-console-key` header authentication.
6. Implement `litestar-autowire` for service lifecycle dependencies.
7. Expose GOE operations as tools and resources via `litestar-mcp`.
8. Ensure all existing REST endpoints (`/api/system/*`, `/api/orchestration/*`) maintain 100% JSON contract compatibility.
9. Author end-to-end Listener API tests using Litestar's `TestClient` / `AsyncTestClient`.

---

## Implementation Plan

### Phase 1: Litestar Application Factory & DTOs
- [ ] `litestar_app_and_dtos`: Create Litestar application factory, controllers, and `MsgspecDTO` schemas matching existing REST endpoints.

### Phase 2: Security Guards & Autowire DI
- [ ] `litestar_security_and_autowire`: Implement `litestar-security` authentication guard for `x-goe-console-key` and configure `litestar-autowire`.

### Phase 3: Task Queues & Cron Workers
- [ ] `litestar_queues_and_workers`: Migrate periodic Redis jobs and background tasks to `litestar-queues[sqlspec]`.

### Phase 4: Granian Server Runtime & MCP Integration
- [ ] `litestar_granian_and_mcp`: Configure `litestar-granian` server CLI runner and expose MCP tools via `litestar-mcp`.

### Phase 5: Integration Testing & Verification
- [ ] `listener_api_verification_tests`: Implement comprehensive API tests with `AsyncTestClient` validating all routes, auth guards, and error handlers.
