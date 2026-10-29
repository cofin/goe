---
type: Architecture
title: Orchestration Core Engine
description: Detailed design of OrchestrationRunner, ExecutionContext, ExecutionSink, staged OffloadPipeline, table concurrency locking, and step state machines
tags:
  - architecture
  - orchestration
  - runner
  - pipeline
  - locking
  - state-machine
  - opentelemetry
updated_at: "2026-10-28T21:18:00Z"
---

# Orchestration Core Engine

The orchestration engine coordinates data offloading, schema synchronization, and validation workflows across frontend RDBMS and backend cloud platforms using an explicit per-execution context, pluggable telemetry sinks, and a stateless 4-stage pipeline.

## Core Components

### 1. `ExecutionContext` & Pluggable `ExecutionSink` (`src/goe/orchestration/context.py`, `src/goe/orchestration/sinks.py`)
- **`ExecutionContext(BaseStruct)` (`src/goe/orchestration/context.py`)**: Per-execution context object replacing module-level mutable state (`options`, `log_fh`, `suppress_stdout_override`, `ts`). Holds `execution_id`, `command_type`, `options`, `config`, `messages`, `log_fh`, `repo_client`, `sink`, `suppress_stdout_override`, `started_at`, and `extra`, and exposes `ExecutionContext.build(...)`, `.enter()` / `.close()` context management (`bind_execution_context` + `bind_orchestration_context`), and `.child(...)` for nested sub-operations.
- **`ExecutionSink` Protocol & Composite Sinks (`src/goe/orchestration/sinks.py`)**:
  - `StepProgressEvent(FrozenBaseStruct)`: Immutable event payload (`execution_id`, `command_type`, `step_id`, `step_title`, `status`, `timestamp`, `duration_seconds`, `details`, `error_message`).
  - `RepositoryStepSink`: Writes step start/completion rows to `GOE_REPO.COMMAND_EXECUTION_STEP` via `OrchestrationRepoClient`.
  - `OpenTelemetryStepSink`: Emits spans and step duration histograms.
  - `CompositeExecutionSink`: Fans out `on_command_start`, `on_step_start`, `on_step_end`, `on_log_event`, and `on_command_end` to multiple sinks (including `ListenerCacheSink`) in registration order, isolating non-critical sink failures so primary repository persistence is never aborted.
  - `NullExecutionSink`: Zero-overhead no-op implementation for dry-run and unit tests.

### 2. `OrchestrationRunner` (`src/goe/orchestration/orchestration_runner.py`)
`OrchestrationRunner` is the primary controller for all GOE commands:
- **Initialization**: Configures operational context (`ExecutionContext`), loads `OrchestrationConfig`, resolves execution options, and establishes the repository connection via `OrchestrationRepoClient`.
- **Command Registration & Trace Context**: Assigns a unique `ExecutionId` (UUID4), binds `ExecutionId` to OpenTelemetry W3C baggage (`goe.execution.id`) and SQLSpec `CorrelationContext` via `traced_command()` (`goe.command.offload`), and records `COMMAND_OFFLOAD` in `GOE_REPO.COMMAND_EXECUTION` with status `EXECUTING` (including `_trace_id` and `_span_id` inside `COMMAND_PARAMETERS` when OpenTelemetry is enabled).
- **Concurrency Protection**: Obtains an exclusive table lock via `orchestration_lock_for_table()`.
- **Pipeline Execution**: Instantiates `OffloadPipeline` (`src/goe/orchestration/pipeline.py`) to run the 4 stateless stages (`DiscoveryStage`, `BoundaryStage`, `PlanResolutionStage`, `OffloadPlanExecutor`).
- **Finalization & Error Handling**: Records final status (`COMMAND_SUCCESS` or `COMMAND_ERROR`), records `goe.commands.total` and `goe.commands.duration` metrics, emits step summary timings, and releases locks and connections.

### 3. Stateless 4-Stage `OffloadPipeline` (`src/goe/orchestration/models.py`, `src/goe/orchestration/stages/`, `src/goe/orchestration/pipeline.py`)
The legacy monolithic `OffloadOperation`, `execution.py`, and `OffloadSourceData*` hierarchy were replaced by immutable `FrozenBaseStruct` stage artifacts and 4 stateless stages:
- **`DiscoveryStage` (`src/goe/orchestration/stages/discovery.py`)**: Inspects source RDBMS metadata, partition dictionaries, existing backend table state, and stored repository `OffloadMetadata` to produce an immutable `DiscoveryResult(FrozenBaseStruct)`.
- **`BoundaryStage` (`src/goe/orchestration/stages/boundary.py`)**: Computes partition high-water marks (IPA `RANGE` and `LIST`), predicate-based offload (`PBO`) filters, full-table (`RBO` `100:0` / `90:10`) rules, and partition chunks without mutating table objects, producing an immutable `BoundaryResult(FrozenBaseStruct)`.
- **`PlanResolutionStage` (`src/goe/orchestration/stages/plan_resolution.py`)**: Resolves canonical column mappings, RDBMS precision/scale sampling (`sample_rdbms_data_types`), transport method selection, staging format, and verification strategy into an immutable, serializable `OffloadPlan(FrozenBaseStruct)`.
- **`OffloadPlanExecutor` (`src/goe/orchestration/stages/executor.py`)**: Executes target DDL creation, snapshot SCN capture, staging transport (`Spark`, `Dataproc`, `QueryImport`, `DuckDB`), staging validation, cast verification, final load, staging cleanup, metadata persistence, and cross-database row/aggregate verification from the resolved `OffloadPlan`, returning `OffloadExecutionResult(FrozenBaseStruct)`.

### 4. Execution Locking & Process Worker Primitives (`src/goe/platform/locking.py`, `src/goe/platform/worker.py`)
- **`FileOrchestrationLock` (`src/goe/platform/locking.py`)**: Uses `filelock.FileLock` to acquire `$OFFLOAD_HOME/run/orchestration_<owner>_<table_name>.lock` via `orchestration_lock_for_table()` and `orchestration_lock_from_hybrid_metadata()`.
- **Fail-Fast Semantics**: Zero-second timeout ensures that if another process is operating on the same table, `OrchestrationLockTimeout` is thrown immediately to prevent concurrent metadata corruption or conflicting data staging.
- **`LocalProcessWorker`, `LameDuckController`, and `CgroupQuota` (`src/goe/platform/worker.py`)**: Provide cgroup v2 CPU/memory quota reading (`cpu.max`, `memory.max`), graceful lame-duck drain signaling (`SIGTERM` / `SIGINT` with in-flight task tracking), and subprocess execution management.

### 5. Declarative Adapter Registry (`src/goe/offload/registry.py`)
- **`AdapterRegistry` & `ADAPTER_REGISTRY`**: Consolidates all 9 adapter domains (`FRONTEND_API`, `BACKEND_API`, `BACKEND_TABLE`, `SOURCE_TABLE`, `REPOSITORY_CLIENT`, `TRANSPORT`, `TRANSPORT_RDBMS_API`, `STAGING_FILE`, `QUERY_IMPORT_ENCODER`) into a single declarative registry of `AdapterEntry(kind, key, LazyTarget(module, attribute, extra))` structs.
- **Lazy Resolution**: `ADAPTER_REGISTRY.resolve(kind, key)` imports target modules on demand via `ensure_module(target.module, extra=target.extra)` (`src/goe/util/module_loader.py`), while `resolve_dry_run(kind, key)` inspects registered targets without importing third-party driver packages.

### 6. Execution Identity & OpenTelemetry Context Bridge (`src/goe/orchestration/execution_id.py`, `src/goe/observability/context.py`)
- **`ExecutionId`**: `FrozenBaseStruct` wrapping Python `uuid.UUID` with 36-char string and 16-byte `RAW(16)` binary conversions.
- **`bind_execution_context`**: Propagates `ExecutionId` simultaneously into `ContextVar`s, W3C `baggage` (`goe.execution.id`), and SQLSpec `CorrelationContext`, allowing `ExecutionContextSpanProcessor` to stamp `goe.execution.id`, `goe.command.type`, and `goe.step.id` onto all spans.

### 7. Command Step State Machine (`src/goe/orchestration/command_steps.py`, `src/goe/offload/offload_messages.py`)
Discrete transactional steps executed via `OffloadMessages.offload_step()`, wrapped in `traced_step()` (`goe.step.<step_id>`), emitted to `ExecutionContext.sink`, and tracked in `GOE_REPO.COMMAND_EXECUTION_STEP`:
- `STEP_MESSAGES`, `STEP_ANALYZE_DATA_TYPES`, `STEP_FIND_OFFLOAD_DATA`, `STEP_CREATE_TABLE`, `STEP_STAGING_SETUP`, `STEP_STAGING_TRANSPORT`, `STEP_VALIDATE_DATA`, `STEP_VALIDATE_CASTS`, `STEP_FINAL_LOAD`, `STEP_STAGING_CLEANUP`, `STEP_SAVE_METADATA`, `STEP_VERIFY_EXPORTED_DATA`.
