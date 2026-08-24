---
type: Guide
title: Product Guidelines & Invariants
description: Operational rules, safety constraints, concurrency controls, and design invariants for GOE
tags:
  - guide
  - product
  - guidelines
  - safety
  - invariants
---

# Product Guidelines & Invariants

This document defines non-negotiable architectural invariants and operational safety guidelines for all GOE components.

## Core Architectural Invariants

### 1. Non-Invasive RDBMS Operations
- GOE must never acquire exclusive DDL locks or modify table structures on production RDBMS source application schemas during normal data offload.
- Offload reads must be executed using consistent read snapshots (`FLASHBACK ANY TABLE` / System Change Number `SCN`) to prevent phantom reads without blocking OLTP transactions.
- DML and DDL operations are strictly restricted to the administrative repository schemas (`goe_adm`, `goe_repo`).

### 2. Concurrency & Locking Controls
- Every offload, schema synchronization, and validation operation must acquire a table-level execution lock (`OrchestrationLockInterface` via `filelock` in `$OFFLOAD_HOME/run/`).
- Multiple concurrent operations on the same source table must fail fast (`OrchestrationLockTimeout`) rather than executing concurrently and corrupting staging metadata.

### 3. Data Integrity & Lossless Transformation
- Type mapping must use the canonical intermediate type system (`column_metadata.py`).
- Implicit lossy downcasting (e.g. `NUMBER(38)` to 32-bit `INT`, or unscaled `DECIMAL` to single-precision float) is strictly forbidden.
- Columns with ambiguous precision or floating scale must be sampled (`--data-sample-pct`) to compute exact integer/decimal boundaries prior to target table creation.

### 4. Staging Isolation & Atomic Activation
- Data is always extracted to isolated cloud staging storage (`part*` files in `OFFLOAD_FS_CONTAINER`) before ingestion into the target table.
- Target tables are updated atomically via `INSERT ... SELECT` / `COPY INTO` operations.
- Intermediate staging tables and storage files are pruned automatically upon successful operation completion unless explicitly overridden by `--preserve-load-table`.

### 5. Repository Auditability & Traceability
- Every execution receives a globally unique `ExecutionId` (UUID4).
- All command parameters, granular step durations, chunk statistics (rows, source bytes, transport bytes, target bytes), and final exit statuses are recorded in `GOE_REPO.COMMAND_EXECUTION` and `COMMAND_EXECUTION_STEP`.
