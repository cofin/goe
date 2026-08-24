---
type: Task
id: litestar_listener_overhaul_20260823:litestar_queues_and_workers
title: Migrate Background Tasks & Cron Workers to litestar-queues
description: Migrate background tasks and periodic Redis synchronization to litestar-queues.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - migration
  - litestar
  - queues
  - workers
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
files:
  - src/goe/listener/tasks.py
  - src/goe/listener/worker.py
  - src/goe/listener/services/periodic_tasks.py
  - src/goe/listener/app.py
tests:
  - tests/unit/listener/test_queues_and_workers.py
verification_strategy: behavior_tdd
---

# Task: Migrate Background Tasks & Cron Workers to litestar-queues

## Objective
Replace custom daemon loops in `src/goe/listener/worker.py`, `src/goe/listener/core/worker.py`, and `src/goe/listener/heartbeat.py` with `litestar-queues[sqlspec]` cron workers and task queues, executing periodic Redis state synchronization and asynchronous offload jobs.

> [!IMPORTANT]
> Use `litestar-queues[sqlspec]`. Under no circumstances should `litestar-saq` or legacy `goelib_contrib.worker` be used.

## Implementation Details
1. Replace `goelib_contrib.asyncer` (`asyncify`, `runnify`) across `src/goe/listener/` with `sqlspec.utils.sync_tools.async_` and `sqlspec.utils.portal.get_global_portal()`.
2. Create `src/goe/listener/tasks.py`:
   - `@task(name="listener:publish_heartbeat")`
   - `@task(name="listener:publish_schemas")`
   - `@task(name="listener:publish_command_executions")`
   - `@task(name="listener:dispatch_async_offload")`
3. Configure `QueuePlugin` with `CronJob` entries in `src/goe/listener/app.py`.
4. Create `src/goe/listener/worker.py` worker startup script using `run_worker(app)`.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_queues_and_workers.py -v
  ```
- **Expected Output**: Queue tasks and cron job tests pass green.\n