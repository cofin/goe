---
type: Task
id: embedded_listener_and_task_execution_20260826:pyproject_dependency_reduction
title: Remove Valkey/Redis Dependencies and Purge Legacy FastAPI/Gunicorn Modules
description: Remove external broker dependencies (valkey, redis, hiredis, libvalkey) from pyproject.toml while retaining litestar-queues, and delete dead legacy FastAPI/Gunicorn/worker files in src/goe/listener/.
state: closed
priority: P1
plan_revision: 2
plan_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
state_revision: 2
claimed_by: null
claimed_at: null
blocked_reason: null
unblock_condition: null
next_step: null
last_operation: 20261002T211500Z-flow-finish-00
operation_targets: []
last_verified_at: "2026-10-02T21:15:00Z"
last_verified_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
verification_evidence: "uv run pytest tests/unit/listener"
commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-10-02T21:15:00Z"
tags:
  - refactor
  - dependencies
  - pyproject
  - uv
depends_on: []
files:
  - pyproject.toml
  - src/goe/listener/__main__.py
  - src/goe/listener/config/application.py
tests:
  - tests/unit/listener/test_jobs.py
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
verification_strategy: behavior_tdd
---

# Task: Remove Valkey/Redis Dependencies and Purge Legacy FastAPI/Gunicorn Modules

## Objective
Clean up `pyproject.toml` by removing `valkey[libvalkey]>=6.1.1` while retaining `litestar-queues>=0.1.0`, synchronize `uv.lock`, and remove dead legacy FastAPI/Uvicorn/Gunicorn/`goelib_contrib` modules from `src/goe/listener/`.

## Context
- **File:** `pyproject.toml` (lines 68-80)
- **Modifications:**
  Remove `"valkey[libvalkey]>=6.1.1"` while keeping first-party Litestar ecosystem packages (`litestar`, `litestar-granian`, `litestar-queues`, `litestar-security`, `litestar-autowire`, `litestar-mcp`).
- **Legacy Dead Files to Remove under `src/goe/listener/`**:
  - `src/goe/listener/wsgi.py`
  - `src/goe/listener/config/gunicorn.conf.py`
  - `src/goe/listener/core/` (`__init__.py`, `enum.py`, `events.py`, `security.py`, `worker.py`, `middleware/`)
  - `src/goe/listener/heartbeat.py`
  - `src/goe/listener/prestart.py`
  - `src/goe/listener/worker.py`
  - `src/goe/listener/services/heartbeat.py`
- Update `src/goe/listener/__main__.py` to launch Granian (`goe.listener.asgi:app`).

## Steps
- [x] Remove `"valkey[libvalkey]>=6.1.1"` from `dependencies` in `pyproject.toml` while retaining `"litestar-queues>=0.1.0"`.
- [x] Remove dead legacy FastAPI/Gunicorn/`goelib_contrib` modules under `src/goe/listener/` and update `src/goe/listener/__main__.py`.
- [x] Update `uv.lock` so `valkey` and `libvalkey` are no longer required by `goe-framework`.

## Verification
```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener
```

## Acceptance Criteria
- [x] `pyproject.toml` and `uv.lock` no longer require `valkey` or `libvalkey` while retaining `litestar-queues`.
- [x] All legacy FastAPI/Starlette/Gunicorn/`goelib_contrib` dead files under `src/goe/listener/` are removed.

## Notes & Discoveries
- Removed `valkey[libvalkey]>=6.1.1` from `pyproject.toml`, updated `uv.lock`, and deleted 15 dead legacy FastAPI/Gunicorn/worker files in `src/goe/listener/`.
