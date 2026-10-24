---
type: Spec
flow_id: concurrent_cross_db_validation_20261024
title: "Chapter 7.3: Concurrent Cross-DB Validation"
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
description: "Replace sequential float-cast validation and regex filter rewriting with AST-composed aggregate queries, concurrent frontend and backend execution, exact Decimal comparison, normalized group-key alignment, and opt-in DuckDB row-level diffing."
tags: [refactor, validation, sqlglot, concurrency]
parent_prd: prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024
depends_on: [predicate_ir_compiler_20261024]
research:
  - .agents/bundles/specs/prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 7.3: Concurrent Cross-DB Validation

## Specification

### 1. Overview and Goals

GOE currently validates offloaded data in `src/goe/offload/offload_validation.py` (977 LOC) and `src/goe/scripts/agg_validate.py` (161 LOC). The existing implementation converts numeric aggregates to binary `float` before calling `isclose` (`offload_validation.py:695`), aligns grouped validation rows by positional `zip` (`offload_validation.py:722-734`) despite `NULL` ordering differences between Oracle (`NULLS LAST` on `ASC`) and cloud warehouses (`NULLS FIRST` on `ASC`), validates CLI `--filters` with a brittle regex (`agg_validate.py:46, 110-120`), and mutates global `sqlglot` state via `register_oracle_dialect_extensions()` (`offload_validation.py:39, 109, 118`).

This chapter:

1. Introduces `src/goe/offload/validation/ast_builder.py` with `AggregateQuestion(FrozenBaseStruct)`, `ValidationBatchQuery(FrozenBaseStruct)`, and `CrossDbValidationBuilder`, which builds `COUNT(*)`, `MIN`, `MAX`, `SUM`, `AVG`, `STDDEV`, and sample-hash aggregate ASTs through `DialectSqlEngine` and `SqlGlotPredicateCompiler`, chunking column aggregates into batches of at most 64 aggregate projections per query and emitting explicit `NULLS LAST` ordering on every `GROUP BY` key.
2. Introduces `src/goe/offload/validation/runner.py` with `ColumnMismatch(FrozenBaseStruct)`, `ValidationResult(FrozenBaseStruct)`, and `CrossDbValidator`, dispatching frontend and backend batch queries concurrently via `run_bounded(..., max_workers=2)` with Oracle `AS OF SCN :scn` snapshot binding, exact `Decimal` comparison for `COUNT`/`MIN`/`MAX`/`SUM`, quantized `Decimal` tolerance only for `AVG`/`STDDEV` and floating-point columns, and normalized group-key dictionary alignment.
3. Refactors `src/goe/offload/offload_validation.py` into a slim (~180 LOC) entry point delegating to `goe.offload.validation`, updates `src/goe/scripts/agg_validate.py` to parse `--filters` via `sqlglot` AST whitelisting instead of `REGEX_FILTER`, and wires `src/goe/cli/commands/validate.py` (including opt-in `--diff` row-level diagnostics via DuckDB).

### 2. Code Analysis Summary

- `src/goe/offload/offload_validation.py:39, 109, 118`: imports and calls `register_oracle_dialect_extensions()` (removed in Chapter 7.1) and constructs `ValidationSqlEngine` (`:103-145`) using `exp.Var` string fragments.
- `src/goe/offload/offload_validation.py:654-670`: `_run_sql` uses `ParallelExecutor.execute_in_threads(2, ...)` without propagating OpenTelemetry context or typed `sqlspec.core.SQL` bind parameters.
- `src/goe/offload/offload_validation.py:686-705`: `front_and_back_match` checks `is_number(front) and is_number(back) and isclose(float(front), float(back))`, which loses precision on 16..38-digit `Decimal` sums and boundaries.
- `src/goe/offload/offload_validation.py:706-735`: `merge_front_end_results` iterates by positional index `for row_no, _ in enumerate(front_results)` and pairs `front_results[row_no]` with `back_results[row_no]`, producing false mismatches when `GROUP BY` columns contain `NULL` values or when one side has missing groups.
- `src/goe/scripts/agg_validate.py:46, 109-121`: `REGEX_FILTER = re.compile(r"(\S+)\s+(%s)\s+(\S+)" % "|".join(SUPPORTED_OPERATIONS), re.IGNORECASE)` rejects parenthesized predicates, `IN (...)`, `IS NULL`, and spaces inside string literals.
- `src/goe/cli/commands/validate.py:28-108`: defines the `goe validate` CLI command and delegates to `post_process_args` and `run_agg_validate`.

### 3. Requirements

- R1. `AggregateQuestion(FrozenBaseStruct)` and `CrossDbValidationBuilder` in `src/goe/offload/validation/ast_builder.py` build dialect-targeted `SELECT` ASTs for `COUNT(*)`, `MIN`, `MAX`, `SUM`, `AVG`, `STDDEV`, and sample-hash expressions using `DialectSqlEngine` and `SqlGlotPredicateCompiler`, chunking aggregate projections into batches of `<= 64` items per query and enforcing `ORDER BY <group_col> ASC NULLS LAST` on all grouped queries.
- R2. `CrossDbValidationBuilder.parse_filter_clause` validates raw `--filters` expressions by parsing with `sqlglot.parse_one(..., read="oracle")` and rejecting unsafe AST nodes (subqueries, function calls outside date/timestamp constructors, DDL/DML), transpiling cleanly to the target dialect without string `.replace('"', '`')`.
- R3. `ValidationResult(FrozenBaseStruct)`, `ColumnMismatch(FrozenBaseStruct)`, and `CrossDbValidator` in `src/goe/offload/validation/runner.py` execute frontend and backend queries concurrently via `run_bounded(..., max_workers=2)`, bind Oracle `AS OF SCN :scn` parameters when `as_of_scn` is provided, align grouped rows by normalized group-key tuple, and compare `COUNT`, `MIN`, `MAX`, and `SUM` on exact integer/decimal columns using exact `Decimal` equality while applying quantized `Decimal` tolerance (`Decimal("1e-6")`) only to `AVG`, `STDDEV`, and floating-point columns.
- R4. `src/goe/offload/offload_validation.py` (~180 LOC), `src/goe/scripts/agg_validate.py`, and `src/goe/cli/commands/validate.py` delegate to `goe.offload.validation`, retire `REGEX_FILTER` and `float()` aggregate comparisons, and add opt-in `--diff` row-level primary-key diagnostics backed by DuckDB 2.0 `EXCEPT` queries.
- R5 (risk). Large wide tables with hundreds of columns can exceed backend query expression limits in a single `SELECT`. Mitigation: `CrossDbValidationBuilder` chunks aggregate questions into batches of at most `max_aggregates_per_query: int = 64` while keeping `COUNT(*)` in the first batch.
- R6 (risk). `goe validate --diff` could be invoked inadvertently during automated offload flows. Mitigation: `--diff` defaults to `False`, is exposed only on `goe validate`, and never executes during `goe offload`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| --- | --- | --- |
| R1 | 1.1 | `tests/unit/offload/validation/test_ast_builder.py` batch chunking, `AS OF SCN`, hint, and `NULLS LAST` AST generation tests |
| R2 | 1.1 | `tests/unit/offload/validation/test_ast_builder.py` filter AST validation and quoted-literal preservation tests |
| R3 | 1.2 | `tests/unit/offload/validation/test_runner.py` concurrent dispatch, 38-digit `Decimal` comparison, and `NULL` group-key alignment tests |
| R4 | 1.3 | `tests/unit/offload/test_offload_validation.py` facade, `agg_validate` filter parsing, and CLI `--diff` delegation tests |
| R5 | 1.1 | `test_builder_chunks_wide_table_aggregates_at_64_limit` in `tests/unit/offload/validation/test_ast_builder.py` |
| R6 | 1.3 | `test_validate_cli_diff_flag_opt_in_only` in `tests/unit/offload/test_offload_validation.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/validation tests/unit/offload/test_offload_validation.py -v
uv run ruff format --check src/goe/offload/validation src/goe/offload/offload_validation.py src/goe/scripts/agg_validate.py src/goe/cli/commands/validate.py tests/unit/offload
uv run ruff check src/goe/offload/validation src/goe/offload/offload_validation.py src/goe/scripts/agg_validate.py src/goe/cli/commands/validate.py tests/unit/offload
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: AST Builder, Concurrent Runner, and CLI Cutover
- [ ] 1.1 Build `AggregateQuestion` and `CrossDbValidationBuilder` with 64-aggregate batch chunking ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement `CrossDbValidator`, `ValidationResult`, and `ColumnMismatch` with `run_bounded` and exact `Decimal` comparison ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Refactor `offload_validation.py`, `agg_validate.py`, and `cli/commands/validate.py` onto `CrossDbValidator` ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `concurrent_cross_db_validation_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: chunk aggregate projections at `<= 64` per query; use `run_bounded(..., max_workers=2)` for concurrent frontend/backend execution; compare `COUNT`, `MIN`, `MAX`, and `SUM` in exact `Decimal` arithmetic and apply tolerance only to `AVG`, `STDDEV`, and floating-point columns; align grouped results by normalized group-key tuple; keep `goe validate --diff` strictly opt-in.
- **Discoveries**: none yet.
- **Blockers**: Chapter 7.2 (`predicate_ir_compiler_20261024`) must complete first.
- **Next exact step**: execute task `1.1` (`concurrent_cross_db_validation_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/standards/database-and-sql.md`, `.agents/bundles/knowledge/operations/cli-tools.md`.
