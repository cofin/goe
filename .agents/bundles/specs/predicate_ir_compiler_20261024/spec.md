---
type: Spec
flow_id: predicate_ir_compiler_20261024
title: "Chapter 7.2: PredicateIR Compiler"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T16:45:00Z
description: "Replace the Lark predicate transformer pipeline and per-dialect literal/predicate classes with an immutable msgspec PredicateExpr AST, sqlglot-backed parser, and cached multi-dialect PredicateCompiler."
tags:
  - refactor
  - sqlglot
  - predicates
  - msgspec
parent_prd: prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024
depends_on:
  - native_sqlglot_dialect_engine_20261024
research:
  - .agents/bundles/specs/prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 7.2: PredicateIR Compiler

## Specification

### 1. Overview and Goals

GOE currently parses offload predicates in `src/goe/offload/predicate_offload.py` (868 LOC) through a multi-stage Lark `Tree` and `Transformer` pipeline (`RawToInternalAST` -> `GenericPredicateToTyped` -> `InsertSyntheticPartitionClauses` -> `TypedPredicateToTemplate` / `TypedPredicateToLiterals` / `TypedPredicateToBinds` / `_TypedPredicateToAst`) paired with per-backend `*_predicate.py` and `*_literal.py` modules. In `RawToInternalAST.decimal_value` (`predicate_offload.py:320-321`), decimal literals are converted via `float(value)`, silently corrupting 16-to-38-digit Oracle `NUMBER` and BigQuery `NUMERIC`/`BIGNUMERIC` values. This chapter:

1. Introduces `src/goe/offload/predicates/ast.py` defining `PredicateExpr`, a `msgspec` tagged union of `FrozenBaseStruct` nodes (`LogicalAnd`, `LogicalOr`, `LogicalNot`, `BinaryComparison`, `InListPredicate`, `NullCheckPredicate`, `ColumnRef`, `LiteralValue` with `TypedValue` preserving exact `Decimal`, `int`, `float`, `str`, `bytes`, `date`, `datetime`, and `np.datetime64` nanosecond resolution).
2. Introduces `src/goe/offload/predicates/parser.py` (`parse_predicate_dsl` and `parse_safe_sql_predicate`) using `sqlglot.parse_one` to parse the persisted GOE predicate DSL (`column(...)`, `numeric(...)`, `string(...)`, `datetime(...)`, `literal(...)`) and raw SQL `WHERE` filters directly into `PredicateExpr`, validating column types against `FrontendTable.columns` / `ColumnMetadataInterface` and expanding synthetic partition clauses without Lark `Transformer` mutation.
3. Introduces `src/goe/offload/predicates/compiler.py` (`PredicateCompiler.to_sqlglot(expr, dialect)` and `render_predicate(expr, dialect, bind_style)`) emitting dialect-accurate `sqlglot` ASTs, literal SQL, and parameterized `RenderedSQL` across `oracle`, `bigquery`, `snowflake`, `tsql`, `hive`, `spark`, and `duckdb`, memoized in `sqlspec.core.NamespacedCache`.
4. Rewires `src/goe/offload/predicate_offload.py` into a compact facade over `goe.offload.predicates`, updates all frontend and backend predicate callers, and removes `lark` from `pyproject.toml`.

### 2. Code Analysis Summary

- `src/goe/offload/predicate_offload.py:200-256`: `GenericPredicate` wraps a mutable Lark `Tree` (`self.ast`), exposing `.dsl`, `.alias_column_names()`, `.column_names()`, `.rename_column()`, and `.set_column_alias()`.
- `src/goe/offload/predicate_offload.py:320-321`: `RawToInternalAST.decimal_value` converts `SIGNED_DECIMAL` tokens with `float(value)`, losing precision beyond 53 bits (15–17 decimal digits).
- `src/goe/offload/predicate_offload.py:324-406`: `GenericPredicateToTyped` validates column names and data type compatibility (`is_number_based()`, `is_date_based()`, `is_string_based()`, `valid_for_offload_predicate()`) and mutates token payloads in place into `(value, data_type)` tuples.
- `src/goe/offload/predicate_offload.py:517-575`: `InsertSyntheticPartitionClauses` appends synthetic partition comparisons (`AND (<synth_col> <op> <synth_val>)`) using `SyntheticPartitionLiteral.gen_synthetic_literal`.
- `src/goe/offload/predicate_offload.py:683-705`: `parse_safe_sql_predicate` validates raw SQL `WHERE` clauses with `sqlglot.parse` and calls `register_oracle_dialect_extensions()` (removed in Chapter 7.1).
- `src/goe/offload/predicate_offload.py:707-868`: `_TypedPredicateToAst` and `PredicateSqlEngine` only support `oracle` and `bigquery` in `datetime_value` (`:819` raises `PredicateOffloadException("Unsupported predicate dialect: ...")` for `snowflake`, `tsql`, `hive`, `spark`, and `duckdb`), forcing those backends to keep separate Lark `Transformer` subclasses in `src/goe/offload/snowflake/snowflake_predicate.py`, `src/goe/offload/microsoft/synapse_predicate.py`, `src/goe/offload/hadoop/hadoop_predicate.py`, and `src/goe/offload/spark/spark_thrift_predicate.py`.
- `git grep -n "import lark\|from lark"` across `src/` shows `src/goe/offload/predicate_offload.py` is the only module in the repository that imports `lark`.

### 3. Requirements

- R1. `src/goe/offload/predicates/ast.py` defines immutable `FrozenBaseStruct` AST nodes (`ColumnRef`, `TypedValue`, `LiteralValue`, `BinaryComparison`, `InListPredicate`, `NullCheckPredicate`, `LogicalAnd`, `LogicalOr`, `LogicalNot`, and `PredicateExpr` union) plus functional tree transforms (`column_names`, `alias_column_names`, `rename_column`, `with_column_alias`, `to_dsl`) that preserve exact 38-to-76-digit `Decimal` strings and 9-digit nanosecond timestamps.
- R2. `src/goe/offload/predicates/parser.py` implements `@lru_cache(maxsize=2048)` `parse_predicate_dsl(dsl_str)` and `resolve_predicate_types(expr, columns, include_synthetic=True)` using `sqlglot.parse_one` with zero `lark` dependency, raising `OptionValueError` with the expected syntax and type-compatibility diagnostics when columns are missing or compared against incompatible literal kinds.
- R3. `src/goe/offload/predicates/compiler.py` implements `PredicateCompiler.to_sqlglot(expr, dialect)` and `render_predicate(expr, dialect, bind_style=...)` across `oracle`, `bigquery`, `snowflake`, `tsql`, `hive`, `spark`, and `duckdb` in both literal mode (`bind_style=None`) and parameterized bind mode (`:bind_0` for `oracle`, `@bind_0` for `bigquery`, `?` for `tsql`/`duckdb`, `%s` for `snowflake`/`hive`/`spark`), caching compiled results in `sqlspec.core.NamespacedCache`.
- R4. `src/goe/offload/predicate_offload.py` and the per-dialect `*_predicate.py` modules delegate to `goe.offload.predicates`, shrinking `predicate_offload.py` from 868 LOC to a thin compatibility facade (~60 LOC) while keeping `GenericPredicate` callers working identically.
- R5. `lark` is removed from `pyproject.toml` core dependencies.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/offload/predicates/test_parser.py` 38-digit `Decimal` and nanosecond `datetime64` round-trip tests |
| R2 | 1.1 | `tests/unit/offload/predicates/test_parser.py` DSL grammar, column resolution, synthetic partition injection, and `OptionValueError` tests |
| R3 | 1.2 | `tests/unit/offload/predicates/test_compiler.py` literal and bind rendering across all 7 dialects |
| R4 | 1.3 | `tests/unit/offload/test_predicate_offload.py` end-to-end frontend and backend predicate rendering |
| R5 | 1.3 | `git grep -n "lark" -- src pyproject.toml` returning nothing |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/predicates tests/unit/offload/test_predicate_offload.py tests/unit/characterization -q
uv run ruff format --check src/goe/offload tests/unit/offload
uv run ruff check src/goe/offload tests/unit/offload
uv run mypy src/goe
uv run python tools/verify_architecture.py
git grep -n "lark" -- src pyproject.toml
```

The `git grep` command must print nothing.

## Implementation Plan

### Phase 1: Predicate AST, SQLGlot Parser, Multi-Dialect Compiler, and Caller Cutover
- [ ] 1.1 Build immutable PredicateExpr AST and sqlglot-backed predicate DSL parser ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Build multi-dialect PredicateCompiler and render_predicate with NamespacedCache memoization ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Rewire predicate_offload.py and dialect predicate callers onto goe.offload.predicates and remove lark ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `predicate_ir_compiler_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `sqlglot.parse_one` parses the GOE predicate DSL directly because `column(X)`, `numeric(123)`, `string("abc")`, and `datetime(...)` tokenize as function-like expressions in `sqlglot` once `datetime(...)` inner tokens are normalized; `PredicateExpr` is a frozen `msgspec` tagged union so it is hashable for `@lru_cache` and `NamespacedCache`; `src/goe/offload/predicates/compiler.py` is registered in `tools/verify_architecture.py` (or re-exported from `goe.offload.sql_ast`) as an allowed `sqlglot` consumer alongside `goe.offload.sql_ast`.
- **Discoveries**: none yet.
- **Blockers**: Chapter 7.1 (`native_sqlglot_dialect_engine_20261024`) must complete first.
- **Next exact step**: execute task `1.1` (`predicate_ir_compiler_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/standards/database-and-sql.md`, `.agents/bundles/knowledge/architecture/type-mapping.md`.
