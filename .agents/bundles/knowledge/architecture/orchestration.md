---
type: Architecture
title: Orchestration Core Engine
description: Detailed design of OrchestrationRunner, table concurrency locking, ExecutionId-to-W3C trace bridge, and step state machines
tags:
  - architecture
  - orchestration
  - runner
  - locking
  - state-machine
  - opentelemetry
---

# Orchestration Core Engine

The orchestration engine coordinates data offloading, schema synchronization, and validation workflows across frontend RDBMS and backend cloud platforms.

## Core Components

### 1. `OrchestrationRunner` (`src/goe/orchestration/orchestration_runner.py`)
`OrchestrationRunner` is the primary controller for all GOE commands:
- **Initialization**: Configures operational context, loads `OrchestrationConfig`, resolves execution options, and establishes the repository connection via `OrchestrationRepoClient`.
- **Command Registration & Trace Context**: Assigns a unique `ExecutionId` (UUID4), binds `ExecutionId` to OpenTelemetry W3C baggage (`goe.execution.id`) and SQLSpec `CorrelationContext` via `traced_command()` (`goe.command.offload`), and records `COMMAND_OFFLOAD` in `GOE_REPO.COMMAND_EXECUTION` with status `EXECUTING` (including `_trace_id` and `_span_id` inside `COMMAND_PARAMETERS` when OpenTelemetry is enabled).
- **Concurrency Protection**: Obtains an exclusive table lock via `orchestration_lock_for_table()`.
- **Execution**: Instantiates `OffloadSourceTable` and `BackendTable` before invoking `offload_table()`.
- **Finalization & Error Handling**: Records final status (`COMMAND_SUCCESS` or `COMMAND_ERROR`), records `goe.commands.total` and `goe.commands.duration` metrics, emits step summary timings, and releases locks and connections.

### 2. Execution Locking & Process Worker Primitives (`src/goe/platform/locking.py`, `src/goe/platform/worker.py`)
- **`FileOrchestrationLock` (`src/goe/platform/locking.py`)**: Uses `filelock.FileLock` to acquire `$OFFLOAD_HOME/run/orchestration_<owner>_<table_name>.lock` via `orchestration_lock_for_table()` and `orchestration_lock_from_hybrid_metadata()`.
- **Fail-Fast Semantics**: Zero-second timeout ensures that if another process is operating on the same table, `OrchestrationLockTimeout` is thrown immediately to prevent concurrent metadata corruption or conflicting data staging.
- **`LocalProcessWorker`, `LameDuckController`, and `CgroupQuota` (`src/goe/platform/worker.py`)**: Provide cgroup v2 CPU/memory quota reading (`cpu.max`, `memory.max`), graceful lame-duck drain signaling (`SIGTERM` / `SIGINT` with in-flight task tracking), and subprocess execution management.

### 3. Declarative Adapter Registry (`src/goe/offload/registry.py`)
- **`AdapterRegistry` & `ADAPTER_REGISTRY`**: Consolidates all 9 adapter domains (`FRONTEND_API`, `BACKEND_API`, `BACKEND_TABLE`, `SOURCE_TABLE`, `REPOSITORY_CLIENT`, `TRANSPORT`, `TRANSPORT_RDBMS_API`, `STAGING_FILE`, `QUERY_IMPORT_ENCODER`) into a single declarative registry of `AdapterEntry(kind, key, LazyTarget(module, attribute, extra))` structs, replacing the retired `src/goe/offload/factory/*` and `src/goe/persistence/factory/*` modules.
- **Lazy Resolution**: `ADAPTER_REGISTRY.resolve(kind, key)` imports target modules on demand via `ensure_module(target.module, extra=target.extra)` (`src/goe/util/module_loader.py`), while `resolve_dry_run(kind, key)` inspects registered targets without importing third-party driver packages.

### 4. Execution Identity & OpenTelemetry Context Bridge (`src/goe/orchestration/execution_id.py`, `src/goe/observability/context.py`)
- **`ExecutionId`**: `FrozenBaseStruct` wrapping Python `uuid.UUID`.
- Supports bi-directional conversion:
  - String format: `36` characters with hyphens (e.g. `1bf72363-03f8-4985-8ed1-728486b4b187`).
  - Binary format: 16-byte raw binary (`RAW(16)`) for compact storage in Oracle repository tables.
- **`bind_execution_context`**: Propagates `ExecutionId` simultaneously into `ContextVar`s, W3C `baggage` (`goe.execution.id`), and SQLSpec `CorrelationContext`, allowing `ExecutionContextSpanProcessor` to stamp `goe.execution.id`, `goe.command.type`, and `goe.step.id` onto all spans.

### 4. Command Step State Machine (`src/goe/orchestration/command_steps.py`, `src/goe/offload/offload_messages.py`)
Discrete transactional steps executed via `OffloadMessages.offload_step()`, wrapped in `traced_step()` (`goe.step.<step_id>`) and tracked in `GOE_REPO.COMMAND_EXECUTION_STEP` (with `_trace_id` and `_span_id` in `STEP_DETAILS` when OpenTelemetry is enabled):
- `STEP_ANALYZE_DATA_TYPES`: Type analysis and sampling.
- `STEP_FIND_OFFLOAD_DATA`: Partition discovery and boundary calculation.
- `STEP_CREATE_TABLE`: Target table DDL generation and creation.
- `STEP_STAGING_SETUP`: External staging table or bucket preparation.
- `STEP_STAGING_TRANSPORT`: Data extraction to staging files (Spark, Dataproc, Query Import, DuckDB).
- `STEP_VALIDATE_DATA`: Row count and schema validation on staging files.
- `STEP_VALIDATE_CASTS`: Type conversion safety verification.
- `STEP_FINAL_LOAD`: Data ingestion from staging to target table.
- `STEP_STAGING_CLEANUP`: Pruning transient staging files and tables.
- `STEP_SAVE_METADATA`: Storing offload state and high-water marks in repository.
- `STEP_VERIFY_EXPORTED_DATA`: Cross-database row count and aggregate validation.

## Decomposed Domain Packages & Definition-Free Facades

Core orchestration, status reporting, source data discovery, and transport execution are organized into four cohesive packages with definition-free backward-compatible re-export facades:

| Legacy Facade Module | Decomposed Package & Modules | Key Responsibilities |
| :--- | :--- | :--- |
| [`src/goe/goe.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/goe.py) | `src/goe/orchestration/{constants,logging_init,operation,execution}.py` | Log Level constants (`normal`, `verbose`, `vverbose`), top-level log/version initialization (`logging_init.py`), `OffloadOperation` normalization and step state machine (`operation.py`), and `offload_table`/`run_offload` execution (`execution.py`). |
| [`src/goe/offload/offload_status_report.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_status_report.py) | `src/goe/report/{models,demo_data,renderers,collector}.py` | Report dataclasses (`models.py`), deterministic demo dataset (`demo_data.py`), CSV/TEXT/JSON/RAW/HTML formatting (`renderers.py`), and `OffloadStatusReport` / `offload_status_report_run` collection (`collector.py`). |
| [`src/goe/offload/offload_source_data.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_source_data.py) | `src/goe/offload/source_data/{base,predicate,full,ipa_range,ipa_list,factory}.py` | `OffloadSourceDataInterface` & `OffloadSourcePartition(s)` (`base.py`), PBO (`predicate.py`), RBO full/partitioned (`full.py`), IPA `RANGE` (`ipa_range.py`), IPA `LIST` (`ipa_list.py`), and `OffloadSourceData` factory (`factory.py`). |
| [`src/goe/offload/offload_transport.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_transport.py) & [`src/goe/offload/factory/offload_transport_factory.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/factory/offload_transport_factory.py) | `src/goe/offload/transport/{constants,availability,base,spark_thrift,spark_submit,query_import,duckdb_constants,duckdb_availability,duckdb_engine,duckdb_transport,factory}.py` | Transport constants (`constants.py`), availability checks (`availability.py`, `duckdb_availability.py`), `OffloadTransport` base (`base.py`), Spark Thrift (`spark_thrift.py`), Spark Submit / PySpark generator (`spark_submit.py`), `OffloadTransportQueryImport` (`query_import.py`), `OffloadTransportDuckDB` (`duckdb_transport.py`), and `choose_offload_transport_method` / `offload_transport_factory` (`factory.py`). |

### Architectural Invariants for Decomposed Packages
1. **Definition-Free `as`-Alias Facades**: Each legacy facade module contains only a module docstring and `from <defining_module> import Symbol as Symbol` re-exports for its observed import surface (satisfying Ruff `F401` and Mypy explicit re-export rules without `__all__`).
2. **Acyclic Empty `__init__.py` Files**: `src/goe/orchestration/__init__.py`, `src/goe/report/__init__.py`, `src/goe/offload/source_data/__init__.py`, and `src/goe/offload/transport/__init__.py` contain only the 2-line SPDX header and a module docstring so importing a leaf submodule (e.g. `goe.orchestration.command_steps`) never triggers package-wide circular imports.
3. **Mutable Module State Access**: Mutable globals (`options`, `log_fh`, `suppress_stdout_override`, `ts`) live in `src/goe/orchestration/logging_init.py` and are mutated/read via `logging_init.<attr>` module attribute access in `execution.py` rather than `from ... import` value bindings.
