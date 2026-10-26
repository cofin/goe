---
type: Spec
flow_id: native_sqlglot_dialect_engine_20261024
title: "Chapter 7.1: Native SQLGlot Dialect Engine"
state: completed
plan_revision: 1
plan_commit: null
state_revision: 2
current_task: null
last_operation: finish
operation_targets: []
last_verified_checkpoint: "1.2"
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-25T17:54:00Z
description: "Replace the monkey-patched Oracle dialect and the separate Oracle and BigQuery SQL engines with one DialectSqlEngine built on native sqlglot 30.24 generation, preserving every generated string byte for byte."
tags: [refactor, sqlglot, oracle, bigquery]
parent_prd: prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024
depends_on: [prd_05_foundation_typing_settings_and_adapter_reduction_20261024, prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024]
research:
  - .agents/bundles/specs/prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 7.1: Native SQLGlot Dialect Engine

## Specification

### 1. Overview and Goals

GOE currently generates Oracle extraction SQL through `OracleSqlEngine` in `src/goe/offload/oracle/oracle_dialect.py`, which first mutates the global `sqlglot` Oracle tokenizer, parser, and generator (`register_oracle_dialect_extensions()`) and imports the private `sqlspec.builder._generation` module. BigQuery DDL and DML come from a second engine, `BigQuerySqlEngine` in `src/goe/offload/bigquery/bigquery_sql.py`. This chapter:

1. Adds `DialectSqlEngine` (`src/goe/offload/sql_ast/dialect_engine.py`), one AST builder with a dialect argument (`oracle`, `bigquery`, `snowflake`, `tsql`, `hive`, `spark`) that ports every `OracleSqlEngine` and `BigQuerySqlEngine` method with byte-identical output and adds the multi-dialect `ALTER TABLE` builders that Chapter 7.4 schema sync consumes.
2. Moves every engine call site to `DialectSqlEngine`, deletes `oracle_dialect.py` (including all monkey-patching and the private `sqlspec.builder._generation` import) and `bigquery_sql.py`, and replaces the two engine protocols in `src/goe/offload/sql_engine.py` with one `DialectSqlEngineProtocol`. `sql_engine.py` stays free of `sqlglot` imports.

### 2. Code Analysis Summary

- `src/goe/offload/oracle/oracle_dialect.py:30-47` `register_oracle_dialect_extensions()` sets `Oracle.Tokenizer.KEYWORDS["SUBPARTITION"]`, `Oracle.ALIAS_POST_VERSION`, `OracleParser.SUPPORTS_PARTITION_SELECTION`, `OracleParser.VERSION_PHRASES`, replaces `OracleParser._parse_version` (`:347-361`) and `OracleGenerator.TRANSFORMS[exp.Version]` (`:364-377`), and calls the private `sqlspec.builder._generation.invalidate_generator_dispatch` imported at `:17`. `OracleSqlEngine` (`:50-338`) builds extraction SQL; `get_oracle_dialect_engine()` is at `:341-344`.
- Verified in `.venv` (`sqlglot==30.24.0`, pure Python, no `sqlglotc` installed; `sqlspec==0.68.0` builder modules are mypyc-compiled `.so` files): without the patch, `sqlglot/parsers/oracle.py` already sets `SUPPORTS_PARTITION_SELECTION = True`, `sqlglot/dialects/oracle.py` sets `ALIAS_POST_VERSION = True`, the tokenizer maps `SUBPARTITION` to `TokenType.PARTITION`, and `VERSION_PHRASES` contains `("AS", "OF", "SCN")` and `("AS", "OF", "TIMESTAMP")`. Native and patched output are identical for every production shape (probe compared both in separate processes):
  - `SELECT "A" FROM "OWN"."T" PARTITION ("P1") AS OF SCN :scn t_alias` renders `SELECT "A" FROM "OWN"."T" PARTITION("P1") AS OF SCN :scn t_alias` (the generator drops the space before `(`; the current test at `tests/unit/offload/oracle/test_oracle_dialect.py:45` already expects `PARTITION("P1")`).
  - `SELECT "A" FROM "OWN"."T" SUBPARTITION ("SP1") AS OF SCN :scn t_alias` renders `SELECT "A" FROM "OWN"."T" SUBPARTITION("SP1") AS OF SCN :scn t_alias`.
  - `SELECT "A" FROM "OWN"."T" AS OF TIMESTAMP TO_TIMESTAMP('2024-01-01 10:11:12.123456789', 'YYYY-MM-DD HH24:MI:SS.FF9') g` round-trips unchanged.
  - The only shape lost is `VERSIONS BETWEEN SCN 100 AND 200` (native raises `ParseError`); it appears only in `tests/unit/offload/oracle/test_oracle_dialect.py:54-56`, never in `src/`.
- `src/goe/offload/bigquery/bigquery_sql.py:49-369` `BigQuerySqlEngine` (`partition_by_clause`, `properties_clause`, `create_table`, `create_external_table`, `create_or_replace_ddl`, `ctas`, `insert_select`, `alter_add_columns`, `create_view`); `get_bigquery_dialect_engine()` at `:372-375`. Exact current outputs were captured for every method (see task 1.1); `sqlglot` escapes `'` in BigQuery strings as `\'` (`description='o\'brien'`).
- Call sites: `src/goe/offload/bigquery/bigquery_backend_api.py:55` import and `:204, :455, :786, :825, :842, :965, :1819, :1849, :2071`; `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py:48` import and `:129, :414, :452, :915`; `register_oracle_dialect_extensions` imports and calls in `src/goe/offload/predicate_offload.py:107, :689, :838` and `src/goe/offload/offload_validation.py:39, :109, :118`.
- `src/goe/offload/sql_engine.py:44-252` defines `BigQueryDialectEngineProtocol` and `OracleExtractionQueryProtocol`; `RenderedSQL`, `ValidationQuerySpec`, `PredicateDialectEngineProtocol`, and `ValidationQueryEngineProtocol` stay for Chapters 7.2 and 7.3.
- Verified `sqlglot` behaviors the new builders rely on: `exp.Alter(..., actions=[exp.ColumnDef(..., exists=True)])` renders `ADD COLUMN IF NOT EXISTS` on BigQuery; `exp.AlterColumn(this=col, dtype=...)` renders `ALTER COLUMN "C" SET DATA TYPE <type>` on BigQuery and Snowflake; `exp.AlterColumn(this=col, drop=True, allow_null=True)` renders `ALTER COLUMN "C" DROP NOT NULL` (`sqlglot/generator.py:4369-4377`); `allow_null=True` without `drop` renders `SET NOT NULL`, and `exp.Drop(this=table, kind="TABLE", exists=True)` renders `DROP TABLE IF EXISTS` without the table name, so neither form is used.
- Tests: `tests/unit/offload/oracle/test_oracle_dialect.py` (116 LOC), `tests/unit/offload/bigquery/test_bigquery_sql.py` (221 LOC), `tests/unit/offload/test_sql_engine.py` (63 LOC), golden `tests/unit/characterization/test_offload_bigquery_golden.py` (`:110-116`, `:181`, `:212-215`, `:306-310` depend on BigQuery engine output).

### 3. Requirements

- R1. `DialectSqlEngine` reproduces every current `OracleSqlEngine` and `BigQuerySqlEngine` output byte for byte, using stock `sqlglot` nodes only (no subclassing of `sqlglot` classes, no mutation of dialect classes, no private `sqlspec` imports).
- R2. Oracle `PARTITION`, `SUBPARTITION`, `AS OF SCN` (literal and bind placeholder), and `AS OF TIMESTAMP` parse and render natively with the alias after the version clause; exact strings are pinned in tests.
- R3. `DialectSqlEngine.alter_add_columns`, `alter_column_set_data_type`, and `alter_column_drop_not_null` render dialect-correct DDL; unsupported dialect and method combinations raise `DialectNotSupportedError` with a message naming the method and dialect.
- R4. `register_oracle_dialect_extensions()`, `_parse_oracle_version()`, `_oracle_version_sql()`, the private `sqlspec.builder._generation` import, `oracle_dialect.py`, and `bigquery_sql.py` are deleted; every call site uses `goe.offload.sql_ast.dialect_engine.get_dialect_engine`.
- R5. `src/goe/offload/sql_engine.py` exposes `DialectSqlEngineProtocol` (runtime checkable) instead of `BigQueryDialectEngineProtocol` and `OracleExtractionQueryProtocol`, and imports no `sqlglot` symbol.
- R6. The BigQuery golden characterization suite and all transport and backend unit tests stay green without expectation changes.
- R7 (risk). Global `sqlglot` state: removing the patch must not change any other generated SQL. Mitigation: the probe proved identical output; task 1.2 runs the full offload, characterization, and transport suites.
- R8 (risk). `VERSIONS BETWEEN` support is dropped. Mitigation: no production caller exists; the test case is deleted with its file and recorded in task 1.2 notes.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| --- | --- | --- |
| R1 | 1.1 | `tests/unit/offload/sql_ast/test_dialect_engine.py` exact-string tests per ported method |
| R2 | 1.1 | `test_native_oracle_round_trip_*` tests |
| R3 | 1.1 | `test_alter_*` tests including `DialectNotSupportedError` cases |
| R4 | 1.2 | `git ls-files` absence check, `uv run python tools/verify_architecture.py`, full `tests/unit/offload` run |
| R5 | 1.2 | `tests/unit/offload/test_sql_engine.py` protocol tests |
| R6 | 1.2 | `tests/unit/characterization/test_offload_bigquery_golden.py` unchanged and green |
| R7 | 1.2 | `uv run pytest tests/unit -q` |
| R8 | 1.2 | Notes entry plus `git grep -n "VERSIONS BETWEEN" -- src` returning nothing |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/sql_ast tests/unit/offload/test_sql_engine.py tests/unit/characterization -q
uv run pytest tests/unit/offload -q
uv run ruff format --check src/goe/offload tests/unit/offload
uv run ruff check src/goe/offload tests/unit/offload
uv run mypy src/goe
uv run python tools/verify_architecture.py
git grep -n -E "register_oracle_dialect_extensions|sqlspec.builder._generation|OracleSqlEngine|BigQuerySqlEngine|get_oracle_dialect_engine|get_bigquery_dialect_engine" -- src tests
uv run pytest tests/unit -q
```

The `git grep` command must print nothing.

## Implementation Plan

### Phase 1: Engine and Cutover
- [x] 1.1 Build DialectSqlEngine on native sqlglot generation ([tasks/1.1.md](tasks/1.1.md))
- [x] 1.2 Move engine call sites to DialectSqlEngine and delete the Oracle monkey patch ([tasks/1.2.md](tasks/1.2.md))

## Continuity Snapshot

- **Flow / lifecycle**: `native_sqlglot_dialect_engine_20261024`, `completed`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: `1.2` (`pytest`, `ruff`, `mypy`, `tools/verify_architecture.py`).
- **Decisions**: one engine class with a dialect argument instead of one class per dialect; Oracle-only and BigQuery-only methods raise `DialectNotSupportedError` for other dialects; `get_dialect_engine()` is `lru_cache`d per dialect; the chapter has two tasks because every engine file may appear in only one task and the new module must land before the cutover deletes the old engines; the sqlglot import boundary is enforced by the Chapter 5.2 architecture gate, so the AST source-scanner tests in the deleted test files are not ported.
- **Discoveries**: `TableRef(FrozenBaseStruct, frozen=True)` requires explicit `frozen=True` on `msgspec.Struct` subclasses under `mypy` to avoid `Non-frozen dataclass cannot inherit from a frozen dataclass [misc]`.
- **Blockers**: none.
- **Next exact step**: completed.
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 2`.
- **Relevant knowledge**: `.agents/bundles/knowledge/standards/database-and-sql.md`, `.agents/bundles/knowledge/frontends/oracle.md`, `.agents/bundles/knowledge/backends/bigquery.md`.
