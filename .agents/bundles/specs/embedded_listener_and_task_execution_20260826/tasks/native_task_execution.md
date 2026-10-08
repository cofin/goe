---
type: Task
id: embedded_listener_and_task_execution_20260826:native_task_execution
title: Wire First-Party litestar-queues, litestar-security, Autowire, and LitestarMCP
description: Wire real periodic tasks in litestar-queues jobs.py, implement litestar-security console-key auth in security.py, upgrade controllers to Litestar 2.24 native DI and mcp_tool markers, and configure AutowirePlugin(integrations=['queues']) in app.py.
state: closed
priority: P1
plan_revision: 2
plan_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
state_revision: 4
claimed_by: null
claimed_at: null
blocked_reason: null
unblock_condition: null
next_step: null
last_operation: 20261002T211500Z-flow-finish-00
operation_targets: []
last_verified_at: "2026-10-02T21:15:00Z"
last_verified_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
verification_evidence: "uv run pytest tests/unit/listener -v"
commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-10-02T21:15:00Z"
tags:
  - refactor
  - litestar
  - litestar-queues
  - litestar-security
  - litestar-mcp
depends_on:
  - embedded_listener_and_task_execution_20260826:embedded_memory_cache
files:
  - src/goe/listener/jobs.py
  - src/goe/listener/security.py
  - src/goe/listener/controllers/system.py
  - src/goe/listener/controllers/orchestration.py
  - src/goe/listener/app.py
tests:
  - tests/unit/listener/test_jobs.py
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
  - tests/unit/listener/test_mcp.py
verification_strategy: behavior_tdd
---

# Task: Wire First-Party litestar-queues, litestar-security, Autowire, and LitestarMCP

## Objective
Complete the first-party Litestar ecosystem integration in `src/goe/listener/`:
1. **`src/goe/listener/jobs.py` (`litestar-queues`)**: Connect `@task("system.heartbeat")`, `@task("system.sync_schemas")`, and `@task("system.sync_executions")` to the real `periodic_tasks` functions (`publish_heartbeat`, `publish_schemas`, `publish_command_executions`) backed by `MemoryCache`, alongside `@task("orchestration.offload")`.
2. **`src/goe/listener/security.py` (`litestar-security`)**: Implement `ConsoleKeySlot`, `ConsoleKeyAuthenticator`, `ConsoleKeyIdentityResolver`, and `build_security_config()` enforcing `x-goe-console-key` via `secrets.compare_digest` when `settings.shared_token` (`OFFLOAD_LISTENER_SHARED_TOKEN`) is configured, allowing local unauthenticated access when unset, and keeping `/api/system/status/`, `/docs*`, `/schema*`, and `/.well-known/*` public.
3. **`src/goe/listener/controllers/system.py` & `orchestration.py`**:
   - Replace deprecated `from litestar.params import Dependency, Parameter` with Litestar 2.24 native `NamedDependency`, `FromPath`, `FromQuery`, and `JSONBody`.
   - Subclass `SecureController` (with `auth=public()` on `GET /api/system/status/`).
   - Expose controller routes to `LitestarMCP` via `mcp_tool=` markers (`get_listener_config`, `list_offloadable_schemas`, `list_schema_tables`, `list_table_columns`, `list_table_partitions`, `list_command_executions`, `get_command_execution`, `get_command_execution_log`, `trigger_offload`).
4. **`src/goe/listener/app.py`**:
   - Register `SecurityPlugin(build_security_config())`, `QueuePlugin(QueueConfig(queue_backend="memory", worker=WorkerConfig(placement="asgi")))`, `LitestarMCP(MCPConfig(name="GOE Listener MCP", route_opt={"auth": public()}))`, and `AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"], integrations=["queues"]))`.

## Steps
- [x] Create `src/goe/listener/security.py` implementing `litestar-security` console-key verification and `ProtectedResourceConfig` for `/.well-known/oauth-protected-resource`.
- [x] Update `src/goe/listener/jobs.py` and `src/goe/listener/services/periodic_tasks.py` so periodic `@task` functions execute real cache synchronization.
- [x] Refactor `src/goe/listener/controllers/system.py` and `src/goe/listener/controllers/orchestration.py` to use `SecureController`, `NamedDependency`, `FromPath`, `FromQuery`, `JSONBody`, and `mcp_tool=` markers.
- [x] Update `src/goe/listener/app.py` to register `SecurityPlugin` and `AutowireConfig(domain_packages=["goe.listener"], integrations=["queues"])`.

## Verification
```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener -v
```

## Acceptance Criteria
- [x] `SecurityPlugin` enforces `x-goe-console-key` when `settings.shared_token` is set and allows local requests when unset.
- [x] `SystemController` and `OrchestrationController` use Litestar 2.24 `NamedDependency`, `FromPath`, `FromQuery`, and `JSONBody` with zero deprecated `Dependency`/`Parameter` imports.
- [x] `LitestarMCP` discovers and exposes the Listener routes as MCP tools.
- [x] `jobs.py` tasks invoke `periodic_tasks` and persist into `MemoryCache`.

## Notes & Discoveries
- Configured `AuthenticationMechanism` with `scheme_name="ConsoleKey"` and `SecurityScheme(type="apiKey", name="x-goe-console-key", security_scheme_in="header")` so `litestar-security==0.6.0` integrates cleanly with Litestar's OpenAPI schema generation.
