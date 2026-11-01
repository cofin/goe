---
type: concept
title: Oracle Database Frontend Adapter
description: Pooled SQLSpec OracleDatabaseRegistry, session tracing, OffloadMetadata and OracleRepositoryService, OracleCatalogService, FrontendCatalogCache, and GOEOracleDialect AST splitting.
status: stable
tags:
  - frontends
  - oracle
  - database
  - sql
  - sqlspec
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: ora-registry
    resource: src/goe/persistence/registry.py::OracleDatabaseRegistry
    title: Pooled SQLSpec Oracle Database Registry
  - id: ora-catalog
    resource: src/goe/offload/oracle/catalog.py::OracleCatalogService
    title: Consolidated Oracle Catalog Snapshot Service
  - id: ora-repo
    resource: src/goe/persistence/oracle/repository.py::OracleRepositoryService
    title: Oracle Repository Service and PL/SQL Wrapper
  - id: dialect-engine
    resource: src/goe/offload/sql_ast/dialect_engine.py::GOEOracleDialect
    title: Custom Oracle Dialect for Partition and AS OF SCN Clauses
---

# Oracle Database Frontend Adapter

<!-- truth: start -->
- `OracleDatabaseRegistry` (`src/goe/persistence/registry.py`) manages role-keyed (`app`, `adm`, `repo`, `transport`) `sqlspec.adapters.oracledb.OracleSyncConfig` connection pools (`min=1`, `max=8`, `stmtcachesize=100`) and shared `SQLFileLoader` instances.[^ora-registry]
- `session_tracing.py` (`src/goe/persistence/oracle/session_tracing.py`) executes a single combined `ALTER SESSION SET ...` on physical connection creation and tags `conn.module`, `conn.action`, and `conn.clientinfo` (55-byte W3C `traceparent`) with zero extra database round-trips.
- `OracleCatalogService` (`src/goe/offload/oracle/catalog.py`) fetches `OracleTableSnapshot` (including 4-part `ALL_TYPES` UDT attributes in 1 query and `HIGH_VALUE` LONG decoding) and caches snapshots in `FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`).[^ora-catalog]
- `OffloadMetadata` (`src/goe/persistence/models.py`) and `OracleRepositoryService` (`src/goe/persistence/oracle/repository.py`) execute `src/goe/persistence/sql/oracle_repo.sql` and `OFFLOAD_REPO` PL/SQL calls.[^ora-repo]
- `GOEOracleDialect` (`src/goe/offload/sql_ast/dialect_engine.py`) renders `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and `AS OF SCN <int>` AST clauses for snapshot-consistent parallel extraction.[^dialect-engine]
<!-- truth: end -->

## Key Modules

- **`OracleDatabaseRegistry` (`src/goe/persistence/registry.py`)**: Centralized role-keyed (`app`, `adm`, `repo`, `transport`) `sqlspec.adapters.oracledb.OracleSyncConfig` registry backed by pooled `oracledb.ConnectionPool` and a shared `SQLFileLoader`.[^ora-registry]
- **`session_tracing.py` (`src/goe/persistence/oracle/session_tracing.py`)**: Single-round-trip `ALTER SESSION` initialization (`on_connection_create`) and zero-round-trip piggyback session attribute tagging (`tag_oracle_session(conn, module=..., action=..., execution_id=...)`).
- **`OracleCatalogService` (`src/goe/offload/oracle/catalog.py`)**: Consolidated Oracle catalog snapshot service returning immutable `OracleTableSnapshot` structs from `src/goe/offload/oracle/sql/oracle_catalog.sql`.[^ora-catalog]
- **`FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`)**: Execution-scoped in-memory snapshot cache keyed by `(execution_id, db_type, owner, table_name)` with explicit `invalidate(owner, table_name)` after DDL, partition maintenance, or stats gathering.
- **`OracleFrontendApi` (`src/goe/offload/oracle/oracle_frontend_api.py`)**: Connection checkout via `OracleDatabaseRegistry`, `OracleCatalogService` + `FrontendCatalogCache` delegation, DDL extraction, and auxiliary named queries in `src/goe/offload/oracle/sql/frontend_metadata.sql`.
- **`OffloadMetadata` (`src/goe/persistence/models.py`) & `OracleRepositoryService` (`src/goe/persistence/oracle/repository.py`)**: Immutable `OffloadMetadata(FrozenBaseStruct, frozen=True)` domain model and `OracleRepositoryService` executing `src/goe/persistence/sql/oracle_repo.sql` and `OFFLOAD_REPO` PL/SQL calls (packaged DDL in `src/goe/persistence/oracle/ddl/`).[^ora-repo]
- **`GOEOracleDialect` & `DialectSqlEngine` (`src/goe/offload/sql_ast/dialect_engine.py`)**: Custom `sqlglot` Oracle dialect extension supporting `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and `AS OF SCN <int>` AST construction and round-tripping.[^dialect-engine]

## Connection Pooling, Proxy Auth & Session Initialization

- **Pooled `OracleSyncConfig` (`OracleDatabaseRegistry`)**:
  - Each role (`app`, `adm`, `repo`, `transport`) owns a cached `OracleSyncConfig` with `pool_min=1`, `pool_max=8`, `pool_increment=1`, `stmtcachesize=100`, `ping_interval=60`, and `driver_features={"enable_numpy_vectors": False, "enable_lowercase_column_names": True, "enable_uuid_conversion": False, "on_connection_create": ...}`.
  - **Proxy Auth (`proxy_user[schema_user]`)**: `parse_oracle_proxy_user()` splits `user="proxy_user[schema_user]"` into pool credentials `user="proxy_user"` and per-checkout `proxy_user="[schema_user]"`, preventing `ORA-01017` double-bracketing during proxy authentication.[^ora-registry]
  - **Wallet & External Auth**: When `use_oracle_wallet=True` or user/password are empty, `externalauth=True` is configured on the pool without embedding credentials.
- **Single-Round-Trip Session Setup (`src/goe/persistence/oracle/session_tracing.py`)**:
  - `build_alter_session_sql()` combines `TIME_ZONE = '+00:00'`, `NLS_DATE_FORMAT`, `NLS_TIMESTAMP_FORMAT`, `NLS_TIMESTAMP_TZ_FORMAT`, and role-specific session parameters (`ORA_ADM_SESSION_PARAMETERS`, `ORA_APP_SESSION_PARAMETERS`, `ORA_REPO_SESSION_PARAMETERS`) into a single `ALTER SESSION SET ...` executed once per physical connection creation.
- **Piggyback Session Telemetry (`tag_oracle_session`)**:
  - Sets `conn.module = 'GOE'`, `conn.action = <action>`, and `conn.clientinfo = <55-byte W3C traceparent or goe:execution_id>` directly on the `oracledb.Connection` object so attributes piggyback on the next database call with zero extra round-trips.

## Row-Source Splitting Strategies (`DialectSqlEngine`)

| Strategy | Query Pattern | Best For |
| :--- | :--- | :--- |
| `SPLIT_BY_PARTITION` | `SELECT ... FROM "OWNER"."TABLE" PARTITION ("P1") AS OF SCN 12345` | Partitioned tables |
| `SPLIT_BY_SUBPARTITION` | `SELECT ... FROM "OWNER"."TABLE" SUBPARTITION ("SP1") AS OF SCN 12345` | Composite partitioned tables |
| `SPLIT_BY_EXTENT` | `SELECT ... FROM "OWNER"."TABLE" AS OF SCN 12345 WHERE ROWID BETWEEN CHARTOROWID(low) AND CHARTOROWID(high)` | Non-partitioned large tables |
| `SPLIT_BY_MOD` | `SELECT ... FROM "OWNER"."TABLE" AS OF SCN 12345 WHERE MOD(ORA_HASH(col), parallelism) = split_id` | Uniform hash splitting |
| `SPLIT_BY_ID_RANGE` | `SELECT ... FROM "OWNER"."TABLE" AS OF SCN 12345 WHERE id_col >= lower AND id_col < upper` | Monotonic primary key tables |

[^ora-registry]: `src/goe/persistence/registry.py::OracleDatabaseRegistry` — Role-keyed pooled SQLSpec Oracle connection registry.
[^ora-catalog]: `src/goe/offload/oracle/catalog.py::OracleCatalogService` — Consolidated Oracle catalog snapshot service.
[^ora-repo]: `src/goe/persistence/oracle/repository.py::OracleRepositoryService` — Oracle repository service wrapping `oracle_repo.sql` and `OFFLOAD_REPO` PL/SQL procedures.
[^dialect-engine]: `src/goe/offload/sql_ast/dialect_engine.py::GOEOracleDialect` — Custom Oracle SQLGlot dialect supporting `PARTITION`, `SUBPARTITION`, and `AS OF SCN`.
