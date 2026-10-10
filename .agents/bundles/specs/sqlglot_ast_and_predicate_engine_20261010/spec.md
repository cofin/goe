---
type: Spec
flow_id: sqlglot_ast_and_predicate_engine_20261010
title: "Chapter 3.2: Pluggable SQL AST, Custom Oracle Dialect & Predicate Engine"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-10T16:35:00Z
description: "Introduce a library-agnostic SQL dialect and AST engine seam (src/goe/offload/sql_engine.py), a custom upstreamable Oracle dialect extension (src/goe/offload/oracle/oracle_dialect.py) for AS OF SCN and PARTITION/SUBPARTITION ASTs, and encapsulated sqlglot implementations for BigQuery DDL/DML, Oracle extraction queries, predicate rendering, and CrossDbValidator."
tags: [refactor, sqlglot, bigquery, oracle, predicates, validation, architecture]
parent_prd: prd_03_sqlspec_bigquery_and_duckdb_engine_20261010
research:
  - research/sql_generation_and_dialects.md
---

# Chapter 3.2: Pluggable SQL AST, Custom Oracle Dialect & Predicate Engine

## Specification

## 1. Objective & Scope

Replace string-concatenated and f-string-interpolated SQL construction across GOE's BigQuery backend DDL/DML path, Oracle RDBMS extraction row-source builder (`AS OF SCN`, `PARTITION`, `SUBPARTITION`), predicate offload rendering engine, and cross-database validation query builder with a **pluggable, library-agnostic SQL dialect/AST engine seam (`src/goe/offload/sql_engine.py`)** backed initially by `sqlglot`, while **aggressively deleting all superseded string-splicing builders and legacy predicate template classes**.

### Key Deliverables
1. **Pluggable SQL Engine Protocols & BigQuery Dialect Engine (`Task 1.1`)**:
   - Create `src/goe/offload/sql_engine.py` defining library-agnostic domain value objects and `typing.Protocol` interfaces (**zero `sqlglot` imports in `sql_engine.py`**):
     - `RenderedSQL(msgspec.Struct, frozen=True, kw_only=True)`: `sql: str`, `params: dict[str, Any] = msgspec.field(default_factory=dict)`
     - `ValidationQuerySpec(msgspec.Struct, frozen=True, kw_only=True)`: structured specification for cross-database aggregate validation queries.
     - `BigQueryDialectEngineProtocol(Protocol)`: methods (`partition_by_clause`, `properties_clause`, `create_table`, `create_external_table`, `ctas`, `insert_select`, `alter_add_columns`, `create_view`, `select_count`, `select_max`, `aggregate_select`) accepting pure GOE domain objects (`db_name`, `table_name`, `Sequence[ColumnMetadataInterface]`, partition/cluster specs, `options: Mapping[str, Any]`) and returning `str` — **never exposing `sqlglot.exp.Expr` in public signatures**.
     - `OracleExtractionQueryProtocol(Protocol)`: methods (`snapshot_scn_clause`, `iot_partition_clause`, `id_range_query`, `transport_row_source_query`, `parse_and_render`) for building and round-tripping Oracle Flashback (`AS OF SCN`) and `PARTITION` / `SUBPARTITION` extraction queries as `str` / `RenderedSQL`.
     - `PredicateDialectEngineProtocol(Protocol)`: `render_literal_sql(typed_tree: Any, columns: Sequence[ColumnMetadataInterface]) -> str`, `render_bind_sql(typed_tree: Any, columns: Sequence[ColumnMetadataInterface]) -> RenderedSQL`, and `validate_where_clause(raw_sql: str, dialect: str) -> str`.
     - `ValidationQueryEngineProtocol(Protocol)`: `build_aggregate_query(spec: ValidationQuerySpec) -> str` and `validate_filter_clause(raw_filter: str, dialect: str) -> str`.
   - Create `src/goe/offload/bigquery/bigquery_sql.py` encapsulating `BigQuerySqlEngine(BigQueryDialectEngineProtocol)` behind `get_bigquery_dialect_engine() -> BigQueryDialectEngineProtocol`.
   - Refactor `BackendBigQueryApi` in `src/goe/offload/bigquery/bigquery_backend_api.py` to call `get_bigquery_dialect_engine()` (**never importing `sqlglot` directly**) and **delete** the replaced raw f-string DDL/DML construction code (`_create_external_table` at `L255-258`, `_create_table_properties_clause` raw `OPTIONS` join at `L264-280`, `_gen_bigquery_create_table_sql_text` string builder at `L455-509`, and `re.sub(r"^CREATE TABLE", "CREATE OR REPLACE TABLE", ...)` at `L1493`).
2. **Custom Upstreamable Oracle Dialect Extension (`oracle_dialect.py`), Extraction ASTs & Pluggable Predicate Engine (`Task 1.2`)**:
   - Create `src/goe/offload/oracle/oracle_dialect.py` (modeled directly on `sqlspec.dialects.spanner` for future upstreaming to `sqlspec/dialects/oracle/`):
     - Implement `register_oracle_dialect_extensions()` registering `SUBPARTITION` (`TokenType.PARTITION`), `Oracle.ALIAS_POST_VERSION = True`, `OracleParser.SUPPORTS_PARTITION_SELECTION = True`, `OracleParser.VERSION_PHRASES` (`AS OF SCN`, `AS OF TIMESTAMP`, `VERSIONS SCN`, `VERSIONS TIMESTAMP`), and `_oracle_version_sql` on `OracleGenerator.TRANSFORMS[exp.Version]` with `sqlspec.builder._generation.invalidate_generator_dispatch(OracleGenerator)`.
     - Implement `OracleSqlEngine(OracleExtractionQueryProtocol)` and `get_oracle_dialect_engine() -> OracleExtractionQueryProtocol` constructing `exp.Table(..., partition=exp.Partition(...), version=exp.Version(this="SCN", kind="AS OF", expression=...), alias=exp.TableAlias(...))` ASTs for Oracle extraction queries.
   - Refactor `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py` (`L212-731`) to delegate `_get_iot_single_partition_clause`, `get_id_range`, `get_snapshot_clause`, and `get_transport_row_source_query` (`SPLIT_BY_PARTITION`, `SPLIT_BY_SUBPARTITION`, `SPLIT_BY_EXTENT`, `SPLIT_BY_MOD`, `SPLIT_BY_NATIVE_RANGE`, `SPLIT_BY_ID_RANGE`) to `get_oracle_dialect_engine()` (**deleting manual string-spliced `AS OF SCN` and `PARTITION (...)` query templates**).
   - Keep the public Lark DSL grammar (`src/goe/offload/predicate_offload.py:558-623`) and `GenericPredicate.dsl` round-trip behavior byte-identical, while updating `handle_parse_errors` (`L147-183`) for `lark` 1.x compatibility.
   - Implement `PredicateSqlEngine(PredicateDialectEngineProtocol)` and `get_predicate_dialect_engine(dialect: str) -> PredicateDialectEngineProtocol` in `src/goe/offload/predicate_offload.py`.
   - Refactor `src/goe/offload/oracle/oracle_predicate.py` (`L1-92`) and `src/goe/offload/bigquery/bigquery_predicate.py` (`L1-48`) to call `get_predicate_dialect_engine("oracle")` and `get_predicate_dialect_engine("bigquery")` (**zero `sqlglot` imports in `oracle_predicate.py` or `bigquery_predicate.py`**), preserving 9-digit nanosecond `FF9` precision on Oracle `TIMESTAMP` literals/binds and BigQuery typed literals, and **delete** the superseded `OraclePredicateTo*` / `TypedPredicateToOracle*` and `BigQueryPredicateTo*` / `TypedPredicateToBigQuery*` classes.
3. **Pluggable `ValidationQueryEngineProtocol` in `CrossDbValidator` (`Task 1.3`)**:
   - Implement `ValidationSqlEngine(ValidationQueryEngineProtocol)` and `get_validation_query_engine(dialect: str = "oracle") -> ValidationQueryEngineProtocol` in `src/goe/offload/offload_validation.py`.
   - Refactor `CrossDbValidator._construct_simple_agg_sql` (`src/goe/offload/offload_validation.py:397-444`), `_adjust_filters_front` (`L473-486`), and `_adjust_filters_back` (`L488-504`) to call `ValidationQueryEngineProtocol.validate_filter_clause` and `ValidationQueryEngineProtocol.build_aggregate_query(ValidationQuerySpec(...))` (**deleting the legacy raw string-splicing SQL builder** while preserving Oracle `AS OF SCN` and `/*+ PARALLEL(...) */` hints and exact column aliases).

---

## 2. Technical Architecture & Invariants

1. **Zero `sqlglot` Vendor Lock-In at Call Sites**:
   - `src/goe/offload/sql_engine.py` defines pure `typing.Protocol` interfaces and `msgspec.Struct` value objects (`RenderedSQL`, `ValidationQuerySpec`) with zero `sqlglot` imports.
   - `BackendBigQueryApi`, `OracleOffloadTransportRdbmsApi`, `oracle_predicate.py`, `bigquery_predicate.py`, and `CrossDbValidator` interact strictly with `BigQueryDialectEngineProtocol`, `OracleExtractionQueryProtocol`, `PredicateDialectEngineProtocol`, and `ValidationQueryEngineProtocol` returning `str` or `RenderedSQL`. Swapping `sqlglot` out in the future requires replacing only the adapter classes behind the factory functions.
2. **Custom Upstreamable Oracle Dialect Extension (`src/goe/offload/oracle/oracle_dialect.py`)**:
   - Modeled directly on `sqlspec.dialects.spanner` so it can be upstreamed to `sqlspec/dialects/oracle/`, `register_oracle_dialect_extensions()` enables lossless AST parsing and generation of `PARTITION("P1")`, `SUBPARTITION("SP1")`, `AS OF SCN <scn>`, `AS OF TIMESTAMP <expr>`, and `VERSIONS BETWEEN SCN <low> AND <high>` via `exp.Table(partition=exp.Partition(...), version=exp.Version(...))`.
3. **Aggressive Dead-Code Removal**:
   - Delete raw string-spliced DDL/DML construction and `re.sub(r"^CREATE TABLE", ...)` in `src/goe/offload/bigquery/bigquery_backend_api.py`.
   - Delete manual string-spliced `AS OF SCN` / `PARTITION (...)` extraction query builders in `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py`.
   - Delete `OraclePredicateToTemplate`, `OraclePredicateToSql`, `OraclePredicateToLiteralSql`, `TypedPredicateToOracleTemplate`, `TypedPredicateToOracleLiterals`, `TypedPredicateToOracleBinds` in `src/goe/offload/oracle/oracle_predicate.py` and `BigQueryPredicateToTemplate`, `BigQueryPredicateToSql`, `TypedPredicateToBigQueryTemplate`, `TypedPredicateToBigQueryLiterals` in `src/goe/offload/bigquery/bigquery_predicate.py`.
   - Delete raw string-spliced `SELECT ... FROM ... WHERE ... GROUP BY ... ORDER BY ...` construction in `src/goe/offload/offload_validation.py`.
4. **Type Authority & Nanosecond Invariants Inside the SQL Engine Adapters**:
   - Never call `sqlglot.transpile(..., read="oracle", write="bigquery")` or run `qualify` / `optimize` on DDL or validation queries.
   - Construct Oracle `TIMESTAMP(9)` literals (`TIMESTAMP 'YYYY-MM-DD HH:MM:SS.fffffffff'`) and binds (`TO_TIMESTAMP(:bind, 'YYYY-MM-DD HH24:MI:SS.FF9')`) directly from `numpy.datetime64` formatting without parsing through `sqlglot.parse_one`.

---

## 3. Task Breakdown & File Ownership

| Task ID | Title | Strategy | Depends On | Files Owned | Tests Owned |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `1.1` | Define `sql_engine.py` protocols, implement `BigQuerySqlEngine`, and refactor `BackendBigQueryApi` | `behavior_tdd` | `[]` | `src/goe/offload/sql_engine.py`, `src/goe/offload/bigquery/bigquery_sql.py`, `src/goe/offload/bigquery/bigquery_backend_api.py` | `tests/unit/offload/bigquery/test_bigquery_sql.py` |
| `1.2` | Implement `oracle_dialect.py` (`AS OF SCN`/`PARTITION`), `PredicateSqlEngine`, and refactor Oracle/BigQuery extraction and predicate modules | `behavior_tdd` | `["sqlglot_ast_and_predicate_engine_20261010:1.1"]` | `src/goe/offload/oracle/oracle_dialect.py`, `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py`, `src/goe/offload/predicate_offload.py`, `src/goe/offload/oracle/oracle_predicate.py`, `src/goe/offload/bigquery/bigquery_predicate.py` | `tests/unit/offload/oracle/test_oracle_dialect.py`, `tests/unit/offload/test_predicate_offload.py` |
| `1.3` | Implement `ValidationSqlEngine` and modernize `CrossDbValidator` in `offload_validation.py` | `behavior_tdd` | `["sqlglot_ast_and_predicate_engine_20261010:1.2"]` | `src/goe/offload/offload_validation.py` | `tests/unit/offload/test_offload_validation.py` |

## Implementation Plan

- [ ] 1.1 Create `src/goe/offload/sql_engine.py` (`RenderedSQL`, `ValidationQuerySpec`, `BigQueryDialectEngineProtocol`, `OracleExtractionQueryProtocol`, `PredicateDialectEngineProtocol`, `ValidationQueryEngineProtocol`), implement `BigQuerySqlEngine` in `src/goe/offload/bigquery/bigquery_sql.py`, refactor `BackendBigQueryApi` (`src/goe/offload/bigquery/bigquery_backend_api.py`) to use the protocol and delete legacy string-splicing DDL/DML code, and verify in `tests/unit/offload/bigquery/test_bigquery_sql.py`.
- [ ] 1.2 Create `src/goe/offload/oracle/oracle_dialect.py` (`register_oracle_dialect_extensions`, `OracleSqlEngine`), refactor `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py` (`AS OF SCN` and `PARTITION`/`SUBPARTITION` ASTs), implement `PredicateSqlEngine` in `src/goe/offload/predicate_offload.py`, refactor `oracle_predicate.py` and `bigquery_predicate.py` while deleting superseded `TypedPredicateToOracle*` / `TypedPredicateToBigQuery*` classes, and verify in `tests/unit/offload/oracle/test_oracle_dialect.py` and `tests/unit/offload/test_predicate_offload.py`.
- [ ] 1.3 Implement `ValidationSqlEngine` in `src/goe/offload/offload_validation.py`, refactor `CrossDbValidator` to validate `--filters` and build aggregate queries via `ValidationQueryEngineProtocol` while deleting raw string-splicing SQL assembly, and verify in `tests/unit/offload/test_offload_validation.py`.

## Continuity Snapshot

- **Current State**: Planned (`plan_revision: 1`).
- **Next Action**: Execute Task `1.1` (`sqlglot_ast_and_predicate_engine_20261010:1.1`).
