---
type: Guide
title: Database & SQL Standards
description: Unified DialectSqlEngine AST compilation, FrozenBaseStruct PredicateExpr IR, concurrent CrossDbValidator, and SQLSpec OracleGateway conventions
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

## Unified SQL Dialect & AST Engine (`src/goe/offload/sql_ast/` & `src/goe/offload/sql_engine.py`)

- **Strict `sqlglot` Boundary (`[sqlglot-boundary] files = []`)**:
  - Direct `sqlglot` imports are restricted to [`src/goe/offload/sql_ast/`](../../../../../src/goe/offload/sql_ast/__init__.py) and [`src/goe/offload/predicates/compiler.py`](../../../../../src/goe/offload/predicates/compiler.py), enforced by `tools/verify_architecture.py` with an empty baseline (`files = []`).
  - All callers access SQL generation, transpilation, and validation through [`DialectSqlEngine`](../../../../../src/goe/offload/sql_ast/dialect_engine.py) (`get_dialect_engine(dialect)`) and the library-agnostic protocols in [`src/goe/offload/sql_engine.py`](../../../../../src/goe/offload/sql_engine.py):
    - `RenderedSQL(sql: str, params: dict[str, Any])`
    - `ValidationQuerySpec`
    - `DialectSqlEngineProtocol` (`select_from`, `create_table`, `drop_table`, `insert_from_select`, `create_or_replace_view`, `sample_column_precision_sql`, `transpile`, `validation_aggregate_query`, `validation_sample_hash_query`, `transpile_safe_filter`, `parse_filter_tuples`, `build_spec_aggregate_query`, `schema_sync_add_column`, `schema_sync_widen_column`, `schema_sync_relax_nullability`, `schema_sync_drop_partition`)
    - `BigQueryDialectEngineProtocol` (`get_bigquery_dialect_engine()` -> [`BigQuerySqlEngine`](../../../../../src/goe/offload/bigquery/bigquery_sql.py))
    - `OracleExtractionQueryProtocol` (`get_oracle_dialect_engine()` -> [`OracleSqlEngine`](../../../../../src/goe/offload/oracle/oracle_dialect.py))
- **Custom `OracleGoeDialect` (`src/goe/offload/sql_ast/oracle_dialect.py`)**:
  - Extends `sqlglot.dialects.oracle.Oracle` so `Table` AST nodes natively render `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and Flashback `AS OF SCN :scn` clauses without string concatenation.
- **Verbatim Projection & Filter Preservation**:
  - Caller-supplied column cast expressions, literal projections, and pre-rendered filter clauses are embedded as verbatim AST leaves (`exp.Var` / `exp.Paren(this=exp.Var(...))`) rather than re-parsed through `sqlglot.parse_one(...).sql(...)`.
  - This prevents lossy rewrites of Oracle 9-digit nanosecond `TIMESTAMP` literals, 3-argument `TO_DATE(..., 'NLS_CALENDAR=GREGORIAN')`, negative positional `ROUND(col, -2)` arguments, and BigQuery typed literals.
- **BigQuery `OPTIONS (...)` Attachment Gotcha**:
  - `sqlglot`'s `BigQuery` generator wraps `exp.Create(..., properties=exp.Properties(...))` in a redundant outer `OPTIONS (OPTIONS (...))` when `exp.Properties` is rendered directly inside `OPTIONS`. Attach `OPTIONS (...)` via `.set("command", ...)` or construct `exp.Var` property clauses inside `BigQuerySqlEngine` so DDL renders a single `OPTIONS (...)` block.

## Predicate IR & Multi-Dialect Compiler (`src/goe/offload/predicates/`)

- **`FrozenBaseStruct` Predicate IR (`src/goe/offload/predicates/ast.py`)**:
  - User-facing `--offload-predicate` expressions are parsed by `PredicateParser.parse(dsl, column_types=...)` into an immutable, GC-free `PredicateExpr` union (`ColumnRef`, `TypedLiteral`, `ComparisonPred`, `InListPred`, `NullCheckPred`, `LogicalPred`).
  - `PredicateCompiler.render(expr, dialect, bind_style=..., quote_identifiers=...)` compiles `PredicateExpr` trees into `CompiledPredicate(sql, params)` across `oracle`, `bigquery`, `snowflake`, `tsql`, `hive`, `spark`, and `duckdb`, supporting `named_colon` (`:p0`), `named_at` (`@p0`), `pyformat` (`%(p0)s`), `qmark` (`?`), and inline literals.
  - Inside `PredicateCompiler`, 9-digit nanosecond (`FF9`) precision in Oracle `TIMESTAMP(9)` predicates (`TIMESTAMP 'YYYY-MM-DD HH:MM:SS.fffffffff'` and `TO_TIMESTAMP(:p0, 'YYYY-MM-DD HH24:MI:SS.FF9')`) is formatted directly from `numpy.datetime64` without lossy `sqlglot.parse_one` re-parsing.
- **Safe User Filter Clause Gate (`transpile_safe_filter` & `parse_filter_tuples`)**:
  - User-supplied `--filters` clauses in `CrossDbValidator` and `agg_validate.py` are validated via `DialectSqlEngine.transpile_safe_filter()` and `CrossDbValidationBuilder.parse_filter_tuples()`, rejecting semicolons, SQL comments (`--`, `/*`), subqueries (`exp.Subquery`, `exp.Select`), set operations (`UNION`, `INTERSECT`, `EXCEPT`), and DDL/DML tokens.

## Concurrent Cross-Database Validation (`src/goe/offload/validation/`)

- **`CrossDbValidationBuilder` (`src/goe/offload/validation/ast_builder.py`)**:
  - Packs `AggregateQuestion` items (`COUNT`, `MIN`, `MAX`, `SUM`, `AVG`, `STDDEV`, `HASH_XOR`) into batched `ValidationBatchQuery` projections capped at `MAX_AGGREGATES_PER_QUERY = 64` per `SELECT` statement.
  - Emits dialect-specific sample hash queries (`ORA_HASH` on Oracle, `FARM_FINGERPRINT(TO_JSON_STRING(...))` on BigQuery, `HASH(...)` on Snowflake/DuckDB/Spark, `CHECKSUM(...)` on Synapse/T-SQL).
- **`CrossDbValidator` (`src/goe/offload/validation/runner.py`)**:
  - Executes source and target validation batches in parallel via `run_bounded(..., max_workers=2)`, comparing integer/decimal aggregates exactly and floating-point aggregates (`AVG`, `STDDEV`) within `DEFAULT_APPROXIMATE_TOLERANCE = 1e-6`.
  - Supports `--diff` row-level anomaly inspection (`diff_rows_in_duckdb` / `run_row_diff`), streaming bounded primary-key + column projections into an in-memory DuckDB 2.0 relation and running bidirectional `EXCEPT` to isolate mismatched rows.

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
