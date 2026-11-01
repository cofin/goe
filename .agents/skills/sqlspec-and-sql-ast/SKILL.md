---
name: sqlspec-and-sql-ast
description: "Use when working on OracleDatabaseRegistry, OracleCatalogService, OracleRepositoryService, MssqlPythonConfig, FrontendCatalogCache, DialectSqlEngine, PredicateIR/PredicateCompiler, CrossDbValidator, or SchemaSyncService."
disable-model-invocation: false
---

# SQLSpec Data Layer, SQLGlot AST Seam & Predicates

<!-- truth: start -->
- Direct `oracledb` imports are restricted to `src/goe/persistence/oracle/`, `src/goe/offload/oracle/`, and `src/goe/persistence/registry.py` (`[oracledb-boundary]` in `tools/verify_architecture.py`).
- Direct `sqlglot` imports are restricted to `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/` (`[sqlglot-boundary]` in `tools/verify_architecture.py`); all callers use `DialectSqlEngine` (`src/goe/offload/sql_ast/dialect_engine.py`) or `PredicateCompiler` (`src/goe/offload/predicates/compiler.py`).
- `OracleDatabaseRegistry` (`src/goe/persistence/registry.py`) pools `OracleSyncConfig` per role (`app`, `adm`, `repo`, `transport`), formats proxy users (`user[schema]`) in one place (`parse_oracle_proxy_user`), runs a single combined `ALTER SESSION` on connection creation, and piggybacks `conn.module`/`conn.action`/`conn.clientinfo` (`tag_oracle_session`).
- `GOEOracleDialect` (`src/goe/offload/sql_ast/dialect_engine.py`) extends `sqlglot`'s Oracle dialect to parse and render `PARTITION ("P1")`, `SUBPARTITION ("SP1")`, and `AS OF SCN <int>` clauses.
- Direct `sqlglot.transpile(sql, read='oracle', write='bigquery')` is unsafe for schema/data mapping (`NUMBER(38,0)` -> `NUMERIC` overflow); always map types through `ColumnSpec`/`TYPE_REGISTRY` and compile predicates through `PredicateIR` + `PredicateCompiler`.
<!-- truth: end -->

## Workflow

1. **Ground in Domain Seams & Knowledge**:
   - Read [Patterns & Seams](references/patterns-and-seams.md) and the linked OKF v0.2 chapters before editing production modules:
- [Database & SQL Standards](../../bundles/knowledge/standards/database-and-sql.md)
- [Oracle Frontend Adapter](../../bundles/knowledge/frontends/oracle.md)
- [SQL Server Frontend Adapter](../../bundles/knowledge/frontends/sqlserver.md)
- [Schema Evolution](../../bundles/knowledge/architecture/schema-evolution.md)
- [ADR-001: SQLSpec Oracle & SQLGlot AST Seam](../../bundles/knowledge/decisions/adr-001-sqlspec-oracle-and-sqlglot-ast-seam.md)
2. **Verify Public Seams First**:
   - Classify touched dependencies (`In-process`, `Local-substitutable`, `Remote-owned`, `External boundary`) and write or update unit tests in the canonical `tests/unit/` module before changing implementation behavior.
3. **Implement Within Architectural Boundaries**:
   - Preserve `FrozenBaseStruct(..., frozen=True)` / `BaseStruct` contracts, route JSON through `goe.serializers`, keep imports at module top-level (or `if TYPE_CHECKING:` / `import_optional_dependency`), and place public methods/functions above `_` private helpers.
4. **Run Focused & Aggregate Verification**:
   - Run the focused pytest suite, `uv run python tools/verify_architecture.py`, and `make lint`.

## Guardrails

- Never violate the 6 AST/token rules in `tools/verify_architecture.py` (`raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`).
- Never introduce inline `#` comments inside function or method bodies; document rationale in Google-style docstrings.
- Never add backward-compatibility shims, unused re-exports, or standalone `test_*_remediation.py` files; place tests in the canonical `tests/unit/` file for the module under test.
- Check [Review Checklist](../review-sqlspec-and-sql-ast/references/checklist.md) and [False-Positive Suppressions](../review-sqlspec-and-sql-ast/references/false-positive-suppressions.md) before finalizing changes.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/offload/sql_ast tests/unit/offload/predicates tests/unit/persistence tests/unit/validate tests/unit/sync -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Summarize modified files, public-seam tests executed, and exact exit statuses for `pytest`, `verify_architecture.py`, and `make lint`.
