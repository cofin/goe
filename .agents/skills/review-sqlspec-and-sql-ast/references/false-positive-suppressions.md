# False-Positive Suppressions: SQLSpec Data Layer, SQLGlot AST Seam & Predicates (`FP-SQL`)

## `FP-SQL-01`: DO NOT FLAG integer literal `AS OF SCN <int>` in `GOEOracleDialect` extraction SQL as a missing bind parameter

- **Directive**: DO NOT FLAG integer literal `AS OF SCN <int>` in `GOEOracleDialect` extraction SQL as a missing bind parameter.
- **Rationale**: Oracle Flashback `AS OF SCN` in parallel Spark JDBC and `cofin/duckdb-oracle` `oracle_query(...)` requires an integer SCN literal (`int(scn)`); `GOEOracleDialect` validates `int` type before rendering.

## `FP-SQL-02`: DO NOT FLAG `exp.Var` verbatim leaves in `DialectSqlEngine` as raw SQL concatenation

- **Directive**: DO NOT FLAG `exp.Var` verbatim leaves in `DialectSqlEngine` as raw SQL concatenation.
- **Rationale**: `DialectSqlEngine` intentionally wraps pre-validated dialect cast/literal expressions in `exp.Var` to prevent `sqlglot.parse_one` from rewriting Oracle 9-digit nanosecond `TIMESTAMP` literals and 3-arg `TO_DATE(..., 'NLS_CALENDAR=GREGORIAN')` calls.

## `FP-SQL-03`: DO NOT FLAG `format_sqlcommenter` wrapping `sqlspec.core.sqlcommenter.generate_comment(attrs)` in `/*...*/`

- **Directive**: DO NOT FLAG `format_sqlcommenter` wrapping `sqlspec.core.sqlcommenter.generate_comment(attrs)` in `/*...*/`.
- **Rationale**: `sqlspec.core.sqlcommenter.generate_comment` returns bare `key='value'` pairs without `/*` and `*/` delimiters; wrapping in `format_sqlcommenter` (`src/goe/observability/db.py`) is required.

## `FP-SQL-04`: DO NOT FLAG `OracleCatalogService` decoding `HIGH_VALUE` inside the `NamedStatements` session scope

- **Directive**: DO NOT FLAG `OracleCatalogService` decoding `HIGH_VALUE` inside the `NamedStatements` session scope.
- **Rationale**: Oracle `ALL_TAB_PARTITIONS.HIGH_VALUE` is a `LONG` column whose value must be read while the cursor/session remains open.
