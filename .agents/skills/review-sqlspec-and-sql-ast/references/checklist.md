# Review Checklist: SQLSpec Data Layer, SQLGlot AST Seam & Predicates (`SQL`)

## `SQL-01`: Strict `sqlglot-boundary` & `oracledb-boundary` Isolation

No module outside `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/` imports `sqlglot`, and no module outside `src/goe/persistence/oracle/`, `src/goe/offload/oracle/`, and `src/goe/persistence/registry.py` imports `oracledb`.

## `SQL-02`: Pooled `OracleDatabaseRegistry` & Shared `SQLFileLoader`

All Oracle queries execute through `OracleDatabaseRegistry` role pools and shared `SQLFileLoader` named statements (`oracle_catalog.sql`, `frontend_metadata.sql`, `oracle_repo.sql`), never ad-hoc `oracledb.connect()` calls.

## `SQL-03`: Single-Place Proxy User Formatting & Piggyback Session Tagging

Oracle proxy credentials (`proxy_user[schema_user]`) are parsed once by `parse_oracle_proxy_user()` (`src/goe/persistence/registry.py`), and session telemetry sets `conn.module`/`conn.action`/`conn.clientinfo` (`<= 64` bytes) via `tag_oracle_session` rather than `DBMS_APPLICATION_INFO` round-trips.

## `SQL-04`: Execution-Scoped `FrontendCatalogCache` Invalidation

`OracleFrontendApi` and `MSSQLFrontendApi` cache `OracleTableSnapshot` / `MssqlTableCatalogSnapshot` in `FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`) and call `invalidate(owner, table_name)` after DDL, partition maintenance, or stats collection.

## `SQL-05`: BigQuery `OPTIONS (...)` & Verbatim AST Leaf Preservation

`DialectSqlEngine` attaches BigQuery table `OPTIONS (...)` without double-wrapping `OPTIONS (OPTIONS (...))` and embeds pre-rendered cast/literal expressions as verbatim `exp.Var` leaves so 9-digit nanosecond `FF9` timestamps are never truncated.

## `SQL-06`: Safe Filter Validation & Batched 64-Aggregate Queries

`CrossDbValidator` validates user `--filters` through `transpile_safe_filter` / `parse_filter_tuples` (rejecting subqueries, comments, semicolons, and set ops) and batches aggregate projections at `MAX_AGGREGATES_PER_QUERY = 64`.
