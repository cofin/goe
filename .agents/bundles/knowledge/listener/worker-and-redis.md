---
type: concept
title: Listener Durable Job Queue & Bounded Caching
description: Oracle-backed SQLSpec durable job queue (GOE_LISTENER_JOBS with SKIP LOCKED and cooperative CANCEL_REQUESTED cancellation), DurableJobWorker, cluster node heartbeats, and bounded LRU + singleflight ListenerCache.
status: stable
tags:
  - reference
  - listener
  - cache
  - workers
  - jobs
  - oracle
  - sqlspec
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: job-store
    resource: src/goe/listener/jobs/store.py::OracleJobStore
    title: Oracle-Backed Durable Job Queue Store
  - id: job-worker
    resource: src/goe/listener/jobs/worker.py::DurableJobWorker
    title: Durable Job Worker and Cooperative Cancellation Sink
  - id: listener-cache
    resource: src/goe/listener/cache.py::ListenerCache
    title: Bounded LRU and Singleflight Listener Cache
---

# Listener Durable Job Queue & Bounded Caching

<!-- truth: start -->
- `OracleJobStore` (`src/goe/listener/jobs/store.py`) persists Listener jobs in `GOE_LISTENER_JOBS` and worker heartbeats in `GOE_LISTENER_ENDPOINTS` via `OracleDatabaseRegistry.for_options(config)`, claiming jobs with `SELECT ... FOR UPDATE SKIP LOCKED` + `cursor.fetchmany(limit)`.[^job-store]
- `DurableJobWorker` (`src/goe/listener/jobs/worker.py`) executes `OrchestrationRunner` in `asyncio.to_thread` with `_CooperativeCancelSink`, unwinding on `CANCEL_REQUESTED` before `mark_cancelled()` releases `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ`.[^job-worker]
- `ListenerCache` (`src/goe/listener/cache.py`) provides bounded LRU + TTL + singleflight coalescing (`max_entries=1024`) with event-driven invalidation via `ListenerCacheSink`.[^listener-cache]
<!-- truth: end -->

The Listener uses an Oracle-backed durable `sqlspec` job queue (`src/goe/listener/jobs/{models,store,worker}.py` and `src/goe/listener/jobs/sql/job_queue.sql`) and a bounded LRU + singleflight in-process cache (`ListenerCache` and `ListenerCacheSink` in `src/goe/listener/cache.py`). Neither `litestar-queues`, SQLite, nor external Redis infrastructure is used.

## Oracle Durable Job Queue (`src/goe/listener/jobs/`)

- **Domain Models (`src/goe/listener/jobs/models.py`)**:
  - `JobStatus`: `StrEnum` (`PENDING`, `CLAIMED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `DEAD_LETTER`).
  - `JobRecord(FrozenBaseStruct)`: Durable job row (`job_id`, `execution_id`, `table_key`, `status`, `payload_json`, `attempt`, `max_attempts`, `created_at`, `updated_at`, `worker_id`, `claimed_at`, `lease_expires_at`, `started_at`, `finished_at`, `error_message`, `cancel_requested`).
  - `EndpointHeartbeat(FrozenBaseStruct)`: Active Listener node heartbeat (`endpoint_id`, `listener_group_id`, `host_url`, `worker_role`, `updated_at`, `expires_at`, `version`).
  - `DuplicateActiveTableJobError` (`HTTP 409 Conflict`) and `JobCancelledError`.
- **Repository DDL (`src/goe/persistence/oracle/ddl/sql/create_offload_repo_24.sql`) & Named SQL (`src/goe/listener/jobs/sql/job_queue.sql`)**:
  - Defines `GOE_LISTENER_JOBS` (including `CANCEL_REQUESTED NUMBER(1) DEFAULT 0 NOT NULL` and active-table function-based unique index `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ` on `CASE WHEN STATUS IN ('PENDING', 'CLAIMED', 'RUNNING') THEN TABLE_KEY END`) and `GOE_LISTENER_ENDPOINTS`.
- **`OracleJobStore` & `create_job_store` (`src/goe/listener/jobs/store.py`)**:
  - `create_job_store` resolves an Oracle connection factory from `OracleDatabaseRegistry.for_options(OrchestrationConfig.as_defaults(do_not_connect=True))` and constructs `OracleJobStore`.
  - `OracleJobStore.claim_next`: Uses `SELECT ... FROM GOE_LISTENER_JOBS WHERE STATUS = 'PENDING' AND CANCEL_REQUESTED = 0 ORDER BY CREATED_AT ASC FOR UPDATE SKIP LOCKED` with `cursor.fetchmany(limit)` to claim jobs across multi-node Listener clusters without blocking concurrent workers. Maps `ORA-00001` on `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ` to `DuplicateActiveTableJobError` (`HTTP 409 Conflict`).
  - `OracleJobStore.cancel_job` & `mark_cancelled`: `cancel_job(execution_id)` transitions `PENDING`/`CLAIMED` jobs directly to `STATUS = 'CANCELLED'` (`CANCEL_REQUESTED = 1`) and marks `RUNNING` jobs with `CANCEL_REQUESTED = 1` for cooperative worker termination. `reap_expired_leases` transitions expired leases with `CANCEL_REQUESTED = 1` to `CANCELLED` before re-queuing remaining expired leases to `PENDING` or `DEAD_LETTER`.
- **`DurableJobWorker` & `_CooperativeCancelSink` (`src/goe/listener/jobs/worker.py`)**:
  - Claims pending jobs, transitions `CLAIMED -> RUNNING`, spawns a background lease renewal thread, restores W3C trace context (`extract_trace_context`), and executes `orchestrate.offload` with `_CooperativeCancelSink` injected at the front of `sinks`.
  - At every `on_command_start` and `on_step_start` boundary, `_CooperativeCancelSink` checks `store.get_job_by_execution_id(record.execution_id).cancel_requested`; when set, it raises `JobCancelledError`, allowing `orchestrate.offload` to unwind its `with orchestration_lock_for_table(...):` context manager cleanly before `DurableJobWorker` calls `store.mark_cancelled(...)`.
  - Runs embedded inside the Listener ASGI lifespan or standalone via `goe listener start --worker-only`.

## Bounded LRU + Singleflight Cache (`src/goe/listener/cache.py`)

- **`ListenerCache`**: Thread-safe (`threading.RLock`) bounded LRU (`OrderedDict`, default `max_entries=512`) with monotonic TTL (`time.monotonic()`) and async singleflight stampede coalescing (`get_or_load(key, loader, ttl=...)` sharing an in-flight `asyncio.Task` across concurrent callers for the same cache key).
- **`ListenerCacheSink`**: Implements `ExecutionSink` (`src/goe/orchestration/sinks.py`) so `on_command_start`, `on_step_start`, `on_step_end`, and `on_command_end` invalidate stale `executions:*`, `schemas:*`, and `tables:*` cache prefixes immediately on state transitions.

[^job-store]: `src/goe/listener/jobs/store.py::OracleJobStore` — Oracle-Backed Durable Job Queue Store.
[^job-worker]: `src/goe/listener/jobs/worker.py::DurableJobWorker` — Durable Job Worker and Cooperative Cancellation Sink.
[^listener-cache]: `src/goe/listener/cache.py::ListenerCache` — Bounded LRU and Singleflight Listener Cache.
