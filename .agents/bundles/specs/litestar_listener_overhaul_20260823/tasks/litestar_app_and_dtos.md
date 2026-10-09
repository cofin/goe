---
type: Task
id: litestar_listener_overhaul_20260823:litestar_app_and_dtos
title: Build Litestar Application Factory, Controllers, Exception Handlers, and MsgspecDTOs
description: Build Litestar application factory, controllers, exception handlers, and MsgspecDTO schemas.
state: closed
priority: P1
verification_strategy: behavior_tdd
depends_on: []
files:
  - src/goe/listener/app.py
  - src/goe/listener/schemas/system.py
  - src/goe/listener/schemas/orchestration.py
  - src/goe/listener/controllers/__init__.py
  - src/goe/listener/controllers/system.py
  - src/goe/listener/controllers/orchestration.py
  - src/goe/listener/exceptions/__init__.py
  - src/goe/listener/exceptions/handlers.py
tests:
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
plan_revision: 1
plan_commit: 57f84ab
state_revision: 1
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
  - command: "uv run pytest tests/unit/listener/test_system_controllers.py tests/unit/listener/test_orchestration_controllers.py -v"
    result: "passed"
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-26T15:25:00Z"
commit: 57f84ab
tags:
  - feature
  - litestar
  - api
  - dtos
  - controllers
---

# Task: Build Litestar Application Factory, Controllers, Exception Handlers, and MsgspecDTOs

## Objective
Replace the legacy FastAPI application in `src/goe/listener/asgi.py` with a native Litestar application factory (`src/goe/listener/app.py`), defining modular `Controller` classes, `msgspec.Struct` schemas, and custom error handlers for `/api/system/*` and `/api/orchestration/*`.

## Context
The GOE Listener REST service requires zero-overhead JSON serialization and native Litestar routing while preserving 100% endpoint compatibility.

## Steps
1. Create `src/goe/listener/schemas/` defining typed `msgspec.Struct` models (`HealthCheck`, `ListenerConfig`, `OffloadableSchemas`, `TableDetails`, `ColumnDetails`, `PartitionDetails`, `CommandExecution`, `CommandExecutionStep`, `CommandExecutionLog`, `OffloadOptions`, `CommandScheduled`, `ErrorMessage`).
2. Create `src/goe/listener/controllers/system.py` with `SystemController` implementing all `/api/system/*` routes.
3. Create `src/goe/listener/controllers/orchestration.py` with `OrchestrationController` implementing all `/api/orchestration/*` routes.
4. Create `src/goe/listener/exceptions/handlers.py` mapping exceptions to standard error payloads.
5. Create `src/goe/listener/app.py` with `create_app()` factory configuring OpenAPI, compression, CORS, and plugins.

## Verification
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_system_controllers.py tests/unit/listener/test_orchestration_controllers.py -v
  ```
- **Expected Output**: Controller tests pass 100% green.

## Acceptance Criteria
- [x] `create_app()` initializes Litestar application with `SystemController` and `OrchestrationController`.
- [x] Request/response schemas use `msgspec.Struct` models.
- [x] Exception handlers return structured error payloads.

## Notes & Discoveries
- `2026-08-26T15:25:00Z` (`57f84ab`): Completed and verified in PR #5.\n