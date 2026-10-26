---
type: Spec
flow_id: durable_job_queue_listener_cache_and_mcp_20261024
title: "Chapter 10.4: Durable Job Queue, Listener Cache, and MCP"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T16:45:00Z
description: "Replaces litestar-queues and the unindexed in-memory Listener cache with a GOE-owned SQLSpec durable job queue (Oracle FOR UPDATE SKIP LOCKED with WAL SQLite fallback), bounded singleflight ListenerCache with step-event invalidation, non-blocking controllers, and authenticated MCP diagnostic and confirmation-gated tools."
tags:
  - refactor
  - listener
  - queues
  - caching
  - mcp
parent_prd: prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024
depends_on:
  - offload_plan_resolution_and_stateless_executor_20261024
research:
  - .agents/bundles/specs/prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/vertebra-and-runtime-evaluation.md
  - .agents/bundles/specs/prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
---

# Chapter 10.4: Durable Job Queue, Listener Cache, and MCP

## Specification

### 1. Overview and Goals

This chapter replaces the broken per-process `litestar-queues` configuration, the unbounded `MemoryCache` singleton, the blocking synchronous Listener controller paths, and the unauthenticated `/mcp` bypass with a cohesive control-plane architecture:

1. **Durable Job Queue Models and DDL (`src/goe/listener/jobs/models.py`, `src/goe/listener/jobs/sql/job_queue.sql`)**: Defines `JobState`, `JobRecord(FrozenBaseStruct)`, and `NodeHeartbeat(FrozenBaseStruct)`, alongside `SQLFileLoader`-compatible named queries and the Oracle repository migration (`GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS`) with a function-based unique index on `CASE WHEN STATUS IN ('PENDING', 'CLAIMED', 'RUNNING') THEN TABLE_KEY END` and a matching WAL-mode SQLite schema.
2. **Oracle and SQLite Job Stores plus Lease-Renewing Worker (`src/goe/listener/jobs/store.py`, `src/goe/listener/jobs/worker.py`)**: Implements `OracleJobStore` using `SELECT ... FOR UPDATE SKIP LOCKED` with cursor `fetchmany(limit)` (avoiding `FETCH FIRST ... FOR UPDATE`, which raises `ORA-02014` on Oracle) and `SqliteJobStore` (`PRAGMA journal_mode=WAL; BEGIN IMMEDIATE`) at `$OFFLOAD_HOME/run/listener_jobs.sqlite3`. `DurableJobWorker` claims jobs with a 120-second lease, renews leases every 30 seconds during multi-hour offloads, reaps expired leases up to `max_attempts`, and maintains durable node heartbeats.
3. **Bounded `ListenerCache`, `ListenerCacheSink`, and Non-Blocking Controllers (`src/goe/listener/cache.py`, `src/goe/listener/controllers/**`)**: Replaces `src/goe/listener/utils/cache.py` and the unread periodic tasks in `src/goe/listener/services/periodic_tasks.py` with `ListenerCache` (bounded LRU, monotonic TTL, async singleflight deduplication, prefix invalidation) and `ListenerCacheSink` (invalidating cached table/schema/execution entries when `StepFinishedEvent` or `CommandFinishedEvent` fires). Replaces `litestar-queues` in `src/goe/listener/app.py` and `pyproject.toml`, splits controller responsibilities across `system.py`, `schemas.py`, `tables.py`, and `orchestration.py`, returns `409 Conflict` when a table lock or active job is held, streams bounded logs from local or `gs://` paths with path-containment enforcement, and deletes `src/goe/listener/config/logging.py`, `src/goe/listener/utils/cache.py`, `src/goe/listener/utils/group_by.py`, `src/goe/listener/jobs.py`, and `src/goe/listener/services/periodic_tasks.py`.
4. **Authenticated MCP Surface and Confirmation Gate (`src/goe/listener/mcp.py`, `src/goe/listener/security.py`)**: Removes `r"^/mcp"` from `SecurityConfig.exclude`, adds HMAC-SHA256 `ConfirmationGate` tokens for mutating MCP tools, and exposes five read-only MCP tools (`get_connectivity_report`, `get_table_status_report`, `list_offloaded_tables`, `preview_offload_plan`, and `get_job_status`) plus schema-drift preview.

### 2. Code Analysis Summary

- `src/goe/listener/app.py:46-55`: Configures `QueuePlugin(QueueConfig(queue_backend="memory", worker=WorkerConfig(placement="asgi")))` and `AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"], integrations=["queues"]))`. With `http_workers: int = 2` (`src/goe/listener/config/application.py:27`), each worker process holds an isolated in-memory queue and runs duplicate periodic tasks.
- `src/goe/listener/app.py:38`: Registers `"system_service": Provide(get_system_service, sync_to_thread=False)` while `src/goe/listener/controllers/system.py:40` invokes synchronous `system_service.get_db_unique_name()` directly on the ASGI event loop.
- `src/goe/listener/jobs.py:17-43` and `src/goe/listener/services/periodic_tasks.py:22-145`: Defines four `@task` handlers (`run_offload_job`, `system_heartbeat_job`, `sync_schemas_job`, `sync_command_executions_job`) that write double-encoded JSON strings to `goe:listener:metadata:*` keys in `MemoryCache` (`src/goe/listener/utils/cache.py:18`) that no controller or service ever reads.
- `src/goe/listener/controllers/orchestration.py:80-123`: `get_command_execution_log` slurps unbounded local files via synchronous `log_path.read_text()`, fails on `gs://` `OFFLOAD_LOGDIR` paths, does not verify that `command_log_path` resides inside `OFFLOAD_LOGDIR`, and hardcodes `is_file=True` even when the log file is missing (`lines 98-102`). `execute_offload_command` (`lines 104-123`) calls `utils.orchestrate.check_for_running_command(data.owner_table)` (`src/goe/listener/utils/orchestrate.py:13-32`), which raises a `500` `ApplicationError` instead of `409 Conflict` when a lock is held.
- `src/goe/listener/schemas.py:39-312`: Declares mutable `BaseStruct` classes without `frozen=True` or `gc=False`, types `results` as untyped `list[dict[str, Any]]`, and duplicates 95 offload CLI options in `OffloadOptions` (`lines 165-299`).
- `src/goe/listener/security.py:114` and `src/goe/listener/mcp.py:11-22`: Excludes `r"^/mcp"` from `SecurityConfig`, leaving `/mcp` unauthenticated and causing `SecureController` routes invoked via MCP to lack a resolved `Principal`.
- `src/goe/listener/config/logging.py:1-67` and `src/goe/listener/utils/group_by.py:1-13`: Unused legacy Gunicorn logger (`from gunicorn.glogging import Logger as GunciornLogger`) and 5-line `groupby` helper.

### 3. Requirements

- **R1 (Durable Job Models and Oracle/SQLite DDL)**: Define `JobState(StrEnum)` (`PENDING`, `CLAIMED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `DEAD_LETTER`), `JobRecord(FrozenBaseStruct)`, and `NodeHeartbeat(FrozenBaseStruct)` in `src/goe/listener/jobs/models.py`. Provide named SQL queries in `src/goe/listener/jobs/sql/job_queue.sql` and repository migration DDL in `sql/oracle/source/sql/create_offload_repo_24.sql` with a function-based unique index on `CASE WHEN STATUS IN ('PENDING', 'CLAIMED', 'RUNNING') THEN TABLE_KEY END` and SQLite WAL DDL with a partial unique index `WHERE status IN ('PENDING', 'CLAIMED', 'RUNNING')`.
- **R2 (Oracle `SKIP LOCKED` and SQLite WAL Job Stores)**: Implement `OracleJobStore` and `SqliteJobStore` in `src/goe/listener/jobs/store.py`. `OracleJobStore.claim_batch` must execute `SELECT ... FOR UPDATE SKIP LOCKED` and call `cursor.fetchmany(limit)` in Python rather than combining `FETCH FIRST` with `FOR UPDATE` (which raises `ORA-02014`). When the Oracle repository tables are absent or unconfigured, auto-select `SqliteJobStore` at `$OFFLOAD_HOME/run/listener_jobs.sqlite3` in WAL mode.
- **R3 (Lease Heartbeat Renewal and Expired-Lease Reaper)**: Implement `DurableJobWorker` in `src/goe/listener/jobs/worker.py` with a 120-second default lease (`lease_seconds=120`), a 30-second background lease-extension task for active multi-hour offloads (`heartbeat_interval_seconds=30`), an expired-lease reaper that transitions expired `CLAIMED`/`RUNNING` jobs back to `PENDING` (when `attempt < max_attempts`) or `DEAD_LETTER` (when `attempt >= max_attempts`), and durable node heartbeat registration.
- **R4 (`ListenerCache` and `ListenerCacheSink`)**: Implement `ListenerCache` in `src/goe/listener/cache.py` with bounded `OrderedDict` LRU capacity, monotonic TTL, async singleflight deduplication, and prefix invalidation, plus `ListenerCacheSink` implementing `ExecutionSink` to invalidate cached schema, table, and execution entries when `StepFinishedEvent` or `CommandFinishedEvent` is emitted.
- **R5 (Non-Blocking Controllers, `litestar-queues` Removal, and Legacy Cleanup)**: Remove `litestar-queues` from `pyproject.toml` and `src/goe/listener/app.py`, wire `ListenerCache` and `JobStore` into Litestar lifespan and dependency injection, split schema and table routes into `src/goe/listener/controllers/schemas.py` and `src/goe/listener/controllers/tables.py`, enforce `409 Conflict` when a table lock or active job is held, enforce path-contained bounded log reading (`is_file=False` when absent, plus `gs://` support via `GOEDfs`), convert `src/goe/listener/schemas.py` to `FrozenBaseStruct`, and delete `src/goe/listener/jobs.py`, `src/goe/listener/services/periodic_tasks.py`, `src/goe/listener/utils/cache.py`, `src/goe/listener/utils/group_by.py`, and `src/goe/listener/config/logging.py`.
- **R6 (Authenticated MCP Server and Read-Only Diagnostic Tools)**: Remove `r"^/mcp"` from `SecurityConfig.exclude` in `src/goe/listener/security.py`, implement `ConfirmationGate` HMAC token verification in `src/goe/listener/mcp.py` for mutating MCP calls, and register read-only MCP tools `get_connectivity_report`, `get_table_status_report`, `list_offloaded_tables`, `preview_offload_plan`, and `get_job_status`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | `1.1` | `uv run pytest tests/unit/listener/test_job_models.py -v` |
| R2, R3 | `1.2` | `uv run pytest tests/unit/listener/test_job_store_and_worker.py -v` |
| R4, R5 | `1.3` | `uv run pytest tests/unit/listener/test_listener_cache_and_controllers.py -v` |
| R6 | `1.4` | `uv run pytest tests/unit/listener/test_mcp.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/listener/test_job_models.py tests/unit/listener/test_job_store_and_worker.py tests/unit/listener/test_listener_cache_and_controllers.py tests/unit/listener/test_mcp.py -v
uv run ruff format --check src/goe/listener tests/unit/listener
uv run ruff check src/goe/listener tests/unit/listener
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Durable Job Queue, Listener Cache, Non-Blocking Controllers, and MCP
- [ ] 1.1 Define Durable Job Queue Models and Oracle/SQLite DDL ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement Oracle and SQLite Job Stores and Lease-Renewing Worker ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Implement ListenerCache, Replace litestar-queues, and Refactor Controllers ([tasks/1.3.md](tasks/1.3.md))
- [ ] 1.4 Authenticate MCP Endpoints and Expose Read-Only Diagnostic Tools ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `durable_job_queue_listener_cache_and_mcp_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: Use `SELECT ... FOR UPDATE SKIP LOCKED` with cursor `fetchmany(limit)` on Oracle (`GOE_LISTENER_JOBS`) and WAL-mode SQLite (`$OFFLOAD_HOME/run/listener_jobs.sqlite3`) as single-host fallback; enforce one active job per table via function-based/partial unique index; renew 120s leases every 30s; remove `litestar-queues`; authenticate `/mcp` via `ConsoleKeyAuthenticator`.
- **Discoveries**: none yet.
- **Blockers**: `offload_plan_resolution_and_stateless_executor_20261024` (Chapter 10.3) and `execution_context_and_concurrency_safety_20261024` (Chapter 10.1) must complete first.
- **Next exact step**: execute task `1.1` (`durable_job_queue_listener_cache_and_mcp_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/listener/index.md`, `.agents/bundles/knowledge/listener/rest-api.md`, `.agents/bundles/knowledge/listener/worker-and-redis.md`.
