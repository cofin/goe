---
type: Task
id: litestar_listener_overhaul_20260823:litestar_app_and_dtos
title: Build Litestar Application Factory, Controllers, Exception Handlers, and MsgspecDTOs
description: Build Litestar application factory, controllers, exception handlers, and MsgspecDTO schemas.
state: closed
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - feature
  - litestar
  - api
  - dtos
  - controllers
depends_on: []
files:
  - src/goe/listener/app.py
  - src/goe/listener/dtos.py
  - src/goe/listener/controllers/__init__.py
  - src/goe/listener/controllers/system.py
  - src/goe/listener/controllers/orchestration.py
  - src/goe/listener/exceptions/__init__.py
  - src/goe/listener/exceptions/handlers.py
tests:
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
verification_strategy: behavior_tdd
---

# Task: Build Litestar Application Factory, Controllers, Exception Handlers, and MsgspecDTOs

## Objective
Replace the legacy FastAPI application in `src/goe/listener/asgi.py` with a native Litestar application factory (`src/goe/listener/app.py`), defining modular `Controller` classes, `msgspec.Struct` / `MsgspecDTO` schemas, and custom error handlers for `/api/system/*` and `/api/orchestration/*`.

## Implementation Details
1. Create `src/goe/listener/dtos.py` defining typed `msgspec.Struct` models:
   - `HealthCheckDTO`, `ListenerConfigDTO`, `OffloadableSchemasDTO`, `TableDetailsDTO`, `ColumnDetailsDTO`, `PartitionDetailsDTO`
   - `CommandExecutionsDTO`, `CommandExecutionDTO`, `CommandExecutionStepDTO`, `CommandExecutionLogDTO`, `OffloadOptionsDTO`, `CommandScheduledDTO`, `ErrorMessageDTO`
2. Create `src/goe/listener/controllers/system.py` with `SystemController` implementing all `/api/system/*` routes.
3. Create `src/goe/listener/controllers/orchestration.py` with `OrchestrationController` implementing all `/api/orchestration/*` routes.
4. Create `src/goe/listener/exceptions/handlers.py` mapping exceptions to standard `ErrorMessageDTO` payloads.
5. Create `src/goe/listener/app.py` with `create_app()` factory configuring OpenAPI, compression, CORS, and security headers.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_system_controllers.py tests/unit/listener/test_orchestration_controllers.py -v
  ```
- **Expected Output**: Controller tests pass 100% green.\n