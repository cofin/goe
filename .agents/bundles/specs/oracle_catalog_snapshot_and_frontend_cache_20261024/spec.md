---
type: Spec
flow_id: oracle_catalog_snapshot_and_frontend_cache_20261024
title: "Chapter 6.3: Oracle Catalog Snapshot and Frontend Cache"
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
description: "Consolidate scattered Oracle data dictionary queries into a frozen OracleTableSnapshot loaded by OracleCatalogService, cache snapshots and session context in FrontendCatalogCache, and refactor OracleFrontendApi and OracleSourceTable to consume cached snapshots."
tags: [refactor, oracle, caching, sqlspec]
parent_prd: prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024
depends_on: [offload_metadata_and_repository_service_20261024]
research:
  - .agents/bundles/specs/prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 6.3: Oracle Catalog Snapshot and Frontend Cache

## Specification

### 1. Overview and Goals

Constructing an `OracleSourceTable` (`src/goe/offload/oracle/oracle_offload_source_table.py`) and querying table metadata through `OracleFrontendApi` (`src/goe/offload/oracle/oracle_frontend_api.py`) currently triggers 22 to 35 separate Oracle data dictionary round trips per table. Worse, `_get_partitions` (`oracle_offload_source_table.py:1158-1208`) joins `dba_tab_partitions` directly to `dba_tab_subpartitions`, transferring the partition `LONG` `high_value` column $P \times S$ times across the network, and Listener introspection (`OracleRepositoryService` / `SystemService`) previously constructed throwaway `OracleFrontendApi` and `OffloadSourceTable` objects without caching or closing them.

This chapter consolidates all Oracle catalog discovery into `src/goe/offload/oracle/sql/oracle_catalog.sql` and `src/goe/offload/oracle/catalog.py` (`OracleCatalogService` producing immutable `OracleTableSnapshot` and `OracleSessionContext` structs), caches them in `src/goe/offload/frontend_cache.py` (`FrontendCatalogCache`), and refactors `OracleFrontendApi` and `OracleSourceTable` to consume `OracleTableSnapshot` without issuing ad-hoc catalog queries.

Goals:

1. Define `OracleTableSnapshot`, `OracleColumnMeta`, `OraclePartitionMeta`, `OracleSubpartitionMeta`, `OracleConstraintMeta`, `OracleIndexMeta`, `OracleStorageStats`, `OracleSessionContext`, and `OracleCatalogService` in `src/goe/offload/oracle/catalog.py`, backed by consolidated named SQL in `src/goe/offload/oracle/sql/oracle_catalog.sql`.
2. Parse Oracle partition and subpartition `HIGH_VALUE` `LONG` literals once at snapshot hydration (without $P \times S$ cartesian duplication) and decode `DBA_TAB_COL_STATISTICS` `LOW_VALUE`/`HIGH_VALUE` `RAW` bytes in pure Python.
3. Implement `FrontendCatalogCache` in `src/goe/offload/frontend_cache.py` with `OracleSessionContext` cached per pool and `(owner, table)` snapshots validated by a 30-second monotonic TTL and `MAX(LAST_DDL_TIME)` from `ALL_OBJECTS` (or pinned to an execution `snapshot_scn`), with deterministic invalidation on DDL.
4. Refactor `src/goe/offload/oracle/oracle_frontend_api.py` to delegate catalog reads to `OracleCatalogService` and `FrontendCatalogCache` and route SQL execution through `OracleDatabaseRegistry`.
5. Refactor `src/goe/offload/oracle/oracle_offload_source_table.py` (with `src/goe/offload/oracle/oracle_source_table.py` and `src/goe/offload/oracle/oracle_partition.py`) to consume `OracleTableSnapshot` without issuing ad-hoc catalog queries, and use `OracleSyncDriver.select_to_arrow` for bounded `SAMPLE BLOCK` column precision/scale sampling.

### 2. Code Analysis Summary

- `src/goe/offload/oracle/oracle_frontend_api.py:140-453, 871-920` issues separate queries for `get_columns`, `get_partition_column_names`, `get_subpartition_column_names`, `get_primary_key_column_names`, `get_table_default_parallelism`, `get_table_size`, `_is_iot`, `schema_exists`, `table_exists`, `view_exists`, and `get_session_option("compatible")`.
- `src/goe/offload/oracle/oracle_offload_source_table.py`:
  - `__init__` (`:209-219`) runs sequential queries for `_get_db_version`, `_get_db_block_size` (`v$parameter` via `offload.get_init_param`), `_get_table_details` (`:974-1005`), `_get_column_details`, `_get_columns_with_partition_info`, `_is_compression_enabled` (`:1340-1374`), and `_get_table_size`.
  - `_get_table_stats` (`:1006-1104`) runs 3 separate queries against `all_tab_statistics` and `all_tab_col_statistics`.
  - `_get_hash_bucket_candidate` (`:1106-1129`) re-queries `all_tables` and `all_tab_cols` when the NDV and null counts are already in column statistics.
  - `_get_partitions` (`:1131-1243`) joins `dba_tab_partitions` with `dba_tab_subpartitions`, duplicating `tp.high_value` (`LONG`) across every subpartition row.
  - `_get_subpartitions` (`:1245-1338`) re-queries `dba_tab_subpartitions` and `dba_segments`.
  - `_get_column_low_high_values` (`:1402-1460`) runs per-column `UTL_RAW.CAST_TO_*` or `offload.get_column_low_high_dates` round trips against `all_tab_cols`.

### 3. Requirements

Functional:

- **R1** `src/goe/offload/oracle/sql/oracle_catalog.sql` and `src/goe/offload/oracle/catalog.py` define `OracleSessionContext`, `OracleStorageStats`, `OracleColumnMeta`, `OracleConstraintMeta`, `OracleIndexMeta`, `OracleSubpartitionMeta`, `OraclePartitionMeta`, `OracleTableSnapshot`, and `OracleCatalogService`.
- **R2** `OracleCatalogService` loads table/view header, segment bytes, column metadata (including partition/subpartition key positions, optimizer NDV/nulls/avg_col_len, and decoded `LOW_VALUE`/`HIGH_VALUE` `RAW` statistics), constraints, indexes, partitions, and subpartitions without cartesian `LONG` `high_value` duplication, and parses partition `HIGH_VALUE` literals once at snapshot hydration.
- **R3** `src/goe/offload/frontend_cache.py` implements `FrontendCatalogCache` caching `OracleSessionContext` per pool DSN and `OracleTableSnapshot` per `(dsn, owner, table)` with a 30-second TTL, `MAX(LAST_DDL_TIME)` validation from `ALL_OBJECTS`, optional execution `snapshot_scn` pinning, and explicit invalidation on DDL.
- **R4** `src/goe/offload/oracle/oracle_frontend_api.py` delegates catalog and session-context lookups to `OracleCatalogService` and `FrontendCatalogCache`, invalidates the cache on DDL execution, and routes SQL and PL/SQL execution through `OracleDatabaseRegistry`.
- **R5** `src/goe/offload/oracle/oracle_offload_source_table.py`, `src/goe/offload/oracle/oracle_source_table.py`, and `src/goe/offload/oracle/oracle_partition.py` hydrate table, column, partition, subpartition, compression, hash-bucket candidate, and column low/high stats directly from `OracleTableSnapshot` with zero ad-hoc catalog SQL queries, and sample unknown number precision/scale via `driver.select_to_arrow(..., return_format="batches", batch_size=10_000)`.
- **R6** `OracleRepositoryService` (`src/goe/persistence/oracle/oracle_repository.py`) exposes `get_table_columns`, `get_table_partitions`, and `get_table_subpartitions` backed by `FrontendCatalogCache` and `OracleCatalogService` so Listener introspection leaks zero connections.

Non-functional:

- **R7** All snapshot models inherit from `FrozenBaseStruct` (`frozen=True, gc=False`), using `tuple` collections so cached snapshots cannot be mutated by callers.

Risks and mitigations:

- Non-literal partition `HIGH_VALUE` expressions in Oracle `DBA_TAB_PARTITIONS`: parsed in Python for standard `TO_DATE`, `TIMESTAMP`, `MAXVALUE`, `DEFAULT`, numeric, and string literals, with a single batched PL/SQL fallback on `OracleCatalogService` when non-standard expressions occur.
- Stale catalog entries after GOE creates or alters hybrid views/tables: `OracleFrontendApi._execute_ddl_or_dml` calls `FrontendCatalogCache.invalidate_table` / `invalidate_schema`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| --- | --- | --- |
| R1, R2, R7 | 1.1 | `tests/unit/offload/oracle/test_catalog.py` |
| R3, R6 | 1.2 | `tests/unit/offload/test_frontend_cache.py` |
| R4 | 1.3 | `tests/unit/offload/oracle/test_oracle_frontend_api.py`; `tests/unit/offload/test_oracle_frontend_metadata.py` |
| R5 | 1.4 | `tests/unit/offload/oracle/test_oracle_source_table.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/oracle/test_catalog.py tests/unit/offload/test_frontend_cache.py tests/unit/offload/oracle/test_oracle_frontend_api.py tests/unit/offload/oracle/test_oracle_source_table.py tests/unit/offload/test_oracle_frontend_metadata.py -q
uv run pytest tests/unit -q
uv run ruff format --check src/goe tests/unit
uv run ruff check src/goe tests/unit
uv run mypy src/goe
uv run python tools/verify_architecture.py
make test-integration-oracle
```

## Implementation Plan

### Phase 1: Catalog Snapshot and Cache

- [ ] 1.1 Add OracleCatalogService and frozen snapshot models in src/goe/offload/oracle/catalog.py ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement FrontendCatalogCache with pool session context and LAST_DDL_TIME validation ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: Frontend API and Source Table Refactoring

- [ ] 1.3 Refactor OracleFrontendApi to delegate catalog reads to OracleCatalogService and FrontendCatalogCache ([tasks/1.3.md](tasks/1.3.md))
- [ ] 1.4 Refactor OracleSourceTable and OraclePartition to consume OracleTableSnapshot ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `oracle_catalog_snapshot_and_frontend_cache_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `OracleTableSnapshot` and its child structs are immutable `FrozenBaseStruct` types; partition and subpartition `HIGH_VALUE` literals are parsed once during snapshot construction; `FrontendCatalogCache` caches `OracleSessionContext` per pool and validates `(owner, table)` snapshots using a 30s TTL and `ALL_OBJECTS.LAST_DDL_TIME`.
- **Discoveries**: none yet.
- **Blockers**: Chapter 6.2 (`offload_metadata_and_repository_service_20261024`) must complete first.
- **Next exact step**: execute task `1.1` (`oracle_catalog_snapshot_and_frontend_cache_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/frontends/oracle.md`, `.agents/bundles/knowledge/standards/database-and-sql.md`.
