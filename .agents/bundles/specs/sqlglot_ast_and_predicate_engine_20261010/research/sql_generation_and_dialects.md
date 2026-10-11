---
type: Research
title: SQL Generation & Dialect Management (Pluggable Dialect Seam + Custom Oracle Dialect over sqlglot) for GOE
description: Evaluates sqlglot for GOE, specifies a library-agnostic Protocol seam (src/goe/offload/sql_engine.py) without vendor lock-in, documents a custom upstreamable Oracle dialect extension (src/goe/offload/oracle/oracle_dialect.py) for AS OF SCN and PARTITION/SUBPARTITION AST parsing and generation, and records empirical round-trip caveats for caller SQL expressions.
tags: [research, sql, sqlglot, dialects, oracle, bigquery, architecture]
created_at: 2026-10-10T15:55:00Z
updated_at: 2026-10-10T19:25:00Z
---

# SQL Generation & Dialect Management (Pluggable Dialect Seam + Custom Oracle Dialect over sqlglot) for GOE

## 1. Executive Summary

**Recommendation: define a library-agnostic SQL dialect & AST engine seam (`src/goe/offload/sql_engine.py`) using `typing.Protocol` interfaces and `msgspec.Struct` value objects, backed initially by `sqlglot` as an encapsulated implementation detail, and register a custom upstreamable Oracle dialect extension (`src/goe/offload/oracle/oracle_dialect.py`) for `AS OF SCN` and `PARTITION` / `SUBPARTITION` AST construction. Do not leak `sqlglot.exp` types to callers. Do not use Oracle→BigQuery transpilation.**

1. **Encapsulate `sqlglot` behind a pluggable `Protocol` seam (No Vendor Lock-In).**
   - Callers (`BackendBigQueryApi`, `OffloadTransportOracleApi`, `oracle_predicate.py`, `bigquery_predicate.py`, `CrossDbValidator`) must **never import `sqlglot` or `sqlglot.exp` directly**.
   - Instead, `src/goe/offload/sql_engine.py` defines:
     - `RenderedSQL(msgspec.Struct, frozen=True, kw_only=True)`: `sql: str`, `params: dict[str, Any] = msgspec.field(default_factory=dict)`
     - `ValidationQuerySpec(msgspec.Struct, frozen=True, kw_only=True)`: domain specification for cross-DB aggregate validation queries.
     - `BigQueryDialectEngineProtocol(Protocol)`: methods (`partition_by_clause`, `properties_clause`, `create_table`, `create_external_table`, `create_or_replace_ddl`, `ctas`, `insert_select`, `alter_add_columns`, `create_view`) accepting pure GOE domain parameters and returning `str`.
     - `OracleExtractionQueryProtocol(Protocol)`: methods (`snapshot_scn_clause`, `iot_partition_clause`, `table_from_clause`, `id_range_query`, `transport_row_source_query`, `parse_and_render`) building and round-tripping Oracle extraction queries (`PARTITION("P1")`, `SUBPARTITION("SP1")`, `AS OF SCN <scn>`, `TABLE(offload.offload_rowid_ranges(...))`, `MOD(ORA_HASH(...))`) and returning `str`.
     - `PredicateDialectEngineProtocol(Protocol)`: `render_literal_sql`, `render_bind_sql`, and `validate_where_clause`.
     - `ValidationQueryEngineProtocol(Protocol)`: `build_aggregate_query(spec: ValidationQuerySpec) -> str` and `validate_filter_clause(raw_filter: str, dialect: str) -> str`.
2. **Custom Temporary Oracle Dialect Extension (`src/goe/offload/oracle/oracle_dialect.py`) for Future Upstreaming to `sqlspec`:**
   - Although stock `sqlglot.dialects.oracle.Oracle` does not enable `SUPPORTS_PARTITION_SELECTION` or `AS OF SCN` / `VERSIONS BETWEEN` out of the box, registering targeted extensions on `Oracle`, `OracleParser`, and `OracleGenerator` (modeled directly on `sqlspec.dialects.spanner`) yields **100% lossless AST round-trip parsing and generation**:
     - `Oracle.Tokenizer.KEYWORDS["SUBPARTITION"] = TokenType.PARTITION` (where `TokenType` is imported from `sqlglot.tokenizer_core` to satisfy `mypy --strict`)
     - `Oracle.ALIAS_POST_VERSION = True`
     - `OracleParser.SUPPORTS_PARTITION_SELECTION = True`
     - `OracleParser.VERSION_PHRASES` extended with `("AS", "OF", "SCN"): "SCN"`, `("AS", "OF", "TIMESTAMP"): "TIMESTAMP"`, `("VERSIONS", "SCN"): "SCN"`, `("VERSIONS", "TIMESTAMP"): "TIMESTAMP"`
     - `OracleGenerator.TRANSFORMS[exp.Version] = _oracle_version_sql` + `invalidate_generator_dispatch(OracleGenerator)`
   - Verified empirically in `.venv` (`sqlglot` 30.17.0 + `sqlspec` 0.62.1):
     - `SELECT /*+ FULL(s) */ a FROM "SH"."SALES" PARTITION ("P1") AS OF SCN 123456 s WHERE a > :b1` and `SUBPARTITION ("SP1") AS OF SCN :scn_bind s` parse into canonical `exp.Table(..., partition=exp.Partition(subpartition=..., expressions=[...]), version=exp.Version(this="SCN", kind="AS OF", expression=...), alias=exp.TableAlias(...))` and render back to `SELECT /*+ FULL(s) */ a FROM "SH"."SALES" PARTITION("P1") AS OF SCN 123456 s WHERE a > :b1`.
   - **Important Transport Constraint**: `AS OF SCN <scn>` in `OffloadTransportOracleApi.get_snapshot_clause` and `get_transport_row_source_query` must remain an integer literal (`exp.Literal.number(int(transport_scn))`), not a bind variable, because DuckDB `oracle_query(...)` (`cofin/duckdb-oracle`) and Spark JDBC transport cannot bind parameters in extraction queries.
3. **Empirical Caveats on `sqlglot` Parse/Generate Round-Trips for Caller Expressions:**
   - **Oracle `TIMESTAMP(9)` and 3-Argument `TO_DATE`**: `sqlglot.parse_one(..., read="oracle").sql("oracle")` rewrites `TIMESTAMP '2015-07-01 00:00:00.123456789'` to `TO_TIMESTAMP('2015-07-01 00:00:00.123456789', 'YYYY-MM-DD HH24:MI:SS.FF6')` (truncating the format mask to `FF6` and raising `ORA-01830` at runtime) and drops the 3rd `NLS_CALENDAR` argument from `TO_DATE(' 2012-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')` (as emitted by Oracle partition `HIGH_VALUE` metadata).
   - **BigQuery Typed Literals**: `sqlglot.parse_one(..., read="bigquery").sql("bigquery")` rewrites `DATETIME '2020-01-01 00:00:00'`, `DATE '2020-01-01'`, `NUMERIC '1.23'`, and `BIGNUMERIC '1.23'` to `CAST('...' AS <TYPE>)`.
   - **Negative Positional Floats in `exp.Literal.number`**: `exp.Literal.number("-0.00000000000000000001")` converts the magnitude back to scientific notation `-1E-20`; use `exp.Literal(this=formatted, is_string=False)` to preserve `np.format_float_positional(val, trim="-")` output.
   - **Rule**: Construct table identifiers, column definitions, `PARTITION(...)`, `AS OF SCN`, and `OPTIONS(...)` via typed `sqlglot.exp` AST nodes, while embedding pre-formatted caller projections, casts, and validated `WHERE` filter expressions verbatim via `exp.Var(this=...)` / `exp.Paren(this=exp.Var(this=...))`. Use `sqlglot.parse` on raw filter strings strictly for read-only AST allowlist validation (`validate_where_clause` / `validate_filter_clause`) and return the validated stripped filter string without re-rendering through the generator.
   - **BigQuery `create_or_replace_ddl`**: In `BackendBigQueryApi.get_table_ddl(..., for_replace=True)` (`src/goe/offload/bigquery/bigquery_backend_api.py:1490-1497`), use `BigQuery().tokenize(ddl)` to verify leading `TokenType.CREATE` + `TokenType.TABLE` tokens and splice `OR REPLACE` at the token offset without re-parsing/re-rendering `INFORMATION_SCHEMA.TABLES.DDL`.
4. **Use `sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0` (Drop `mypyc` Extra).**
   - GOE uses only the `performance` extra group on `sqlspec`, not `mypyc`.
5. **Keep the Predicate DSL and Base Transformers Used by Non-Oracle/BigQuery Backends.**
   - Keep the public Lark grammar (`--offload-predicate`), `GenericPredicate.dsl`, and base classes in `src/goe/offload/predicate_offload.py` (`GenericPredicateToSQL`, `TypedPredicateToTemplate`, `TypedPredicateToLiterals`, `TypedPredicateToBinds`, which are still subclassed by `hadoop_predicate.py`, `synapse_predicate.py`, `snowflake_predicate.py`, and `teradata_predicate.py`).
   - Delete the superseded per-dialect classes in `src/goe/offload/oracle/oracle_predicate.py` (`GenericPredicateToOracleSQL`, `TypedPredicateToOracleLiteralTemplate`, `TypedPredicateToOracleBindTemplate`, `TypedPredicateToOracleLiterals`, `TypedPredicateToOracleBinds`) and `src/goe/offload/bigquery/bigquery_predicate.py` (`GenericPredicateToBigQuerySQL`, `TypedPredicateToBigQueryTemplate`, `TypedPredicateToBigQueryLiterals`), routing `oracle_predicate.py` and `bigquery_predicate.py` through `get_predicate_dialect_engine(...)`.

## 2. Custom Oracle Dialect Extension (`src/goe/offload/oracle/oracle_dialect.py`)

```python
# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from typing import Final
from sqlglot import exp
from sqlglot.dialects.oracle import Oracle
from sqlglot.generators.oracle import OracleGenerator
from sqlglot.parsers.oracle import OracleParser
from sqlglot.tokenizer_core import TokenType
from sqlspec.builder._generation import invalidate_generator_dispatch

_ORACLE_EXTENSIONS_REGISTERED_ATTR: Final[str] = "_goe_oracle_extensions_registered"


def register_oracle_dialect_extensions() -> None:
    """Register Oracle PARTITION/SUBPARTITION selection and AS OF SCN/TIMESTAMP flashback extensions."""
    if getattr(OracleParser, _ORACLE_EXTENSIONS_REGISTERED_ATTR, False):
        return
    Oracle.Tokenizer.KEYWORDS["SUBPARTITION"] = TokenType.PARTITION
    Oracle.ALIAS_POST_VERSION = True
    OracleParser.SUPPORTS_PARTITION_SELECTION = True
    OracleParser.VERSION_PHRASES = {
        **OracleParser.VERSION_PHRASES,
        ("AS", "OF", "SCN"): "SCN",
        ("AS", "OF", "TIMESTAMP"): "TIMESTAMP",
        ("VERSIONS", "SCN"): "SCN",
        ("VERSIONS", "TIMESTAMP"): "TIMESTAMP",
    }
    OracleGenerator.TRANSFORMS[exp.Version] = _oracle_version_sql
    invalidate_generator_dispatch(OracleGenerator)
    setattr(OracleParser, _ORACLE_EXTENSIONS_REGISTERED_ATTR, True)


def _oracle_version_sql(generator: OracleGenerator, expression: exp.Version) -> str:
    """Render Oracle Flashback Query AS OF {SCN | TIMESTAMP} and VERSIONS BETWEEN clauses."""
    this = expression.name.upper()
    kind = expression.text("kind").upper()
    expr_sql = generator.sql(expression, "expression")
    if this in {"SCN", "TIMESTAMP"} and kind == "AS OF":
        return f"AS OF {this} {expr_sql}"
    if this in {"SCN", "TIMESTAMP"} and kind == "BETWEEN":
        expr_node = expression.expression
        if isinstance(expr_node, exp.Tuple) and len(expr_node.expressions) == 2:
            start_sql = generator.sql(expr_node.expressions[0])
            end_sql = generator.sql(expr_node.expressions[1])
            return f"VERSIONS BETWEEN {this} {start_sql} AND {end_sql}"
    return f"FOR {this} {kind} {expr_sql}"
```

## 3. Capability Matrix for GOE Constructs

### 3.1 BigQuery DDL/DML Generation (`BigQuerySqlEngine`)

| Statement (GOE builder) | Round-trip | Notes |
|---|---|---|
| `CREATE OR REPLACE TABLE … (… BIGNUMERIC(38, 0), NUMERIC(38, 9) …) PARTITION BY DATE_TRUNC(\`D\`, MONTH) CLUSTER BY \`ID\`, \`AMT\` OPTIONS (kms_key_name='…', description='GOE')` | **Exact** | `exp.PartitionedByProperty`, `exp.Cluster`, `exp.Property` |
| `PARTITION BY RANGE_BUCKET(\`ID\`, GENERATE_ARRAY(0, 1000000, 1000))` | **Exact** | — |
| `PARTITION BY DATETIME_TRUNC(\`TS\`, YEAR)` | **Exact** | — |
| `CREATE EXTERNAL TABLE … OPTIONS (format='PARQUET', uris=[…], description=…)` | Semantically equal | Properly escapes `uris` list and string options |
| CTAS `CREATE TABLE … OPTIONS (…) AS SELECT … LIMIT n` | **Exact** | Preserves caller projections via `exp.Var` |
| `INSERT INTO … SELECT … WHERE \`D\` >= DATE '2020-01-01'` | **Exact** | Preserves caller casts and typed literals via `exp.Var` |
| `ALTER TABLE … ADD COLUMN …` | **Exact** | Accepts `(col_name, formatted_data_type)` pairs from `BackendBigQueryApi.add_columns` |
| `CREATE OR REPLACE VIEW … AS SELECT …` | **Exact** | Preserves joined `from_tables` and `WHERE` clauses |

### 3.2 Oracle Extraction Queries with `register_oracle_dialect_extensions()` (`OracleSqlEngine`)

| Extraction Construct (`oracle_offload_transport_rdbms_api.py`) | AST Representation | Round-trip |
|---|---|---|
| `"SH"."SALES" PARTITION("P1") AS OF SCN 123456 g` (`SPLIT_BY_PARTITION`) | `exp.Table(this="SALES", db="SH", partition=exp.Partition(expressions=[exp.Identifier(this="P1", quoted=True)]), version=exp.Version(this="SCN", kind="AS OF", expression=exp.Literal.number(123456)), alias=exp.TableAlias(this=exp.Identifier(this="g")))` | **Exact** |
| `"SH"."SALES" SUBPARTITION("SP1") AS OF SCN 123456 g` (`SPLIT_BY_SUBPARTITION`) | `exp.Table(..., partition=exp.Partition(subpartition=True, expressions=[...]), version=exp.Version(...))` | **Exact** |
| `SELECT /*+ NO_INDEX(g) USE_NL(g) LEADING(r) */ ... FROM "SH"."SALES" AS OF SCN 123456 g, TABLE(offload.offload_rowid_ranges(...)) r WHERE g.rowid BETWEEN CHARTOROWID(r.min_rowid_vc) AND CHARTOROWID(r.max_rowid_vc)` (`SPLIT_BY_EXTENT`) | `exp.Select` + `exp.Table(version=exp.Version(...))` | **Exact** |
| `SELECT g.*, MOD(ORA_HASH(col), 4) AS goe_batch FROM "SH"."SALES" AS OF SCN 123456 g` (`SPLIT_BY_MOD`) | `exp.Select` + `exp.Anonymous(this="MOD", ...)` | **Exact** |

### 3.3 Predicate Rendering & Nanosecond Fidelity (`PredicateSqlEngine`)

- `validate_where_clause` parses `SELECT 1 WHERE <clause>` via `sqlglot.parse` and verifies every node in `where_node.walk()` against a strict allowlist (forbidding `exp.Select`, `exp.Subquery`, `exp.Table`, `exp.SetOperation`, `exp.Exists`, `exp.DDL`, `exp.DML`, `exp.Command`, and non-allowlisted `exp.Anonymous` functions) while returning the stripped input string verbatim so 9-digit `TIMESTAMP '...'` and 3-arg `TO_DATE(...)` literals are never mutated.
- Inside `PredicateSqlEngine`:
  - Oracle `DATE` literal → `exp.Anonymous(this="TO_DATE", expressions=[exp.Literal.string(val), exp.Literal.string("YYYY-MM-DD HH24:MI:SS")])`
  - Oracle `TIMESTAMP` literal → `exp.Var(this=f"TIMESTAMP '{formatted_ns}'")` (preserving all 9 fractional nanosecond digits)
  - Oracle `TIMESTAMP` bind → `exp.Anonymous(this="TO_TIMESTAMP", expressions=[exp.Placeholder(this=bind_name), exp.Literal.string("YYYY-MM-DD HH24:MI:SS.FF9")])`
  - BigQuery literal → `BigQueryLiteral.format_literal` wrapped as `exp.Var`.
  - Numeric literal → `exp.Literal(this=formatted, is_string=False)` (preserving `np.format_float_positional(val, trim="-")` for negative decimals without `-1E-20` conversion).
