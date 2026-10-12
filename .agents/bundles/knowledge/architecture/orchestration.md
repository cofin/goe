---
type: Architecture
title: Orchestration Core Engine
description: Detailed design of OrchestrationRunner, table concurrency locking, execution tracking, and step state machines
tags:
  - architecture
  - orchestration
  - runner
  - locking
  - state-machine
---

# Orchestration Core Engine

The orchestration engine coordinates data offloading, schema synchronization, and validation workflows across frontend RDBMS and backend cloud platforms.

## Core Components

### 1. `OrchestrationRunner` (`src/goe/orchestration/orchestration_runner.py`)
`OrchestrationRunner` is the primary controller for all GOE commands:
- **Initialization**: Configures operational context, loads `OrchestrationConfig`, resolves execution options, and establishes the repository connection via `OrchestrationRepoClient`.
- **Command Registration**: Assigns a unique `ExecutionId` (UUID4) and records `COMMAND_OFFLOAD` in `GOE_REPO.COMMAND_EXECUTION` with status `EXECUTING`.
- **Concurrency Protection**: Obtains an exclusive table lock via `orchestration_lock_for_table()`.
- **Execution**: Instantiates `OffloadSourceTable` and `BackendTable` before invoking `offload_table()` in `goe.py`.
- **Finalization & Error Handling**: Records final status (`COMMAND_SUCCESS` or `COMMAND_ERROR`), emits step summary timings, and releases locks and connections.

### 2. Execution Locking (`src/goe/orchestration/orchestration_lock.py`)
- **`FileLockOrchestrationLock`**: Uses `filelock.FileLock` to acquire `$OFFLOAD_HOME/run/orchestration_<owner>_<table_name>.lock`.
- **Fail-Fast Semantics**: Zero-second timeout ensures that if another process is operating on the same table, `OrchestrationLockTimeout` is thrown immediately to prevent concurrent metadata corruption or conflicting data staging.

### 3. Execution Identity (`src/goe/orchestration/execution_id.py`)
- **`ExecutionId`**: Dataclass wrapping Python `uuid.UUID`.
- Supports bi-directional conversion:
  - String format: `32` hex characters with hyphens (e.g. `1bf72363-03f8-4985-8ed1-728486b4b187`).
  - Binary format: 16-byte raw binary (`RAW(16)`) for compact storage in Oracle repository tables.

### 4. Command Step State Machine (`src/goe/orchestration/command_steps.py`)
Discrete transactional steps tracked in `GOE_REPO.COMMAND_EXECUTION_STEP`:
- `STEP_ANALYZE_DATA_TYPES`: Type analysis and sampling.
- `STEP_FIND_OFFLOAD_DATA`: Partition discovery and boundary calculation.
- `STEP_CREATE_TABLE`: Target table DDL generation and creation.
- `STEP_STAGING_SETUP`: External staging table or bucket preparation.
- `STEP_STAGING_TRANSPORT`: PySpark / Sqoop data extraction to staging files.
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
| [`src/goe/offload/offload_transport.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_transport.py) & [`src/goe/offload/factory/offload_transport_factory.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/factory/offload_transport_factory.py) | `src/goe/offload/transport/{constants,availability,base,spark_thrift,spark_submit,query_import,factory}.py` | Transport constants (`constants.py`), availability checks (`availability.py`), `OffloadTransport` base (`base.py`), Spark Thrift (`spark_thrift.py`), Spark Submit / PySpark generator (`spark_submit.py`), `OffloadTransportQueryImport` (`query_import.py`), and `choose_offload_transport_method` / `offload_transport_factory` (`factory.py`). |

### Architectural Invariants for Decomposed Packages
1. **Definition-Free `as`-Alias Facades**: Each legacy facade module contains only a module docstring and `from <defining_module> import Symbol as Symbol` re-exports for its observed import surface (satisfying Ruff `F401` and Mypy explicit re-export rules without `__all__`).
2. **Acyclic Empty `__init__.py` Files**: `src/goe/orchestration/__init__.py`, `src/goe/report/__init__.py`, `src/goe/offload/source_data/__init__.py`, and `src/goe/offload/transport/__init__.py` contain only the 2-line SPDX header and a module docstring so importing a leaf submodule (e.g. `goe.orchestration.command_steps`) never triggers package-wide circular imports.
3. **Mutable Module State Access**: Mutable globals (`options`, `log_fh`, `suppress_stdout_override`, `ts`) live in `src/goe/orchestration/logging_init.py` and are mutated/read via `logging_init.<attr>` module attribute access in `execution.py` rather than `from ... import` value bindings.

