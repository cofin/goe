---
type: Reference
title: Oracle Database Frontend Adapter
description: Driver lifecycle, metadata extraction, SCN snapshots, PL/SQL packages, and row-splitting strategies
tags:
  - reference
  - frontends
  - oracle
  - database
  - sql
---

# Oracle Database Frontend Adapter

The Oracle frontend adapter (`src/goe/offload/oracle/`) provides connectivity, metadata inspection, Flashback SCN snapshot extraction, and row-source splitting for Oracle databases.

## Key Modules

- **`OracleFrontendApi` (`oracle_frontend_api.py`)**: Connection management, session initialization, and DDL extraction.
- **`OracleSourceTable` (`oracle_offload_source_table.py`)**: Data dictionary inspection (`ALL_TABLES`, `ALL_TAB_PARTITIONS`, `DBA_TAB_SUBPARTITIONS`).
- **`OffloadTransportOracleApi` (`oracle_offload_transport_rdbms_api.py`)**: SCN snapshot generation and parallel row splitting.
- **`OracleLiteral` (`oracle_literal.py`)**: Literal formatting (`TO_DATE`, `TO_TIMESTAMP`, `HEXTORAW`).

## Connection Management & Modes

- **Driver**: `python-oracledb` (with cx_Oracle compatibility layer).
- **Client Modes**:
  - **Thin Mode (Default)**: Pure Python networking; zero Oracle Instant Client dependencies.
  - **Thick Mode**: Enables Oracle Instant Client for Oracle Wallet authentication (`USE_ORACLE_WALLET=true`) and mTLS.
- **Automatic Reconnection**: Transparent recovery from transient disconnects (`ORA-02396`, `ORA-03113`, `ORA-03114`, `ORA-03135`).
- **Session Environment**:
  ```sql
  ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS';
  ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF';
  ALTER SESSION SET TIME_ZONE = '00:00';
  ```
- **Telemetry**: Sessions are tagged via `DBMS_APPLICATION_INFO.SET_MODULE('GOE-Offload', '<table_name>')`.

## Row-Source Splitting Strategies

| Strategy | Query Pattern | Best For |
| :--- | :--- | :--- |
| `SPLIT_BY_PARTITION` | `SELECT ... FROM table PARTITION (p_name)` | Partitioned tables |
| `SPLIT_BY_SUBPARTITION` | `SELECT ... FROM table SUBPARTITION (sp_name)` | Composite partitioned tables |
| `SPLIT_BY_EXTENT` | `SELECT ... WHERE ROWID BETWEEN CHARTOROWID(low) AND CHARTOROWID(high)` | Non-partitioned large tables |
| `SPLIT_BY_MOD` | `SELECT ... WHERE MOD(ORA_HASH(col), parallelism) = split_id` | Uniform hash splitting |
| `SPLIT_BY_ID_RANGE` | `SELECT ... WHERE id_col >= lower AND id_col < upper` | Monotonic primary key tables |

## PL/SQL Packages (`OFFLOAD` & `OFFLOAD_REPO`)

- `offload.version`: Validates installed database package build matches the Python binary.
- `offload.get_init_param`: Queries database initialization parameters (block size, character set).
- `offload.offload_rowid_ranges`: Pipelined table function for extent chunk generation.
- `offload_repo.start_command` / `end_command`: Audit logging in repository tables.
