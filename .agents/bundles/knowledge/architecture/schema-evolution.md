---
type: Architecture
title: Schema Evolution & Synchronization
description: Pure-value single-pass schema drift detection and DialectSqlEngine DDL generation via goe.sync
tags:
  - architecture
  - schema-sync
  - evolution
  - ddl
---

# Schema Evolution & Synchronization

The **Schema Sync** package (`src/goe/sync/differ.py`) detects structural drift between source RDBMS tables and target cloud data warehouses in a single pass and emits dialect-aware evolution DDL via `DialectSqlEngine`.

## Domain Models & Service (`src/goe/sync/differ.py`)

- **`SourceColumnSnapshot` & `TargetColumnSnapshot` (`FrozenBaseStruct`)**:
  - Immutable column snapshots (`name`, `data_type`, `nullable`, `precision`, `scale`, `length`, `position`) captured from `OracleCatalogService` / `FrontendCatalogCache` and backend metadata without re-instantiating `OffloadSourceTable`.
- **Change Vector Value Objects (`FrozenBaseStruct`)**:
  - `ColumnAddition(column_name, source_type, target_type, nullable, position)`
  - `TypeWidening(column_name, old_target_type, new_target_type, safe)`
  - `NullabilityRelaxation(column_name)`
  - `PartitionDrop(partition_name, partition_value)`
  - `SchemaDiff(schema_name, table_name, target_schema, target_table, additions, widenings, nullability_relaxations, partition_drops)` with `.has_changes` property.
- **`SchemaSyncService`**:
  - `compute_diff(...)`: Computes `SchemaDiff` in a single pass over `source_columns` and `target_columns` (plus optional dropped partitions when `sync_dropped_partitions=True`).
  - `generate_ddl(diff, dialect=...)`: Delegates DDL construction to `DialectSqlEngine` (`schema_sync_add_column`, `schema_sync_widen_column`, `schema_sync_relax_nullability`, `schema_sync_drop_partition`) across BigQuery, Snowflake, Synapse (`tsql`), Hive, Impala, and Oracle.
  - `apply_diff(diff, execute=..., ddl_executor=...)` & `sync_table(...)`: Generates DDL statements and executes them only when `execute=True`.
  - `run_from_options(options, messages=..., execution_id=..., repo_client=...)`: Entry point invoked by `goe sync` (`src/goe/cli/commands/sync.py`) and `run_schema_sync`.
- **Listener Integration**:
  - `SystemService.preview_schema_drift` (`src/goe/listener/services/system.py`) and `GET /api/system/schemas/{schema_name}/{table_name}/drift/` (`mcp_tool="preview_schema_drift"` in `src/goe/listener/controllers/system.py`) return `SchemaDiff` directly via `SchemaSyncService`.

## Workflow

```
1. Scope Expansion: Parse --include patterns (default *.*) via normalise_schema_sync_options
2. Snapshot Capture: Read SourceColumnSnapshot and TargetColumnSnapshot once per table
3. Single-Pass Diff: SchemaSyncService.compute_diff produces an immutable SchemaDiff
4. Lock Acquisition: Acquire per-table lock via OrchestrationLockInterface when execute=True
5. DDL Generation: DialectSqlEngine renders dialect-specific ALTER TABLE statements
6. Execution / Command File: Apply DDL via ddl_executor (when -x) and record clean SQL to --command-file
```
