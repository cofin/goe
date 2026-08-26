---
type: Task
id: embedded_listener_and_task_execution_20260826:pyproject_dependency_reduction
title: Remove Redis/Valkey and litestar-queues Dependencies from pyproject.toml
description: Remove external broker dependencies (valkey, redis, hiredis, libvalkey, litestar-queues) from pyproject.toml and lock dependencies with uv.
state: open
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-08-26T21:23:00Z"
tags:
  - dependencies
  - pyproject
  - cleanup
  - uv
depends_on: []
files:
  - pyproject.toml
tests:
  - tests/unit/listener/test_jobs.py
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
verification_strategy: behavior_tdd
---

# Task: Remove Redis/Valkey and litestar-queues Dependencies from pyproject.toml

## Objective
Clean up `pyproject.toml` by removing `valkey[libvalkey]>=6.1.1` and `litestar-queues>=0.1.0` dependencies. Synchronize `uv.lock` to guarantee that no external caching server or queue broker packages are pulled into the environment.

## Target Changes
- **File:** `pyproject.toml` (lines 68-80)
- **Modifications:**
  Remove:
  - `"valkey[libvalkey]>=6.1.1"`
  - `"litestar-queues>=0.1.0"`

  Retain standard lean listener dependencies:
  ```toml
  # GOE Listener packages
  "brotli>=1.0.9",
  "tenacity>=8.0.1",
  "uvloop",
  "httptools",
  "litestar>=2.8.0",
  "litestar-granian>=0.4.0",
  "litestar-security>=0.1.0",
  "litestar-autowire>=0.1.0",
  "litestar-mcp>=0.1.0",
  ```

## Implementation Checklist
- [ ] Remove `"valkey[libvalkey]>=6.1.1"` from `dependencies` in `pyproject.toml`.
- [ ] Remove `"litestar-queues>=0.1.0"` from `dependencies` in `pyproject.toml`.
- [ ] Verify `[project.optional-dependencies]` does not contain dangling references to valkey/redis/litestar-queues.
- [ ] Run `uv lock` to update `uv.lock`.
- [ ] Verify `uv.lock` no longer contains `valkey`, `redis`, `hiredis`, `libvalkey`, or `litestar-queues`.

## Verification Strategy
- **Command:**
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv lock --check && uv run pytest tests/unit/listener
  ```
- **Success Criteria:** `uv.lock` is consistent and valid; all existing unit tests pass or skip safely during dependency transition.
