---
name: review-sqlspec-and-sql-ast
description: "Use when reviewing GOE changes touching src/goe/persistence/, src/goe/offload/oracle/, src/goe/offload/microsoft/, src/goe/offload/sql_ast/, src/goe/offload/predicates/, src/goe/validate/, or src/goe/sync/."
disable-model-invocation: false
---

# Review: SQLSpec Data Layer, SQLGlot AST Seam & Predicates (`SQL`)

<!-- truth: start -->
- Direct `oracledb` imports are restricted to `src/goe/persistence/oracle/`, `src/goe/offload/oracle/`, and `src/goe/persistence/registry.py` (`[oracledb-boundary]` in `tools/verify_architecture.py`).
- Direct `sqlglot` imports are restricted to `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/` (`[sqlglot-boundary]` in `tools/verify_architecture.py`); all callers use `DialectSqlEngine` (`src/goe/offload/sql_ast/dialect_engine.py`) or `PredicateCompiler` (`src/goe/offload/predicates/compiler.py`).
- `OracleDatabaseRegistry` (`src/goe/persistence/registry.py`) pools `OracleSyncConfig` per role (`app`, `adm`, `repo`, `transport`), formats proxy users (`user[schema]`) in one place (`parse_oracle_proxy_user`), runs a single combined `ALTER SESSION` on connection creation, and piggybacks `conn.module`/`conn.action`/`conn.clientinfo` (`tag_oracle_session`).
- `GOEOracleDialect` (`src/goe/offload/sql_ast/dialect_engine.py`) extends `sqlglot`'s Oracle dialect to parse and render `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and `AS OF SCN <int>` clauses.
- Direct `sqlglot.transpile(sql, read='oracle', write='bigquery')` is unsafe for schema/data mapping (`NUMBER(38,0)` -> `NUMERIC` overflow); always map types through `ColumnSpec`/`TYPE_REGISTRY` and compile predicates through `PredicateIR` + `PredicateCompiler`.
<!-- truth: end -->

## Workflow

1. **Load Suppression & Checklist Catalogs**:
   - Read [Checklist (`SQL-01..06`)](references/checklist.md) and [False-Positive Suppressions (`FP-SQL-01..04`)](references/false-positive-suppressions.md) before flagging any finding.
2. **Inspect Changed Files & Surrounding Context**:
   - Read the full target files around every diff hunk in this domain to verify callers, types, resource cleanup, and concurrency invariants.
3. **Evaluate Two-Axis Conformance**:
   - Check spec/behavior correctness, public-seam test strength, and adherence to `SQL-01..06` and `tools/verify_architecture.py`.
4. **Filter Against Suppressions**:
   - Drop any candidate finding matching a `DO NOT FLAG` rule in [False-Positive Suppressions](references/false-positive-suppressions.md) or lacking a concrete failure mode.

## Guardrails

- Never flag stylistic preferences already enforced by `ruff` or `mypy` unless a real defect is present.
- Never propose inline `#` comments inside function/method bodies or nested function-scoped imports (both violate `tools/verify_architecture.py`).
- Anchor every finding to an exact `path/to/file.py:line` range, rule ID (`SQL-NN`), concrete failure scenario, and minimal fix.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/offload/sql_ast tests/unit/offload/predicates tests/unit/persistence tests/unit/validate tests/unit/sync -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Return structured findings citing `[<PREFIX>-NN] path/to/file.py:line — <summary>`, severity (`blocking` | `important` | `nit`), reproduction/failure trace, and concrete fix, or state that zero issues were found across `SQL-01..06`.
