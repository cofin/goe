---
type: Task
id: litestar_listener_overhaul_20260823:litestar_queues_and_workers
title: Migrate Background Tasks & Cron Workers to litestar-queues
description: Migrate background tasks and periodic Redis synchronization to litestar-queues.
state: closed
priority: P1
verification_strategy: behavior_tdd
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
files:
  - src/goe/listener/jobs.py
  - src/goe/listener/worker.py
  - src/goe/listener/services/periodic_tasks.py
  - src/goe/listener/app.py
tests:
  - tests/unit/listener/test_jobs.py
plan_revision: 1
plan_commit: 57f84ab
state_revision: 3
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
  - command: "uv run pytest tests/unit/listener/test_jobs.py -v"
    result: "passed"
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-26T15:25:00Z"
commit: 57f84ab
tags:
  - migration
  - litestar
  - queues
  - workers
---

# Task: Migrate Background Tasks & Cron Workers to litestar-queues

## Objective
Replace custom daemon loops in `src/goe/listener/worker.py` and `src/goe/listener/services/heartbeat.py` with `litestar-queues` cron workers and task queues, executing periodic state synchronization and asynchronous offload jobs.

## Context
Legacy `goelib_contrib.worker` and `goelib_contrib.asyncer` modules are replaced by `sqlspec.utils.sync_tools` and `litestar-queues`.

## Steps
1. Replace `goelib_contrib.asyncer` across `src/goe/listener/` with `sqlspec.utils.sync_tools.async_` and `sqlspec.utils.portal.get_global_portal()`.
2. Create `src/goe/listener/jobs.py` registering heartbeat, schema sync, command execution sync, and offload background tasks.
3. Configure `QueuePlugin` in `src/goe/listener/app.py`.
4. Update `src/goe/listener/worker.py` worker startup script.

## Verification
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_jobs.py -v
  ```
- **Expected Output**: Queue tasks and cron job tests pass green.

## Acceptance Criteria
- [x] Background tasks registered via `litestar-queues`.
- [x] All `goelib_contrib` imports eliminated from `src/goe/listener/`.

## Notes & Discoveries
- `2026-08-26T15:25:00Z` (`57f84ab`): Completed and verified in PR #5.\n