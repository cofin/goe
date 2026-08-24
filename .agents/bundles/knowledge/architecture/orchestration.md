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
