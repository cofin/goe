---
name: goe-diagnostics-and-recovery
description: Diagnostic and recovery procedures for failed, stalled, or lock-contended GOE offload executions.
---

# GOE Diagnostics and Recovery Runbook

## Triaging Failed or Stalled Jobs

1. List durable job records via `goe://jobs` (`list_offload_jobs`) and inspect the target job via `goe://jobs/{execution_id}` (`get_offload_job`).
2. Inspect step-level progress and error details via `goe://executions/{execution_id}` (`get_command_execution`).
3. Retrieve the execution log pointer via `get_execution_log_link` (`GET /api/orchestration/executions/{execution_id}/execution-log/link/`) and read `goe://executions/{execution_id}/log` (`get_command_execution_log`).

## Handling Table Lock Contention (`409 Conflict`)

1. GOE serializes per-table mutations using `OrchestrationLockInterface`. If `execute_offload` or `apply_schema_sync` returns HTTP `409` (`OrchestrationLockTimeout`), another worker or session holds the lock for that table.
2. Check `goe://jobs` for any `QUEUED` or `RUNNING` job targeting the same `owner_table`.

## Cooperative Job Cancellation & Safe Retry

1. To stop a queued or running job, invoke `cancel_offload_job` (`POST /api/orchestration/executions/{execution_id}/cancel/`).
2. `QUEUED` jobs transition immediately to `CANCELLED`. `RUNNING` jobs set `CANCEL_REQUESTED = 1` on `GOE_LISTENER_JOBS` and cooperatively abort at the next step boundary, unwinding `orchestration_lock_for_table` before marking the job `CANCELLED`.
3. Once `goe://jobs/{execution_id}` reports `status: "CANCELLED"`, re-run `preview_offload_plan` to obtain a fresh `confirmation_token` before retrying `execute_offload`.
