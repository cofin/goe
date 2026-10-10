---
type: Research
title: SQL Generation & Dialect Management (Pluggable Dialect Seam + Custom Oracle Dialect over sqlglot) for GOE
description: Evaluates sqlglot and polyglot-sql for GOE, specifies a library-agnostic Protocol seam (src/goe/offload/sql_engine.py) without vendor lock-in, and documents a custom upstreamable Oracle dialect extension (src/goe/offload/oracle/oracle_dialect.py) for AS OF SCN and PARTITION/SUBPARTITION AST parsing and generation.
tags: [research, sql, sqlglot, dialects, oracle, bigquery, architecture]
created_at: 2026-10-10T15:55:00Z
---

# SQL Generation & Dialect Management (Pluggable Dialect Seam + Custom Oracle Dialect over sqlglot) for GOE

## 1. Executive Summary

**Recommendation: define a library-agnostic SQL dialect & AST engine seam (`src/goe/offload/sql_engine.py`) using `typing.Protocol` interfaces and `msgspec.Struct` value objects, backed initially by `sqlglot` as an encapsulated implementation detail, and register a custom upstreamable Oracle dialect extension (`src/goe/offload/oracle/oracle_dialect.py`) for `AS OF SCN` and `PARTITION` / `SUBPARTITION` AST construction. Do not leak `sqlglot.exp` types to callers. Do not use Oracle→BigQuery transpilation.**

1. **Encapsulate `sqlglot` behind a pluggable `Protocol` seam (No Vendor Lock-In).**
   - Callers (`BackendBigQueryApi`, `OracleOffloadTransportRdbmsApi`, `oracle_predicate.py`, `bigquery_predicate.py`, `CrossDbValidator`) must **never import `sqlglot` or `sqlglot.exp` directly**.
   - Instead, `src/goe/offload/sql_engine.py` defines:
     - `RenderedSQL(msgspec.Struct, frozen=True)`: `sql: str`, `params: dict[str, Any] = {}`
     - `ValidationQuerySpec(msgspec.Struct, frozen=True)`: domain specification for cross-DB aggregate validation queries.
     - `BigQueryDialectEngineProtocol(Protocol)`: methods (`partition_by_clause`, `properties_clause`, `create_table`, `create_external_table`, `ctas`, `insert_select`, `alter_add_columns`, `create_view`, `select_count`, `select_max`, `aggregate_select`) accepting pure GOE domain parameters and returning `str`.
     - `OracleExtractionQueryProtocol(Protocol)`: methods (`snapshot_scn_clause`, `iot_partition_clause`, `id_range_query`, `transport_row_source_query`, `parse_and_render`) building and round-tripping Oracle extraction queries (`PARTITION("P1")`, `SUBPARTITION("SP1")`, `AS OF SCN <scn>`, `TABLE(offload.offload_rowid_ranges(...))`, `MOD(ORA_HASH(...))`) and returning `str` or `RenderedSQL`.
     - `PredicateDialectEngineProtocol(Protocol)`: `render_literal_sql`, `render_bind_sql`, and `validate_where_clause`.
     - `ValidationQueryEngineProtocol(Protocol)`: `build_aggregate_query(spec: ValidationQuerySpec) -> str` and `validate_filter_clause(raw_filter: str, dialect: str) -> str`.
2. **Custom Temporary Oracle Dialect Extension (`src/goe/offload/oracle/oracle_dialect.py`) for Future Upstreaming to `sqlspec`:**
   - Although stock `sqlglot.dialects.oracle.Oracle` does not enable `SUPPORTS_PARTITION_SELECTION` or `AS OF SCN` / `VERSIONS BETWEEN` out of the box, registering targeted extensions on `Oracle`, `OracleParser`, and `OracleGenerator` (modeled directly on `sqlspec.dialects.spanner`) yields **100% lossless AST round-trip parsing and generation**:
     - `Oracle.Tokenizer.KEYWORDS["SUBPARTITION"] = TokenType.PARTITION`
     - `Oracle.ALIAS_POST_VERSION = True`
     - `OracleParser.SUPPORTS_PARTITION_SELECTION = True`
     - `OracleParser.VERSION_PHRASES` extended with `("AS", "OF", "SCN"): "SCN"`, `("AS", "OF", "TIMESTAMP"): "TIMESTAMP"`, `("VERSIONS", "SCN"): "SCN"`, `("VERSIONS", "TIMESTAMP"): "TIMESTAMP"`
     - `OracleGenerator.TRANSFORMS[exp.Version] = _oracle_version_sql` + `invalidate_generator_dispatch(OracleGenerator)`
   - Verified empirically in `.venv` (`sqlglot` 30.17.0 + `sqlspec`):
     - `SELECT /*+ FULL(s) */ a FROM "SH"."SALES" PARTITION ("P1") AS OF SCN 123456 s WHERE a > :b1` and `SUBPARTITION ("SP1") AS OF SCN :scn_bind s` parse into canonical `exp.Table(..., partition=exp.Partition(subpartition=..., expressions=[...]), version=exp.Version(this="SCN", kind="AS OF", expression=...), alias=exp.TableAlias(...))` and render back to `SELECT /*+ FULL(s) */ a FROM "SH"."SALES" PARTITION("P1") AS OF SCN 123456 s WHERE a > :b1`!
3. **Use `sqlspec[performance,oracledb,adbc,duckdb]>=0.61.0` (Drop `mypyc` Extra).**
   - GOE uses only the `performance` extra group on `sqlspec`, not `mypyc`.
4. **Oracle→BigQuery transpilation is not safe for GOE.**
   - `NUMBER(38,0)` becomes `NUMERIC` (loses `BIGNUMERIC` promotion).
   - `TIMESTAMP(9)` becomes `DATETIME` (drops precision).
   - `TO_TIMESTAMP(… 'FF9')` becomes `PARSE_TIMESTAMP('%F %T.FF9', …)` (invalid BigQuery format).
   - GOE's own canonical type mapping remains authoritative.
5. **Keep the predicate DSL. Replace its per-dialect string renderers with `PredicateDialectEngineProtocol`.**
   - Keep the public Lark grammar (`--offload-predicate`) and persisted `GenericPredicate.dsl` unchanged.
   - Delete the superseded per-dialect template/literal/bind classes (`TypedPredicateToOracle*`, `OraclePredicateTo*`, `TypedPredicateToBigQuery*`, `BigQueryPredicateTo*`) in `oracle_predicate.py` and `bigquery_predicate.py`.

## 2. Custom Oracle Dialect Extension (`src/goe/offload/oracle/oracle_dialect.py`)

```python
# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from typing import Final
from sqlglot import exp
from sqlglot.dialects.oracle import Oracle
from sqlglot.generators.oracle import OracleGenerator
from sqlglot.parsers.oracle import OracleParser
from sqlglot.tokens import TokenType
from sqlspec.builder._generation import invalidate_generator_dispatch

_ORACLE_EXTENSIONS_REGISTERED_ATTR: Final[str] = "_goe_oracle_extensions_registered"


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
```

## 3. Capability Matrix for GOE Constructs

### 3.1 BigQuery DDL/DML Generation (`BigQuerySqlEngine`)

| Statement (GOE builder) | Round-trip | Notes |
|---|---|---|
| `CREATE OR REPLACE TABLE … (… BIGNUMERIC(38, 0), NUMERIC(38, 9) …) PARTITION BY DATE_TRUNC(\`D\`, MONTH) CLUSTER BY \`ID\`, \`AMT\` OPTIONS (kms_key_name='…', description='GOE')` | **Exact** | `exp.PartitionedByProperty`, `exp.Cluster`, `exp.Property` |
| `PARTITION BY RANGE_BUCKET(\`ID\`, GENERATE_ARRAY(0, 1000000, 1000))` | **Exact** | — |
| `PARTITION BY DATETIME_TRUNC(\`TS\`, YEAR)` | **Exact** | — |
| `CREATE EXTERNAL TABLE … OPTIONS (format='PARQUET', uris=[…], description=…)` | Semantically equal | Properly escapes `uris` list and string options |
| CTAS `CREATE TABLE … OPTIONS (…) AS SELECT … LIMIT n` | **Exact** | — |
| `INSERT INTO … SELECT … WHERE \`D\` >= DATE '2020-01-01'` | Semantically equal | — |
| `ALTER TABLE … ADD COLUMN …` | **Exact** | — |
| `CREATE VIEW … AS SELECT …` | **Exact** | — |

### 3.2 Oracle Extraction Queries with `register_oracle_dialect_extensions()` (`OracleSqlEngine`)

| Extraction Construct (`oracle_offload_transport_rdbms_api.py`) | AST Representation | Round-trip |
|---|---|---|
| `"SH"."SALES" PARTITION("P1") AS OF SCN 123456 g` (`SPLIT_BY_PARTITION`) | `exp.Table(this="SALES", db="SH", partition=exp.Partition(expressions=[exp.Identifier(this="P1", quoted=True)]), version=exp.Version(this="SCN", kind="AS OF", expression=exp.Literal.number(123456)), alias=exp.TableAlias(this=exp.Identifier(this="g")))` | **Exact** |
| `"SH"."SALES" SUBPARTITION("SP1") AS OF SCN 123456 g` (`SPLIT_BY_SUBPARTITION`) | `exp.Table(..., partition=exp.Partition(subpartition=True, expressions=[...]), version=exp.Version(...))` | **Exact** |
| `SELECT /*+ NO_INDEX(g) USE_NL(g) LEADING(r) */ ... FROM TABLE(offload.offload_rowid_ranges(...)) r, "SH"."SALES" AS OF SCN 123456 g WHERE g.rowid BETWEEN r.lo_rid AND r.hi_rid` (`SPLIT_BY_EXTENT`) | `exp.Select(hint=exp.Hint(...))` + `exp.Table(version=exp.Version(...))` | **Exact** |
| `WHERE MOD(ORA_HASH("ID"), 4) = 0` (`SPLIT_BY_MOD`) | `exp.EQ(this=exp.Anonymous(this="MOD", expressions=[exp.Anonymous(this="ORA_HASH", ...), ...]), ...)` | **Exact** |

### 3.3 Predicate Rendering & Nanosecond Fidelity (`PredicateSqlEngine`)

- `sqlglot.condition(...)` plus a strict AST node allowlist catches disallowed SQL such as subqueries (`a = 1 OR (SELECT COUNT(*) FROM dba_users) > 0`).
- Inside `PredicateSqlEngine`:
  - Oracle `DATE` literal → `exp.Anonymous(this="TO_DATE", expressions=[exp.Literal.string(val), exp.Literal.string("YYYY-MM-DD HH24:MI:SS")])`
  - Oracle `TIMESTAMP` literal → `exp.Var(this=f"TIMESTAMP '{formatted_ns}'")` (preserving all 9 fractional nanosecond digits without parsing through `sqlglot.parse_one`, which truncates to `FF6`)
  - Oracle `TIMESTAMP` bind → `exp.Anonymous(this="TO_TIMESTAMP", expressions=[exp.Placeholder(this=bind_name), exp.Literal.string("YYYY-MM-DD HH24:MI:SS.FF9")])`
  - BigQuery literal → `BigQueryLiteral.format_literal` wrapped as `exp.Var` / `exp.Literal`.
