---
type: Reference
title: Oracle Database Frontend Adapter
description: Driver lifecycle, SQLSpec OracleGateway, named SQL files, custom Oracle dialect AST, SCN snapshots, PL/SQL packages, and session telemetry
tags:
  - reference
  - frontends
  - oracle
  - database
  - sql
  - sqlspec
---

# Oracle Database Frontend Adapter

The Oracle frontend adapter (`src/goe/offload/oracle/` and `src/goe/persistence/`) provides connectivity, SQLSpec-backed dictionary/repository query execution, custom Oracle dialect AST generation (`PARTITION`/`SUBPARTITION` and `AS OF SCN`), Flashback SCN snapshot extraction, and row-source splitting for Oracle databases.

## Key Modules

- **`OracleGateway` (`src/goe/persistence/oracle_gateway.py`)**: Centralized SQLSpec execution seam wrapping validated `python-oracledb` connections in per-call `OracleSyncDriver(connection=...)` instances via `OracleSyncConfig(connection_config=None, driver_features={"enable_numpy_vectors": False, "enable_lowercase_column_names": True})` and `SQLFileLoader`.
- **`OracleFrontendApi` (`src/goe/offload/oracle/oracle_frontend_api.py`)**: Connection management, session initialization, sniped-session reconnect (`get_validated_oracle_connection()`), DDL extraction, and 16 named dictionary queries in `src/goe/offload/oracle/sql/frontend_metadata.sql`.
- **`OracleOrchestrationRepoClient` (`src/goe/persistence/oracle/oracle_orchestration_repo_client.py`)**: Repository metadata and introspection client executing 7 named queries in `src/goe/persistence/sql/oracle_repo.sql` validated against `msgspec.Struct` row schemas (`src/goe/persistence/schemas.py`).
- **`OracleQuery` (`src/goe/util/ora_query.py`)**: Cursor helper sharing case-preserving row-to-dict projection (`rows_as_dicts`) with `OracleGateway`.
- **`OracleSqlEngine` (`src/goe/offload/oracle/oracle_dialect.py`)**: Upstreamable custom `sqlglot` Oracle dialect extension and `OracleExtractionQueryProtocol` implementation supporting `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and `AS OF SCN <int>` AST construction and round-tripping.
- **`OffloadTransportOracleApi` (`src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py`)**: SCN snapshot generation and parallel row splitting delegated to `OracleSqlEngine`.
- **`OracleSourceTable` (`src/goe/offload/oracle/oracle_offload_source_table.py`)**: Data dictionary inspection (`ALL_TABLES`, `ALL_TAB_PARTITIONS`, `DBA_TAB_SUBPARTITIONS`).
- **`OracleLiteral` (`src/goe/offload/oracle/oracle_literal.py`)**: Literal formatting (`TO_DATE`, `TO_TIMESTAMP`, `HEXTORAW`).

## Connection Management & Modes

- **Driver**: `python-oracledb` (with `OracleGateway` borrowing validated connections rather than opening a separate pool).
- **Client Modes**:
  - **Thin Mode (Default)**: Pure Python networking; zero Oracle Instant Client dependencies.
  - **Thick Mode**: Enables Oracle Instant Client for Oracle Wallet authentication (`USE_ORACLE_WALLET=true`), LDAP/TNS, Proxy authentication (`user[schema]`), and mTLS.
- **Automatic Reconnection**: `OracleFrontendApi.get_validated_oracle_connection()` transparently recovers from transient disconnects and sniped sessions (`ORA-02396`, `ORA-03113`, `ORA-03114`, `ORA-03135`).
- **Session Environment**:
  ```sql
  ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS';
  ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF';
  ALTER SESSION SET TIME_ZONE = '00:00';
  ```

## SQLSpec `OracleGateway` & Named SQL Files

- **Per-Call Borrowed Connection Wrapping**: `OracleGateway` never manages a competing connection pool. Callers pass `connection_provider=frontend_api.get_validated_oracle_connection` so all enterprise auth, reconnect, and session state invariants remain owned by `OracleFrontendApi`.
- **Named SQL Files (`SQLFileLoader`)**:
  - `src/goe/offload/oracle/sql/frontend_metadata.sql`: 16 named data dictionary statements (`-- name: get_schema_tables`, `get_offloadable_schemas`, `get_columns`, `get_subpartition_columns`, etc.).
  - `src/goe/persistence/sql/oracle_repo.sql`: 7 named repository statements (`-- name: get_command_execution`, `get_command_execution_steps`, `get_offload_chunks`, `get_schema_Metadata`, `get_table_Metadata`, `get_table_partitions`, `get_table_subpartitions`) using bound `:adm_user`, `:app_user`, and `:repo_user` parameters (`NAMED_COLON`).
- **Typed Row Hydration**: Repository queries pass `schema_type=<MsgspecStruct>` to `OracleGateway.select_named()` and convert validated structs via `msgspec.structs.asdict()` when dictionary return shapes are required.
- **PL/SQL Boundary**: PL/SQL anonymous blocks, refcursors, and Oracle UDT object binds (`OFFLOAD_METADATA_OBJ`, `OFFLOAD_PARTITION_LIST_IOT`) remain on `OracleFrontendApi.execute_function` / `execute_procedure` while `OracleGateway.new_out_var()` provides cursor `out_var` allocation.

## Session Telemetry & SQLCommenter (`src/goe/observability/db.py`)

- **`MODULE` / `ACTION` Preservation**: Sessions are tagged via `DBMS_APPLICATION_INFO.SET_MODULE('GOE', '<action>')`. `LOG_SQL_STATS_QUERY_TEXT` queries `gv$sql` by `module` and `action` to collect transport SQL execution statistics, so `MODULE` and `ACTION` are never overwritten by trace context.
- **W3C `traceparent` in `V$SESSION.CLIENT_INFO`**: When OpenTelemetry is enabled (`GOE_OTEL_ENABLED=true`), `tag_oracle_session_trace(conn)` writes the 55-byte W3C `traceparent` (`00-<32hex>-<16hex>-01`, fitting within Oracle's 64-byte `V$SESSION.CLIENT_INFO` limit) via the zero-round-trip `conn.clientinfo` attribute (piggybacked on the next database call) with fallback to `DBMS_APPLICATION_INFO.SET_CLIENT_INFO`.
- **SQLCommenter & `sqlspec.query` Spans**: When observability is enabled, `OracleGateway` configures `StatementConfig.replace(enable_sqlcommenter=True, sqlcommenter_attributes={"db_driver": "oracledb", "framework": "goe"}, sqlcommenter_enable_traceparent=True, sqlcommenter_enable_context=True)` with `SQLCommenterContext.scope({"action": name})` and emits `sqlspec.query` spans via `ObservabilityConfig(telemetry=TelemetryConfig(...))`.

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
