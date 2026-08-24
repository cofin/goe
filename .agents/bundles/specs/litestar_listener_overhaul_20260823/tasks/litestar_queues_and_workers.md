---
type: Task
id: litestar_listener_overhaul_20260823:litestar_queues_and_workers
title: Migrate Background Tasks & Cron Workers to litestar-queues
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - task
  - litestar
  - queues
  - workers
depends_on:
  - litestar_listener_overhaul_20260823:litestar_app_and_dtos
files:
  - src/goe/listener/tasks.py
  - src/goe/listener/worker.py
tests:
  - tests/unit/listener/
verification_strategy: behavior_tdd
---

# Task: Migrate Background Tasks & Cron Workers to litestar-queues

## Objective
Replace custom background daemon loops in `src/goe/listener/worker.py` with `litestar-queues[sqlspec]`, scheduling periodic Redis state synchronization and async offload job dispatching.

## Implementation Details

1. Create `src/goe/listener/tasks.py`:
   - Define `@task` functions:
     - `publish_command_executions`: Periodically queries active executions and syncs status to Redis.
     - `publish_schemas`: Periodically broadcasts updated database schemas to Redis subscribers.
     - `dispatch_async_offload`: Dispatches long-running offload jobs in background worker pool.
2. Configure `QueuePlugin` in `src/goe/listener/app.py` with Redis backend and cron schedules.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Custom while-loop daemon subprocesses in `worker.py`.
- **Final Evidence**: `litestar-queues` worker executes registered tasks on schedule; unit tests verify task dispatch and execution.
