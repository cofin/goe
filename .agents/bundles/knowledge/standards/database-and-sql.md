---
type: concept
title: Database & SQL Standards
description: Unified DialectSqlEngine AST compilation, FrozenBaseStruct PredicateNode IR, concurrent CrossDbValidator, and SQLSpec OracleDatabaseRegistry conventions.
status: stable
tags:
  - standards
  - database
  - sql
  - oracle
  - sqlspec
  - sqlglot
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: dialect-engine
    resource: src/goe/offload/sql_ast/dialect_engine.py::DialectSqlEngine
    title: Unified Multi-Dialect SQLGlot AST Engine
  - id: pred-compiler
    resource: src/goe/offload/predicates/compiler.py::PredicateCompiler
    title: Multi-Dialect Predicate IR Compiler
  - id: validator
    resource: src/goe/validate/validator.py::CrossDbValidator
    title: Concurrent Cross-Database Validator
  - id: ora-registry
    resource: src/goe/persistence/registry.py::OracleDatabaseRegistry
    title: Pooled SQLSpec Oracle Database Registry
---

# Database & SQL Standards

<!-- truth: start -->
- Direct `sqlglot` imports are restricted to `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/compiler.py` (`[sqlglot-boundary]` in `tools/verify_architecture.py`).[^dialect-engine][^pred-compiler]
- Direct `oracledb` imports are restricted to `src/goe/persistence/oracle/`, `src/goe/offload/oracle/`, and `src/goe/persistence/registry.py` (`[oracledb-boundary]` in `tools/verify_architecture.py`).[^ora-registry]
- All extraction queries against Oracle must include Flashback `AS OF SCN <scn>` (rendered by `DialectSqlEngine` and verified by `verify_batch_scn_invariant` in DuckDB).
- User-supplied `--offload-predicate` expressions parse through `PredicateParser` into `PredicateNode` IR and render via `PredicateCompiler` without raw string interpolation.[^pred-compiler]
- `sqlspec.core.sqlcommenter.generate_comment(attrs)` returns inner key/value pairs without `/* ... */` delimiters; wrap via `format_sqlcommenter` (`src/goe/observability/db.py`).
<!-- truth: end -->

## Unified SQL Dialect & AST Engine (`src/goe/offload/sql_ast/`)

- **Strict `sqlglot` Boundary (`[sqlglot-boundary] files = []`)**:
  - Direct `sqlglot` imports are restricted to [`src/goe/offload/sql_ast/`](../../../../../src/goe/offload/sql_ast/__init__.py) and [`src/goe/offload/predicates/compiler.py`](../../../../../src/goe/offload/predicates/compiler.py), enforced by `tools/verify_architecture.py`.
  - Callers access SQL generation, transpilation, and validation through [`DialectSqlEngine`](../../../../../src/goe/offload/sql_ast/dialect_engine.py) (`get_dialect_engine(dialect)`, `get_bigquery_dialect_engine()`, `get_oracle_dialect_engine()`).[^dialect-engine]
- **Custom `GOEOracleDialect` (`src/goe/offload/sql_ast/dialect_engine.py`)**:
  - Extends `sqlglot.dialects.oracle.Oracle` so `Table` AST nodes natively parse and render `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and Flashback `AS OF SCN <int>` clauses without string concatenation.
- **Verbatim Projection & Filter Preservation**:
  - Caller-supplied column cast expressions, literal projections, and pre-rendered filter clauses are embedded as verbatim AST leaves (`exp.Var` / `exp.Paren(this=exp.Var(...))`) rather than re-parsed through `sqlglot.parse_one(...).sql(...)`, preserving Oracle 9-digit nanosecond `TIMESTAMP` literals and BigQuery typed literals.
- **BigQuery `OPTIONS (...)` Attachment Gotcha**:
  - `sqlglot`'s `BigQuery` generator wraps `exp.Create(..., properties=exp.Properties(...))` in a redundant outer `OPTIONS (OPTIONS (...))` when `exp.Properties` is rendered directly inside `OPTIONS`. Attach `OPTIONS (...)` via `.set("command", ...)` or construct property clauses inside `DialectSqlEngine`.

## Predicate IR & Multi-Dialect Compiler (`src/goe/offload/predicates/`)

- **`FrozenBaseStruct` Predicate IR (`src/goe/offload/predicates/ast_nodes.py`)**:
  - User-facing `--offload-predicate` expressions are parsed by `PredicateParser.parse(dsl, column_types=...)` into an immutable, GC-free `PredicateNode` union (`ColumnRef`, `TypedLiteral`, `ComparisonPred`, `InListPred`, `NullCheckPred`, `LogicalPred`).
  - `PredicateCompiler.render(expr, dialect, bind_style=..., quote_identifiers=...)` compiles `PredicateNode` trees into `CompiledPredicate(sql, params)` across `oracle`, `bigquery`, `snowflake`, `tsql`, `hive`, `spark`, and `duckdb`.[^pred-compiler]
- **Safe User Filter Clause Gate (`transpile_safe_filter` & `parse_filter_tuples`)**:
  - User-supplied `--filters` clauses in `CrossDbValidator` are validated via `DialectSqlEngine.transpile_safe_filter()` and `CrossDbValidationBuilder.parse_filter_tuples()`, rejecting semicolons, SQL comments (`--`, `/*`), subqueries, set operations, and DDL/DML tokens.

## Concurrent Cross-Database Validation (`src/goe/validate/`)

- **`CrossDbValidationBuilder` (`src/goe/validate/query_builder.py`)**:
  - Packs `AggregateQuestion` items (`COUNT`, `MIN`, `MAX`, `SUM`, `AVG`, `STDDEV`, `HASH_XOR`) into batched `ValidationBatchQuery` projections capped at `MAX_AGGREGATES_PER_QUERY = 64` per `SELECT` statement.
- **`CrossDbValidator` (`src/goe/validate/validator.py`)**:
  - Executes source and target validation batches in parallel via `run_bounded(..., max_workers=2)`, comparing integer/decimal aggregates exactly and floating-point aggregates (`AVG`, `STDDEV`) within `DEFAULT_APPROXIMATE_TOLERANCE = 1e-6`, with optional `--diff` row-level comparison in DuckDB.[^validator]

## SQLSpec Parameter & Named SQL Discipline

- **Pooled SQLSpec Adapters & `NamedStatements`**:
  - Oracle dictionary and repository SQL is executed via `OracleDatabaseRegistry` ([`src/goe/persistence/registry.py`](../../../../../src/goe/persistence/registry.py)) and `NamedStatements` loaded from `src/goe/offload/oracle/sql/oracle_catalog.sql`, `src/goe/offload/oracle/sql/frontend_metadata.sql`, and `src/goe/persistence/sql/oracle_repo.sql`.[^ora-registry]
  - Microsoft SQL Server catalog SQL is executed via `MssqlPythonConfig` (`mssql-python`) and `NamedStatements` loaded from `src/goe/offload/microsoft/sql/mssql_catalog.sql`.
- **Execution-Scoped Catalog Caching (`FrontendCatalogCache`)**:
  - Frontend catalog inspection caches immutable `FrozenBaseStruct` snapshots in `FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`) per `(execution_id, db_type, owner, table_name)` and invalidates on DDL, partition maintenance, or statistics gathering.

[^dialect-engine]: `src/goe/offload/sql_ast/dialect_engine.py::DialectSqlEngine` — Multi-dialect SQLGlot AST engine and custom `GOEOracleDialect`.
[^pred-compiler]: `src/goe/offload/predicates/compiler.py::PredicateCompiler` — Multi-dialect compiler for `PredicateNode` IR trees.
[^validator]: `src/goe/validate/validator.py::CrossDbValidator` — Concurrent source/target aggregate and row-diff validator.
[^ora-registry]: `src/goe/persistence/registry.py::OracleDatabaseRegistry` — Pooled SQLSpec Oracle connection registry.
