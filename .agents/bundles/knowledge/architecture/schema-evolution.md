---
type: Architecture
title: Schema Evolution & Synchronization
description: Structural drift detection, change vector resolution, and target DDL synchronization via schema_sync
tags:
  - architecture
  - schema-sync
  - evolution
  - ddl
---

# Schema Evolution & Synchronization

The **Schema Sync** module (`src/goe/schema_sync/`) detects and resolves structural drift between source RDBMS tables and target backend data warehouses.

## Components

- **`SchemaSyncAnalyzer` (`schema_sync_analyzer.py`)**:
  - Compares column structures between the source RDBMS catalog and backend data warehouse metadata.
  - Expands scope patterns (e.g. `*.*`, `SCHEMA.*`, `*.TABLE`) against `GOE_REPO.OFFLOAD_OBJECTS`.
  - Analyzes `LAST_DDL_TIME` and detects column additions, alterations, renames, and drop operations.
- **`SchemaSyncProcessor` (`schema_sync_processor.py`)**:
  - Coordinates execution of change steps across affected tables.
  - Acquires table-level execution locks (`orchestration_lock_for_table`) before making modifications.
- **`AddBackendColumn` (`steps/add_backend_column.py`)**:
  - Generates and executes `ALTER TABLE <backend_table> ADD COLUMN <col> <type>`.
  - Updates repository metadata with new column specifications.
- **`AddOracleColumn` (`steps/add_oracle_column.py`)**:
  - Updates Oracle access views and hybrid query definitions.

## Workflow

```
1. Scope Expansion: Expand --include wildcard patterns
2. Diff Detection: Compare source catalog vs GOE_REPO metadata
3. Lock Acquisition: Acquire exclusive table lock in $OFFLOAD_HOME/run/
4. DDL Generation: Generate ALTER TABLE statements for target DW
5. DDL Execution: Apply changes (or write to --command-file)
6. Repository Sync: Update GOE_REPO column metadata
7. Lock Release: Release table lock
```
