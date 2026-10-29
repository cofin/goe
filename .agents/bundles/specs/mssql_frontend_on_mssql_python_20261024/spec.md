---
type: Spec
flow_id: mssql_frontend_on_mssql_python_20261024
title: "Chapter 6.4: MSSQL Frontend on MssqlPythonConfig"
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
description: "Migrate the Microsoft SQL Server frontend from pymssql and quoted literal placeholders onto pooled sqlspec MssqlPythonConfig sessions, named SQL catalog queries, and FrontendCatalogCache."
tags:
  - refactor
  - sqlspec
  - mssql
  - caching
parent_prd: prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024
depends_on:
  - oracle_catalog_snapshot_and_frontend_cache_20261024
research:
  - .agents/bundles/specs/prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 6.4: MSSQL Frontend on MssqlPythonConfig

## Specification

### 1. Overview and Goals

`MSSQLFrontendApi` (`src/goe/offload/microsoft/mssql_frontend_api.py`) and `MSSQLSourceTable` (`src/goe/offload/microsoft/mssql_offload_source_table.py`) currently connect through unpooled `pymssql.connect(...)` sessions, open and close raw DBAPI cursors per query, embed `%s` placeholders inside single-quoted SQL string literals (`WHERE schema_name = '%s'`), and interpolate unquoted schema and table identifiers into `SP_SPACEUSED`, `SP_AUTOSTATS`, and `DBCC SHOW_STATISTICS`. This chapter:

1. Moves every SQL Server catalog and introspection query into `src/goe/offload/microsoft/sql/mssql_catalog.sql` loaded via `sqlspec.loader.SQLFileLoader` with `qmark` (`?`) bind parameters.
2. Replaces `pymssql` session setup and raw cursor management in `MSSQLFrontendApi` and `MSSQLSourceTable` with `sqlspec.adapters.mssql_python.MssqlPythonConfig` (`mssql-python`), integrating `FrontendCatalogCache` for table and column metadata snapshots.
3. Cleans up `OffloadTransportMSSQLApi` (`src/goe/offload/microsoft/mssql_offload_transport_rdbms_api.py`), removes obsolete Sqoop helper methods, updates `MSSQLColumn` (`src/goe/offload/microsoft/mssql_column.py`) to PEP 585/604 typing, and replaces `pymssql` with `mssql-python` in `pyproject.toml`.

### 2. Code Analysis Summary

- `src/goe/offload/microsoft/mssql_frontend_api.py:15, 40-64`: imports `pymssql` at module top level and calls `pymssql.connect(server=..., user=..., password=..., database=..., port=..., appname=..., conn_properties="")` inside `setup_mssql_session()`.
- `src/goe/offload/microsoft/mssql_frontend_api.py:155-158`: `format_query_parameter()` returns `"%s"`, matching `pymssql` format style rather than `qmark` (`?`).
- `src/goe/offload/microsoft/mssql_frontend_api.py:173-196, 240-262`: `get_columns()` and `get_primary_key_column_names()` inline multi-line SQL strings with `%s` binds.
- `src/goe/offload/microsoft/mssql_frontend_api.py:295-298`: `get_table_size()` interpolates `f'SP_SPACEUSED "{schema}.{table_name}"'` while also passing `query_params=(schema, table_name)` into a statement with zero placeholders.
- `src/goe/offload/microsoft/mssql_frontend_api.py:324-345, 353-364`: `schema_exists()`, `table_exists()`, and `view_exists()` write `WHERE schema_name = '%s'` and `AND table_schema = '%s' AND table_name = '%s'` with literal single quotes around `%s`, causing bound parameters to fail substitution or compare against the literal string `'%s'`.
- `src/goe/offload/microsoft/mssql_offload_source_table.py:513-550`: `_get_table_details()` runs an inline `WITH partitions AS (...)` CTE against `sys.tables`, `sys.partitions`, and `sys.schemas` using `%s` binds instead of a named catalog query or `FrontendCatalogCache`.
- `src/goe/offload/microsoft/mssql_offload_source_table.py:554-583`: `_get_hash_bucket_candidate()` executes `SP_AUTOSTATS` and `DBCC SHOW_STATISTICS` per statistics object instead of reading `sys.dm_db_stats_properties` / `sys.stats` set-based catalog metadata.
- `src/goe/offload/microsoft/mssql_offload_transport_rdbms_api.py:155-177`: retains four dead `sqoop_rdbms_specific_*` methods removed by the Sqoop retirement in Master PRD 5.
- `pyproject.toml:86-89, 111`: defines `sql_server = ["pymssql"]` and includes `"pymssql"` in the `all` extra.
- `.venv/lib/python3.14/site-packages/sqlspec/adapters/mssql_python/config.py:27-148`: `MssqlPythonConfig(connection_config=MssqlPythonPoolParams(...), observability_config=...)` provides pooled `MssqlPythonDriver` sessions (`provide_session()`) using `qmark` (`?`) parameters.

### 3. Requirements

- R1. `src/goe/offload/microsoft/sql/mssql_catalog.sql` defines named queries (`fetch_server_version`, `check_schema_exists`, `check_table_exists`, `check_view_exists`, `fetch_table_columns`, `fetch_primary_key_columns`, `fetch_table_details`, `fetch_table_size_bytes`, `fetch_hash_bucket_candidate`) using `?` bind placeholders and `sys.dm_db_partition_stats` / `sys.stats` catalog views instead of unparameterized `SP_SPACEUSED` and `DBCC SHOW_STATISTICS` calls.
- R2. `MSSQLFrontendApi` uses `MssqlPythonConfig` (lazily importing `mssql_python` via `goe.util.module_loader`) and checks out drivers through `provide_session()`, sharing statement caching and `sqlspec_observability_config()`.
- R3. `MSSQLFrontendApi.schema_exists`, `table_exists`, `view_exists`, `get_columns`, `get_primary_key_column_names`, and `get_table_size` bind parameters with `?` without surrounding single quotes, fixing the quoted `'%s'` defect.
- R4. `MSSQLSourceTable` resolves table existence, row count, partitioning flag, size in bytes, column metadata, and hash bucket candidate through `FrontendCatalogCache` and the named `mssql_catalog.sql` queries.
- R5. `OffloadTransportMSSQLApi` removes the four `sqoop_rdbms_specific_*` methods, `MSSQLColumn` uses PEP 585/604 type annotations, and `pyproject.toml` replaces `pymssql` with `mssql-python` in the `sql_server` (and `mssql` alias) and `all` extras.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/offload/microsoft/test_mssql_frontend_api.py` named SQL loading and placeholder assertions |
| R2 | 1.1 | `tests/unit/offload/microsoft/test_mssql_frontend_api.py` `MssqlPythonConfig` session checkout tests |
| R3 | 1.1 | `tests/unit/offload/microsoft/test_mssql_frontend_api.py` `test_exists_queries_use_qmark_binds_without_quoted_percent_s` |
| R4 | 1.1, 1.2 | `tests/unit/offload/microsoft/test_mssql_source_table.py` catalog snapshot and cache hit tests |
| R5 | 1.2 | `tests/unit/offload/microsoft/test_mssql_source_table.py` transport API and column typing tests |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/microsoft -v
uv run ruff format --check src/goe/offload/microsoft tests/unit/offload/microsoft
uv run ruff check src/goe/offload/microsoft tests/unit/offload/microsoft
uv run mypy src/goe
uv run python tools/verify_architecture.py
git grep -n "pymssql" -- src tests pyproject.toml
```

The `git grep` command must print nothing.

## Implementation Plan

### Phase 1: SQLSpec MssqlPythonConfig Cutover and Catalog Cache Integration
- [ ] 1.1 Migrate MSSQLFrontendApi and MSSQLSourceTable onto MssqlPythonConfig, named SQL, and FrontendCatalogCache ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Clean up OffloadTransportMSSQLApi, modernize MSSQLColumn typing, and switch pyproject.toml extras to mssql-python ([tasks/1.2.md](tasks/1.2.md))

## Continuity Snapshot

- **Flow / lifecycle**: `mssql_frontend_on_mssql_python_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: use `sqlspec.adapters.mssql_python.MssqlPythonConfig` with `qmark` (`?`) parameters; replace `SP_SPACEUSED` and `SP_AUTOSTATS` / `DBCC SHOW_STATISTICS` procedural calls with set-based `sys.dm_db_partition_stats` and `sys.stats` catalog queries in `mssql_catalog.sql`; cache MSSQL table snapshots in `FrontendCatalogCache` from Chapter 6.3.
- **Discoveries**: none yet.
- **Blockers**: Chapter 6.3 (`oracle_catalog_snapshot_and_frontend_cache_20261024`) must complete first so `FrontendCatalogCache` is available.
- **Next exact step**: execute task `1.1` (`mssql_frontend_on_mssql_python_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/standards/database-and-sql.md`, `.agents/bundles/knowledge/operations/observability.md`.
