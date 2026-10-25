---
type: Reference
title: Oracle Database Frontend Adapter
description: Pooled SQLSpec OracleDatabaseRegistry, session tracing, OffloadMetadata and OracleRepositoryService, OracleCatalogService and FrontendCatalogCache, custom Oracle dialect AST, and PL/SQL packages
tags:
  - reference
  - frontends
  - oracle
  - database
  - sql
  - sqlspec
---

# Oracle Database Frontend Adapter

The Oracle frontend adapter (`src/goe/offload/oracle/` and `src/goe/persistence/oracle/`) provides pooled SQLSpec connectivity, catalog snapshot inspection, repository persistence, custom Oracle dialect AST generation (`PARTITION`/`SUBPARTITION` and `AS OF SCN`), Flashback SCN snapshot extraction, and row-source splitting for Oracle databases.

## Key Modules

- **`OracleDatabaseRegistry` (`src/goe/persistence/oracle/registry.py`)**: Centralized role-keyed (`app`, `adm`, `repo`, `transport`) `sqlspec.adapters.oracledb.OracleSyncConfig` registry backed by pooled `oracledb.ConnectionPool` (`min=1`, `max=8`, `increment=1`, `stmtcachesize=100`, `ping_interval=60`) and a shared `SQLFileLoader` (`StatementCacheHolder` reuse across calls). Deletes the legacy `OracleGateway`, `OracleOrchestrationRepoClient`, and `src/goe/util/ora_query.py`.
- **`session_tracing.py` (`src/goe/persistence/oracle/session_tracing.py`)**: Single-round-trip `ALTER SESSION` initialization (`on_connection_create`) and zero-round-trip Piggyback session attribute tagging (`tag_oracle_session(conn, module=..., action=..., execution_id=...)`).
- **`OracleCatalogService` (`src/goe/offload/oracle/catalog.py`)**: Consolidated Oracle catalog snapshot service returning immutable `OracleTableSnapshot` structs (`OracleTableOverview`, `OracleColumnMetadata` with 4-part `ALL_TYPES` UDT attributes in 1 query, `OraclePartitionBatch` decoding `HIGH_VALUE` inside the `NamedStatements` session scope, primary/unique/IOT key columns, and `OracleColumnStatistics`) from `src/goe/offload/oracle/sql/oracle_catalog.sql`.
- **`FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`)**: Execution-scoped in-memory snapshot cache keyed by `(execution_id, db_type, owner, table_name)` with explicit `invalidate(owner, table_name)` after DDL, partition maintenance, or stats gathering.
- **`OracleFrontendApi` (`src/goe/offload/oracle/oracle_frontend_api.py`)**: Connection checkout via `OracleDatabaseRegistry`, `OracleCatalogService` + `FrontendCatalogCache` delegation, DDL extraction, and auxiliary named queries in `src/goe/offload/oracle/sql/frontend_metadata.sql`.
- **`OraclePartition` & `OracleSubPartition` (`src/goe/offload/oracle/oracle_partition.py`)**: Partition value objects hydrated from `OraclePartitionRow`.
- **`OracleSourceTable` (`src/goe/offload/oracle/oracle_source_table.py`) & `OracleSourceTableOffloadMixin` (`src/goe/offload/oracle/oracle_offload_source_table.py`)**: Snapshot-backed source table metadata, canonical column mapping, and offload predicate/hash/version rules.
- **`OffloadMetadata` (`src/goe/persistence/metadata.py`) & `OracleRepositoryService` (`src/goe/persistence/oracle/oracle_repository.py`)**: Immutable `OffloadMetadata(FrozenBaseStruct, kw_only=True)` domain model and `OffloadMetadataRepository` / `OracleRepositoryService` executing `src/goe/persistence/oracle/sql/oracle_repo.sql` and `OFFLOAD_REPO` PL/SQL calls.
- **`OracleSqlEngine` (`src/goe/offload/oracle/oracle_dialect.py`)**: Upstreamable custom `sqlglot` Oracle dialect extension and `OracleExtractionQueryProtocol` implementation supporting `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and `AS OF SCN <int>` AST construction and round-tripping.
- **`OffloadTransportOracleApi` (`src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py`)**: SCN snapshot generation and parallel row splitting delegated to `OracleSqlEngine`.
- **`OracleLiteral` (`src/goe/offload/oracle/oracle_literal.py`)**: Literal formatting (`TO_DATE`, `TO_TIMESTAMP`, `HEXTORAW`).

## Connection Pooling, Proxy Auth & Session Initialization

- **Pooled `OracleSyncConfig` (`OracleDatabaseRegistry`)**:
  - Each role (`app`, `adm`, `repo`, `transport`) owns a cached `OracleSyncConfig` with `pool_min=1`, `pool_max=8`, `pool_increment=1`, `stmtcachesize=100`, `ping_interval=60`, and `driver_features={"enable_numpy_vectors": False, "enable_lowercase_column_names": True, "enable_uuid_conversion": False, "on_connection_create": ...}`.
  - **Proxy Auth (`proxy_user[schema_user]`)**: `parse_oracle_proxy_user()` splits `user="proxy_user[schema_user]"` into pool credentials `user="proxy_user"` and per-checkout `proxy_user="[schema_user]"`, preventing `ORA-01017` during proxy authentication.
  - **Wallet & External Auth**: When `use_oracle_wallet=True` or user/password are empty, `externalauth=True` is configured on the pool without embedding credentials.
- **Single-Round-Trip Session Setup (`src/goe/persistence/oracle/session_tracing.py`)**:
  - `build_alter_session_sql()` combines `TIME_ZONE = '+00:00'`, `NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'`, `NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF'`, `NLS_TIMESTAMP_TZ_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF TZR'`, and role-specific session parameters (`ORA_ADM_SESSION_PARAMETERS`, `ORA_APP_SESSION_PARAMETERS`, `ORA_REPO_SESSION_PARAMETERS`) into a single `ALTER SESSION SET ...` executed once per physical connection creation.
- **Piggyback Session Telemetry (`tag_oracle_session`)**:
  - Sets `conn.module = 'GOE'`, `conn.action = <action>`, and `conn.clientinfo = <55-byte W3C traceparent or goe:execution_id>` directly on the `oracledb.Connection` object so attributes piggyback on the next database call with zero extra round-trips (`DBMS_APPLICATION_INFO` is never called).
  - Preserves `MODULE` and `ACTION` for `gv$sql` queries (`get_session_option_rates()`).
  - Configures `StatementConfig` with `SQLCommenter` and `ObservabilityConfig(telemetry=TelemetryConfig(...))` (`goe.observability.db.build_db_observability_config("oracle")`).

## Consolidated Catalog Snapshot & Scoped Cache

- **Named SQL Files (`SQLFileLoader`)**:
  - `src/goe/offload/oracle/sql/oracle_catalog.sql`: Consolidated table overview + columns (`ALL_TAB_COLS` left-joined with `ALL_TYPES` so 4-part UDT metadata is fetched in the same query), partition/subpartition batches, constraint/IOT key columns, and column statistics.
  - `src/goe/offload/oracle/sql/frontend_metadata.sql`: Auxiliary dictionary statements executed via `NamedStatements`.
  - `src/goe/persistence/oracle/sql/oracle_repo.sql`: Repository queries (`get_command_execution`, `get_command_execution_steps`, `get_offload_chunks`, `get_schema_Metadata`, `get_table_Metadata`, `get_table_partitions`, `get_table_subpartitions`, `select_offload_metadata`, `select_offload_join_metadata`).
- **`FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`)**:
  - Stores `OracleTableSnapshot` (and `MssqlTableCatalogSnapshot`) keyed by `(execution_id, db_type, owner.upper(), table_name.upper())`.
  - `OracleFrontendApi` invalidates `(schema, table_name)` automatically after DDL execution, partition maintenance, or optimizer statistics gathering.

## Offload Metadata & `OracleRepositoryService`

- **`OffloadMetadata` (`src/goe/persistence/metadata.py`)**:
  - Immutable `FrozenBaseStruct` replacing `OrchestrationMetadata` across all orchestration, offload, schema sync, validation, and report call sites.
  - Provides `from_attributes()`, `from_legacy_dict()`, `to_repo_dict()`, `with_updates()`, and `decode_Incremental_predicate_values()`.
- **`OracleRepositoryService` (`src/goe/persistence/oracle/oracle_repository.py`)**:
  - Executes all repository queries through `NamedStatements` on the `repo` pool and wraps `OFFLOAD_REPO` PL/SQL procedures (`START_COMMAND` with `oracledb.DB_TYPE_NUMBER` out-bind, `END_COMMAND`, `START_COMMAND_STEP`, `END_COMMAND_STEP`, `SAVE_OFFLOAD_METADATA`, `DROP_OFFLOAD_METADATA`, `SAVE_OFFLOAD_JOIN_METADATA`, `DROP_OFFLOAD_JOIN_METADATA`).
  - Validates rows into typed `FrozenBaseStruct` schemas in `src/goe/persistence/schemas.py` (`FrontendSchemaDetail`, `FrontendTableDetail`, `ColumnDetail`, `PartitionDetail`, `SubPartitionDetail`, `CommandExecutionSummary`, `CommandExecutionDetail`, `CommandStepDetail`).

## Custom Oracle Dialect AST & Row-Source Splitting (`src/goe/offload/oracle/oracle_dialect.py`)

`register_oracle_dialect_extensions()` extends `sqlglot`'s `Oracle` dialect with `SUBPARTITION` tokenization (`TokenType.PARTITION`), `Oracle.ALIAS_POST_VERSION = True`, `OracleParser.SUPPORTS_PARTITION_SELECTION = True`, `OracleParser.VERSION_PHRASES` (`AS OF SCN`, `AS OF TIMESTAMP`, `VERSIONS SCN`, `VERSIONS TIMESTAMP`), and `OracleGenerator.TRANSFORMS[exp.Version]`, followed by `sqlspec.builder._generation.invalidate_generator_dispatch(OracleGenerator)`. `AS OF SCN <int>` is emitted as an integer literal so both Spark JDBC and `cofin/duckdb-oracle` `oracle_query(...)` execute snapshot-consistent reads without bind parameter limitations.

| Strategy | Query Pattern | Best For |
| :--- | :--- | :--- |
| `SPLIT_BY_PARTITION` | `SELECT ... FROM "OWNER"."TABLE" PARTITION ("P1") AS OF SCN 12345` | Partitioned tables |
| `SPLIT_BY_SUBPARTITION` | `SELECT ... FROM "OWNER"."TABLE" SUBPARTITION ("SP1") AS OF SCN 12345` | Composite partitioned tables |
| `SPLIT_BY_EXTENT` | `SELECT ... FROM "OWNER"."TABLE" AS OF SCN 12345 WHERE ROWID BETWEEN CHARTOROWID(low) AND CHARTOROWID(high)` | Non-partitioned large tables |
| `SPLIT_BY_MOD` | `SELECT ... FROM "OWNER"."TABLE" AS OF SCN 12345 WHERE MOD(ORA_HASH(col), parallelism) = split_id` | Uniform hash splitting |
| `SPLIT_BY_ID_RANGE` | `SELECT ... FROM "OWNER"."TABLE" AS OF SCN 12345 WHERE id_col >= lower AND id_col < upper` | Monotonic primary key tables |

## PL/SQL Packages (`OFFLOAD` & `OFFLOAD_REPO`)

- `offload.version`: Validates installed database package build matches the Python binary.
- `offload.get_init_param`: Queries database initialization parameters (block size, character set).
- `offload.offload_rowid_ranges`: Pipelined table function for extent chunk generation.
- `offload_repo.start_command` / `end_command`: Audit logging in repository tables, persisting `_trace_id` and `_span_id` inside `COMMAND_PARAMETERS` JSON and `STEP_DETAILS` JSON when OpenTelemetry is enabled.
