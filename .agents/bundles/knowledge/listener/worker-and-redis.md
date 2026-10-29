---
type: Reference
title: Listener Durable Job Queue & Bounded Caching
description: SQLSpec-backed durable job queue (Oracle SKIP LOCKED + SQLite WAL fallback), DurableJobWorker, cluster node heartbeats, and bounded LRU + singleflight ListenerCache
tags:
  - reference
  - listener
  - cache
  - workers
  - jobs
  - sqlspec
updated_at: "2026-10-28T21:19:00Z"
---

# Listener Durable Job Queue & Bounded Caching

The Listener uses a durable `sqlspec`-backed job queue (`src/goe/listener/jobs/{models,store,worker}.py` and `src/goe/listener/jobs/sql/job_queue.sql`) and a bounded LRU + singleflight in-process cache (`ListenerCache` and `ListenerCacheSink` in `src/goe/listener/cache.py`). Neither `litestar-queues` nor external Redis infrastructure is required.

## Durable Job Queue (`src/goe/listener/jobs/`)

- **Domain Models (`src/goe/listener/jobs/models.py`)**:
  - `JobStatus`: `Literal["QUEUED", "CLAIMED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"]`.
  - `JobRecord(FrozenBaseStruct)`: Durable job row (`job_id`, `execution_id`, `command_type`, `table_owner`, `table_name`, `status`, `attempt`, `max_attempts`, `lease_owner`, `lease_expires_at`, `heartbeat_at`, `cancel_requested`, `payload_json`, `error_message`, `traceparent`, `tracestate`, `created_at`, `updated_at`, `completed_at`).
  - `JobLease(FrozenBaseStruct)` and `NodeHeartbeat(FrozenBaseStruct)` (`node_id`, `listener_group_id`, `endpoint_id`, `host`, `port`, `active_jobs`, `updated_at`).
- **Repository DDL (`sql/oracle/source/sql/create_offload_repo_24.sql`) & Named SQL (`src/goe/listener/jobs/sql/job_queue.sql`)**:
  - Defines `OFFLOAD_JOB_QUEUE` (with active-table function-based unique index `OFFLOAD_JOB_QUEUE_UK1` on `CASE WHEN STATUS IN ('QUEUED', 'CLAIMED', 'RUNNING') THEN TABLE_OWNER || '.' || TABLE_NAME END`) and `OFFLOAD_NODE_HEARTBEAT`.
- **`JobStoreProtocol` Implementations (`src/goe/listener/jobs/store.py`)**:
  - `OracleJobStore`: Uses `SELECT ... FROM OFFLOAD_JOB_QUEUE WHERE STATUS = 'QUEUED' ORDER BY CREATED_AT ASC FOR UPDATE SKIP LOCKED` with `cursor.fetchmany(limit)` to claim jobs across multi-node Listener clusters without blocking concurrent workers. Maps `ORA-00001` on `OFFLOAD_JOB_QUEUE_UK1` to `DuplicateActiveTableJobError` (`HTTP 409 Conflict`).
  - `SqliteJobStore`: Local single-host fallback (`$OFFLOAD_HOME/run/listener_jobs.db`, `PRAGMA journal_mode=WAL`, `BEGIN IMMEDIATE` claim transactions, and partial unique index on active `(table_owner, table_name)`).
- **`DurableJobWorker` (`src/goe/listener/jobs/worker.py`)**:
  - Claims queued jobs, transitions `CLAIMED -> RUNNING`, spawns a background lease renewal + `cancel_requested` polling thread, restores W3C trace context (`trace_context_from_headers`), executes `orchestrate.offload` inside `LocalProcessWorker` with `LameDuckController`, and records `SUCCEEDED`, `CANCELLED`, `FAILED` (re-queued when `attempt < max_attempts`), or `DEAD_LETTER`.
  - Runs embedded inside the Listener ASGI lifespan or standalone via `goe listener start --worker-only`.

## Bounded LRU + Singleflight Cache (`src/goe/listener/cache.py`)

- **`ListenerCache`**: Thread-safe (`threading.RLock`) bounded LRU (`OrderedDict`, default `max_entries=512`) with monotonic TTL (`time.monotonic()`) and async singleflight stampede coalescing (`get_or_load(key, loader, ttl=...)` sharing an in-flight `asyncio.Task` across concurrent callers for the same cache key).
- **`ListenerCacheSink`**: Implements `ExecutionSink` (`src/goe/orchestration/sinks.py`) so `on_command_start`, `on_step_start`, `on_step_end`, and `on_command_end` invalidate stale `executions:*` and `schemas:*` cache prefixes immediately on state transitions.
- **No Unbounded Background Polling**: The legacy `periodic_tasks.py` and `MemoryCache` (`src/goe/listener/utils/cache.py`) were replaced by on-demand singleflight `ListenerCache.get_or_load` and event-driven `ListenerCacheSink` invalidation.
