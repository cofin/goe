---
type: Spec
flow_id: snowflake_synapse_hadoop_backend_alignment_20261024
title: "Chapter 9.4: Snowflake, Synapse, and Hadoop Backend Alignment"
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
description: "Align Snowflake, Azure Synapse, Hive, Impala, and Spark Thrift backend adapters onto BackendCapabilities, CachedBackendCatalog, DialectSqlEngine, TypeMappingRegistry, StagedLoadInsertStrategy, and sqlspec.adapters.mssql."
tags: [refactor, backends, snowflake, synapse, hadoop]
parent_prd: prd_09_composable_backends_and_direct_bigquery_ingestion_20261024
depends_on:
  - bigquery_ingest_strategies_20261024
research:
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/duckdb2-arrow-and-storage-dataplane.md
---

# Chapter 9.4: Snowflake, Synapse, and Hadoop Backend Alignment

## Specification

### 1. Overview and Goals

Chapters 9.1 through 9.3 establish the frozen `ColumnSpec` and `TypeMappingRegistry` (`CanonicalTypeRegistry`), `BackendCapabilities(FrozenBaseStruct)`, `CachedBackendCatalog`, `DialectSqlEngine`, and `StagedLoadInsertStrategy`, and migrate BigQuery onto the composable backend architecture. This chapter completes Master PRD 9 by aligning all retained secondary backends onto those same protocols while preserving every existing target capability:

1. **Snowflake (`src/goe/offload/snowflake/`)**: Refactor `BackendSnowflakeApi` and `BackendSnowflakeTable` to expose static `SNOWFLAKE_CAPABILITIES: BackendCapabilities`, read and invalidate table/schema metadata through `CachedBackendCatalog` (including batch `INFORMATION_SCHEMA.TABLES` and `INFORMATION_SCHEMA.COLUMNS` dataset warming), generate SQL and DDL through `DialectSqlEngine("snowflake")`, map types through `TypeMappingRegistry` (`"snowflake"`), and execute final loads (`COPY INTO` or staged `INSERT INTO ... SELECT`) via `StagedLoadInsertStrategy`.
2. **Azure Synapse (`src/goe/offload/microsoft/synapse_*.py`)**: Refactor `BackendSynapseApi` and `BackendSynapseTable` onto `sqlspec.adapters.mssql` (`MssqlPythonConfig` / `mssql-python`, replacing raw `pyodbc` connection setup and cursor plumbing), `SYNAPSE_CAPABILITIES: BackendCapabilities`, `CachedBackendCatalog`, `DialectSqlEngine("tsql")`, `TypeMappingRegistry` (`"synapse"`), and `StagedLoadInsertStrategy` (preserving PolyBase external tables, `COPY INTO`, and `CREATE TABLE AS SELECT` / `INSERT INTO` load paths plus column statistics initialization).
3. **Hadoop and Spark Thrift (`src/goe/offload/hadoop/` and `src/goe/offload/spark/`)**: Refactor `BackendHadoopApi`, `BackendHadoopTable`, `BackendHiveApi`, `BackendHiveTable`, `BackendImpalaApi`, `BackendImpalaTable`, and the Spark / Spark Thrift backend adapters onto `HIVE_CAPABILITIES`, `IMPALA_CAPABILITIES`, and `SPARK_CAPABILITIES`, `CachedBackendCatalog`, `DialectSqlEngine("hive")` / `DialectSqlEngine("spark")`, `TypeMappingRegistry` (`"hive"`, `"impala"`, `"spark"`), and `StagedLoadInsertStrategy` (`LOAD DATA INPATH` / `INSERT INTO ... SELECT` plus `hive_table_stats` / Impala `COMPUTE INCREMENTAL STATS`), while obtaining Hadoop helpers lazily from `goe.backend.hadoop` (relocated in Chapter 5.1).

### 2. Code Analysis Summary

Line references are at HEAD `d6a02fe`:

- `src/goe/offload/snowflake/snowflake_backend_api.py:105-2004` (`BackendSnowflakeApi`) subclasses `BackendApiInterface`, references `SNOWFLAKE_BACKEND_CAPABILITIES` (`:73`) and `SnowflakeColumn` (`:87`), and implements manual SQL string interpolation for `CREATE TABLE`, `ALTER TABLE`, `COPY INTO`, `INFORMATION_SCHEMA` queries, and identifier quoting.
- `src/goe/offload/snowflake/snowflake_backend_table.py:45-629` (`BackendSnowflakeTable`) subclasses `BackendTableInterface`, constructs `SnowflakeColumn` instances directly (`:37`), builds `COPY INTO` / staged `INSERT` SQL manually (`:160-480`), and calls `self._drop_state()` (`:117`) instead of write-through catalog invalidation.
- `src/goe/offload/microsoft/synapse_backend_api.py:1-2515` (`BackendSynapseApi`) imports `pyodbc` directly (`:17`), builds raw ODBC connection strings and Azure AD token structs (`:220-380`), references `SYNAPSE_BACKEND_CAPABILITIES` (`:107`) and `SynapseColumn` (`:92`), and hand-builds T-SQL `CREATE EXTERNAL TABLE`, `CREATE TABLE ... WITH (DISTRIBUTION = ..., CLUSTERED COLUMNSTORE INDEX)`, `COPY INTO`, and `CREATE STATISTICS` statements.
- `src/goe/offload/microsoft/synapse_backend_table.py:51-525` (`BackendSynapseTable`) subclasses `BackendTableInterface`, references `SynapseColumn` (`:30`) and staging column constants (`:35-45`), and orchestrates external-table or `COPY INTO` loads and `compute_stats` (`:105-380`).
- `src/goe/offload/hadoop/hadoop_backend_api.py:1-1559` (`BackendHadoopApi`), `hive_backend_api.py:57-521` (`BackendHiveApi`), `impala_backend_api.py:72-704` (`BackendImpalaApi`), `hadoop_backend_table.py:64-710` (`BackendHadoopTable`), `hive_backend_table.py:35-190` (`BackendHiveTable`), and `impala_backend_table.py:32-224` (`BackendImpalaTable`) wrap `better_impyla` and `hive_table_stats`, reference `HadoopColumn`, `HIVE_BACKEND_CAPABILITIES`, and `IMPALA_BACKEND_CAPABILITIES`, and duplicate `CREATE TABLE`, `ALTER TABLE ADD COLUMNS`, `LOAD DATA`, and `INSERT INTO ... PARTITION (...) SELECT` SQL builders.
- `src/goe/offload/spark/spark_thrift_backend_api.py` (invoked by `src/goe/offload/factory/backend_api_factory.py:72` for `DBTYPE_SPARK`) and the Spark backend modules in `src/goe/offload/spark/` implement Spark SQL Thrift Server backend operations on top of the HiveServer2 / Hadoop abstractions.

### 3. Requirements

- **R1** `BackendSnowflakeApi` and `BackendSnowflakeTable` use `SNOWFLAKE_CAPABILITIES: BackendCapabilities`, `CachedBackendCatalog` (with write-through invalidation on DDL/DML and `warm_schema` via Snowflake `INFORMATION_SCHEMA`), `DialectSqlEngine("snowflake")`, `TypeMappingRegistry.for_backend("snowflake")`, and `StagedLoadInsertStrategy`, preserving stages, storage integrations, file formats, clustering keys (`CLUSTER BY`), query profile logging, and staging cleanup.
- **R2** `BackendSynapseApi` and `BackendSynapseTable` replace direct `pyodbc` session management with `sqlspec.adapters.mssql` (`MssqlPythonConfig` / `mssql-python`), and use `SYNAPSE_CAPABILITIES: BackendCapabilities`, `CachedBackendCatalog` (with write-through invalidation and `sys.tables`/`sys.columns`/`sys.partitions` catalog loading), `DialectSqlEngine("tsql")`, `TypeMappingRegistry.for_backend("synapse")`, and `StagedLoadInsertStrategy`, preserving `HASH` / `ROUND_ROBIN` distribution, `CLUSTERED COLUMNSTORE INDEX` / `HEAP` indexing, PolyBase external tables, `COPY INTO`, and `CREATE STATISTICS` / `UPDATE STATISTICS`.
- **R3** `BackendHadoopApi`, `BackendHadoopTable`, `BackendHiveApi`, `BackendHiveTable`, `BackendImpalaApi`, `BackendImpalaTable`, and the Spark backend modules (`src/goe/offload/spark/`) use `HIVE_CAPABILITIES`, `IMPALA_CAPABILITIES`, and `SPARK_CAPABILITIES`, `CachedBackendCatalog`, `DialectSqlEngine("hive")` / `DialectSqlEngine("spark")`, `TypeMappingRegistry.for_backend("hive" | "impala" | "spark")`, and `StagedLoadInsertStrategy`, importing `better_impyla`, `hive_table_stats`, `hive_ddl_transform`, and `hs2_connection` from `goe.backend.hadoop` and preserving `PMOD(HASH(...))` bucketing, Impala `SORT BY`, ACID transactional table purge properties, and Hive/Impala partition and column statistics.
- **Non-functional**: no inline `#` comments; two-line SPDX header on all created or touched files; public methods and functions placed before private `_` helpers; zero references to deleted `*_column.py`, `*_literal.py`, or `*_predicate.py` modules.
- **Risks and mitigations**:
  - *Risk*: `src/goe/offload/spark/` at HEAD `d6a02fe` uses `spark_thrift_backend_api.py` while callers or registry targets may reference `spark_backend_api.py`, `spark_backend_table.py`, or `thrift_backend_api.py`. *Mitigation*: Task 1.3 aligns the canonical Spark backend modules so every entry point registered in `AdapterRegistry` (`DBTYPE_SPARK`) resolves cleanly without backward-compatibility shims.
  - *Risk*: Synapse T-SQL DDL options (`DISTRIBUTION = HASH(...)`, `CLUSTERED COLUMNSTORE INDEX`, `CREATE EXTERNAL TABLE ... WITH (LOCATION = ..., DATA_SOURCE = ..., FILE_FORMAT = ...)`) have Synapse-specific clauses beyond generic ANSI SQL. *Mitigation*: `DialectSqlEngine("tsql")` renders identifier-safe AST projections and table references while `BackendSynapseApi` supplies the Synapse `WITH (...)` table property clauses and external table options verified by unit tests.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/offload/snowflake/test_snowflake_backend.py` |
| R2 | 1.2 | `tests/unit/offload/microsoft/test_synapse_backend.py` |
| R3 | 1.3 | `tests/unit/offload/hadoop/test_hadoop_and_spark_backends.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/snowflake/test_snowflake_backend.py tests/unit/offload/microsoft/test_synapse_backend.py tests/unit/offload/hadoop/test_hadoop_and_spark_backends.py -v
uv run pytest tests/unit/offload tests/unit/characterization -q
uv run ruff format --check src/goe/offload/snowflake src/goe/offload/microsoft src/goe/offload/hadoop src/goe/offload/spark tests/unit/offload
uv run ruff check src/goe/offload/snowflake src/goe/offload/microsoft src/goe/offload/hadoop src/goe/offload/spark tests/unit/offload
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Secondary Cloud and Hadoop Backend Alignment

- [ ] 1.1 Align Snowflake backend API and table onto capabilities, cached catalog, DialectSqlEngine, and TypeMappingRegistry ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Align Synapse backend API and table onto SQLSpec MSSQL adapter, capabilities, cached catalog, DialectSqlEngine, and TypeMappingRegistry ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Align Hadoop (Hive, Impala) and Spark Thrift backends onto capabilities, cached catalog, DialectSqlEngine, and TypeMappingRegistry ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `snowflake_synapse_hadoop_backend_alignment_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: Snowflake, Synapse, Hive, Impala, and Spark Thrift all use `StagedLoadInsertStrategy` from `goe.backend.ingest`; Synapse sessions use `sqlspec.adapters.mssql` (`MssqlPythonConfig` / `mssql-python`) instead of raw `pyodbc`; Hadoop helpers are imported from `goe.backend.hadoop` (relocated in Chapter 5.1).
- **Discoveries**: none yet.
- **Blockers**: `bigquery_ingest_strategies_20261024` (Chapter 9.3), `backend_capabilities_and_cached_catalog_20261024` (Chapter 9.2), and `canonical_column_model_and_type_registry_20261024` (Chapter 9.1) must complete first.
- **Next exact step**: execute task `1.1` (`snowflake_synapse_hadoop_backend_alignment_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/backends/snowflake.md`, `.agents/bundles/knowledge/backends/synapse.md`, `.agents/bundles/knowledge/backends/hadoop.md`, `.agents/bundles/knowledge/architecture/type-mapping.md`.
