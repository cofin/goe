---
type: Guide
title: Database & SQL Standards
description: Pluggable SQL dialect engine protocols, SQLSpec OracleGateway conventions, Lark/AST predicate rendering, and snapshot consistency
tags:
  - guide
  - standards
  - database
  - sql
  - oracle
  - sqlspec
  - sqlglot
---

# Database & SQL Standards

## Pluggable SQL Dialect & AST Engine Seam (`src/goe/offload/sql_engine.py`)

- **Protocol-First Decoupling (No Direct `sqlglot` Imports in Callers)**:
  - All SQL DDL/DML generation, Oracle extraction row-source construction, predicate rendering, and cross-database validation queries are accessed through library-agnostic `typing.Protocol` interfaces and value objects in [`src/goe/offload/sql_engine.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/sql_engine.py):
    - `RenderedSQL(sql: str, params: dict[str, Any])`
    - `ValidationQuerySpec`
    - `BigQueryDialectEngineProtocol` (`get_bigquery_dialect_engine()` -> [`BigQuerySqlEngine`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/bigquery/bigquery_sql.py))
    - `OracleExtractionQueryProtocol` (`get_oracle_dialect_engine()` -> [`OracleSqlEngine`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/oracle/oracle_dialect.py))
    - `PredicateDialectEngineProtocol` (`get_predicate_dialect_engine(dialect)` -> [`PredicateSqlEngine`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/predicate_offload.py))
    - `ValidationQueryEngineProtocol` (`get_validation_query_engine(dialect)` -> [`ValidationSqlEngine`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_validation.py))
  - Public protocol signatures accept only GOE domain types (`ColumnMetadataInterface`, `lark.Tree`, `Mapping[str, Any]`, primitives) and return `str` or `RenderedSQL` — never exposing `sqlglot.exp.Expr` to callers.
- **Verbatim Projection & Filter Preservation**:
  - Caller-supplied column cast expressions, literal projections, and pre-rendered filter clauses are embedded as verbatim AST leaves (`exp.Var` / `exp.Paren(this=exp.Var(...))`) rather than re-parsed through `sqlglot.parse_one(...).sql(...)`.
  - This prevents lossy rewrites of Oracle 9-digit nanosecond `TIMESTAMP` literals, 3-argument `TO_DATE(..., 'NLS_CALENDAR=GREGORIAN')`, negative positional `ROUND(col, -2)` arguments, and BigQuery typed literals.
- **BigQuery `OPTIONS (...)` Attachment Gotcha**:
  - `sqlglot`'s `BigQuery` generator wraps `exp.Create(..., properties=exp.Properties(...))` in a redundant outer `OPTIONS (OPTIONS (...))` when `exp.Properties` is rendered directly inside `OPTIONS`. Attach `OPTIONS (...)` via `.set("command", ...)` or construct `exp.Var` property clauses inside `BigQuerySqlEngine` so DDL renders a single `OPTIONS (...)` block.

## Predicate Parsing & Safe SQL Filter Validation (`src/goe/offload/predicate_offload.py`)

- **Lark Grammar + AST Rendering**:
  - User-facing `--offload-predicate` expressions are parsed into `GenericPredicate` (`lark.Tree`) and rendered into target-specific SQL or parameterized binds (`RenderedSQL`) via `PredicateSqlEngine` for Oracle (`oracle_predicate.py`) and BigQuery (`bigquery_predicate.py`), while preserving `GenericPredicateToSQL` visitor base classes for Hadoop, Snowflake, Synapse, and Teradata.
  - Inside `PredicateSqlEngine`, 9-digit nanosecond (`FF9`) precision in Oracle `TIMESTAMP(9)` predicates (`TIMESTAMP 'YYYY-MM-DD HH:MM:SS.fffffffff'` and `TO_TIMESTAMP(:bind, 'YYYY-MM-DD HH24:MI:SS.FF9')`) is formatted directly from `numpy.datetime64` without re-parsing through `sqlglot.parse_one`.
- **Safe User Filter Clause Gate (`parse_safe_sql_predicate`)**:
  - User-supplied `--filters` clauses in `CrossDbValidator` (`src/goe/offload/offload_validation.py`) are validated with `parse_safe_sql_predicate()` before inclusion in `WHERE` clauses, rejecting semicolons, comments, subqueries (`exp.Subquery`, `exp.Select`), `UNION`, and DDL/DML tokens.

## SQLSpec Parameter & Named SQL Discipline

- **Pooled SQLSpec Adapters & `NamedStatements`**:
  - Oracle dictionary and repository SQL is executed via `OracleDatabaseRegistry` (`src/goe/persistence/oracle/registry.py`) and `NamedStatements` loaded from `src/goe/offload/oracle/sql/oracle_catalog.sql`, `src/goe/offload/oracle/sql/frontend_metadata.sql`, and `src/goe/persistence/oracle/sql/oracle_repo.sql`.
  - Microsoft SQL Server catalog SQL is executed via `MssqlPythonConfig` (`mssql-python`) and `NamedStatements` loaded from `src/goe/offload/microsoft/sql/mssql_catalog.sql`.
- **Bind Parameter Discipline**:
  - Oracle SQLSpec queries use `:param_name` (`NAMED_COLON`) binds passed as a `dict[str, Any]`.
  - Microsoft SQL Server (`mssql-python`) queries use `qmark` (`?`) positional binds (or `:param_name` compiled by `sqlspec` to `?`).
- **Execution-Scoped Catalog Caching (`FrontendCatalogCache`)**:
  - Frontend catalog inspection (`OracleCatalogService.get_table_snapshot` and `MSSQLFrontendApi.get_table_snapshot`) caches immutable `FrozenBaseStruct` snapshots in `FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`) per `(execution_id, db_type, owner, table_name)` and explicitly invalidates on DDL, partition maintenance, or statistics gathering.
- **SQLCommenter Formatting**: `sqlspec.core.sqlcommenter.generate_comment(attrs)` returns inner key/value pairs without `/*` and `*/` delimiters; wrap the returned string in `/*...*/` when constructing standalone SQL comments (`format_sqlcommenter` in `src/goe/observability/db.py`).

## Transactional & Snapshot Consistency

- **Consistent Reads**: Extraction queries against Oracle must include Flashback `AS OF SCN <scn>` (generated via `OracleSqlEngine.build_extraction_query` and verified in DuckDB via `verify_batch_scn_invariant` before opening a connection) to guarantee snapshot isolation across parallel Spark, Query Import, and DuckDB workers.
- **Non-Invasive Execution**: Never lock source tables in exclusive mode during normal data offload operations; coordinate table concurrency via `FileLockOrchestrationLock`.
- **Repository Atomicity**: Repository state updates (`COMMAND_EXECUTION`, `COMMAND_EXECUTION_STEP`, `BACKEND_OBJECT`) must be committed atomically.

## DDL Best Practices

- Respect backend identifier case rules (`BACKEND_IDENTIFIER_CASE`: `UPPER`, `LOWER`, or `NO_MODIFY`).
- Always strip physical storage attributes (`TABLESPACE`, `STORAGE`, `SEGMENT`) when reverse-engineering Oracle DDL via `DBMS_METADATA`.
