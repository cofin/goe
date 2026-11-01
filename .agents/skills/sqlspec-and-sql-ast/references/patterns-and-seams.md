# SQLSpec Data Layer, SQLGlot AST Seam & Predicates — Patterns & Seams

## Canonical Seam & Test Matrix

| Subsystem Seam | Primary Symbol Anchor | Dependency Category | Canonical Unit Tests |
| :--- | :--- | :--- | :--- |
| Oracle Database Registry | `src/goe/persistence/registry.py::OracleDatabaseRegistry` | Remote-owned (Ports & Adapters) | `tests/unit/persistence/` |
| Oracle Catalog Service | `src/goe/offload/oracle/catalog.py::OracleCatalogService` | Remote-owned (Ports & Adapters) | `tests/unit/offload/oracle/` |
| Frontend Catalog Cache | `src/goe/offload/frontend_cache.py::FrontendCatalogCache` | In-process | `tests/unit/offload/` |
| Dialect SQL Engine | `src/goe/offload/sql_ast/dialect_engine.py::DialectSqlEngine` | In-process | `tests/unit/offload/sql_ast/` |
| Predicate Parser & Compiler | `src/goe/offload/predicates/compiler.py::PredicateCompiler` | In-process | `tests/unit/offload/predicates/` |
| Cross-DB Validator & Schema Sync | `src/goe/validate/validator.py::CrossDbValidator` | In-process / Ports & Adapters | `tests/unit/validate/ tests/unit/sync/` |

## Domain Invariants (`SQL`)

- **`SQL-01` (Strict `sqlglot-boundary` & `oracledb-boundary` Isolation)**: No module outside `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/` imports `sqlglot`, and no module outside `src/goe/persistence/oracle/`, `src/goe/offload/oracle/`, and `src/goe/persistence/registry.py` imports `oracledb`.
- **`SQL-02` (Pooled `OracleDatabaseRegistry` & Shared `SQLFileLoader`)**: All Oracle queries execute through `OracleDatabaseRegistry` role pools and shared `SQLFileLoader` named statements (`oracle_catalog.sql`, `frontend_metadata.sql`, `oracle_repo.sql`), never ad-hoc `oracledb.connect()` calls.
- **`SQL-03` (Single-Place Proxy User Formatting & Piggyback Session Tagging)**: Oracle proxy credentials (`proxy_user[schema_user]`) are parsed once by `parse_oracle_proxy_user()` (`src/goe/persistence/registry.py`), and session telemetry sets `conn.module`/`conn.action`/`conn.clientinfo` (`<= 64` bytes) via `tag_oracle_session` rather than `DBMS_APPLICATION_INFO` round-trips.
- **`SQL-04` (Execution-Scoped `FrontendCatalogCache` Invalidation)**: `OracleFrontendApi` and `MSSQLFrontendApi` cache `OracleTableSnapshot` / `MssqlTableCatalogSnapshot` in `FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`) and call `invalidate(owner, table_name)` after DDL, partition maintenance, or stats collection.
- **`SQL-05` (BigQuery `OPTIONS (...)` & Verbatim AST Leaf Preservation)**: `DialectSqlEngine` attaches BigQuery table `OPTIONS (...)` without double-wrapping `OPTIONS (OPTIONS (...))` and embeds pre-rendered cast/literal expressions as verbatim `exp.Var` leaves so 9-digit nanosecond `FF9` timestamps are never truncated.
- **`SQL-06` (Safe Filter Validation & Batched 64-Aggregate Queries)**: `CrossDbValidator` validates user `--filters` through `transpile_safe_filter` / `parse_filter_tuples` (rejecting subqueries, comments, semicolons, and set ops) and batches aggregate projections at `MAX_AGGREGATES_PER_QUERY = 64`.
