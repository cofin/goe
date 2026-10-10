---
type: Spec
flow_id: strict_mypy_type_safety_ratchet_20261010
title: "Chapter 2.3: Strict Mypy Type Safety Ratchet"
state: planned
plan_revision: 2
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-10T18:50:00Z
description: "Ratchet mypy across every live package in src/goe in five package waves, then remove all 14 disable_error_code suppressions and production ignore_errors overrides, enable check_untyped_defs/disallow_incomplete_defs, and enforce F401/F841/ERA001 in make lint."
tags:
  - refactor
  - typing
  - mypy
  - quality
  - pep585
  - pep604
parent: prd_02_core_typing_options_and_decomposition_20261010
depends_on:
  - core_god_module_decomposition_20261010
research: []
---

# Chapter 2.3: Strict Mypy Type Safety Ratchet

## Specification

### 1. Context and baseline (verified at `46890a8`)

- **`pyproject.toml:279-326` `[tool.mypy]`**: `disallow_any_generics = false` (L280), `disallow_incomplete_defs = false` (L281), `disallow_untyped_decorators = false` (L282), `disallow_untyped_defs = false` (L283), `exclude` (L284-290), `files = ["src/goe", "tests"]` (L291), `follow_imports = "silent"` (L292), `ignore_missing_imports = true` (L293), `pretty = true` (L294), `show_column_numbers = true` (L295), `warn_no_return = false` (L296), `warn_redundant_casts = false` (L297), `warn_unused_configs = false` (L298), `warn_unused_ignores = false` (L299), `disable_error_code` with 14 entries (L300-315: `attr-defined`, `assignment`, `arg-type`, `has-type`, `union-attr`, `misc`, `call-arg`, `call-overload`, `override`, `index`, `return-value`, `var-annotated`, `operator`, `name-defined`). `[[tool.mypy.overrides]]` (L317-325) sets `ignore_errors = true` and `warn_unused_ignores = false` for `goe.listener.*`, `goe.connect.*`, `goe.schema_sync.*`, `tests.*`. `check_untyped_defs` is unset (default `false`).
- **`[tool.ruff.lint]`** (`pyproject.toml:206-263`) selects `E, F, W, I, UP, B, RUF, CPY` (L210-219) and ignores `F401` and `F841` (L242, L246); per-file ignores (L275-277) keep `F401` for `__init__.py` and `ERA001` for `tests/**/*`; `ERA` is not selected. `make lint` (`Makefile:76-81`) runs `uv run ruff check .` and `uv run mypy src/goe`. `ruff` runs with `fix = true` (`pyproject.toml:201`).
- **Baseline gates**: `uv run mypy src/goe` reports `Success: no issues found in 231 source files`. The canonical strict command below reports **1,095 errors in 106 files** on all of `src/goe`, **1,033** in live modules (excluding the PRD 1 dead modules). `uv run ruff check --no-fix --select F401,F841,ERA001 src tests tools` reports **105** findings (86 in `src`).
- **Why per-wave commands ignore `pyproject.toml`**: mypy per-module overrides beat command-line flags, so `uv run mypy src/goe/listener` with the current config reports zero errors because of `ignore_errors = true`. Each wave therefore runs mypy with `--config-file=` (documented at https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-config-file: "Specifying --config-file= (with no filename) will ignore all config files") plus the exact flags of the final configuration. Task 1.6 then writes that configuration into `pyproject.toml`, so the global switch introduces no new errors.
- **Canonical wave gate** (equivalent to the final `[tool.mypy]`):

```bash
uv run mypy --config-file= --ignore-missing-imports --follow-imports=silent --check-untyped-defs --disallow-incomplete-defs --warn-redundant-casts --warn-unused-ignores <paths>
```

- **Earlier chapters**: PRD 1 Chapter 1.1 Task 1.4 deletes `src/goe/conductor/`, `src/goe/listener/services/hybrid_view.py`, and `src/goe/util/{serialization,env,text,uuids,exception_trigger,local_cache,retry_logic}.py`; Task 1.1 deletes `src/goe/util/redis_tools.py`; Chapter 1.2 Task 1.1 adds `src/goe/util/gcp_credentials.py`. Chapter 2.1 adds `src/goe/config/options.py`. Chapter 2.2 adds `src/goe/orchestration/{constants,logging_init,operation,execution}.py`, `src/goe/report/`, `src/goe/offload/source_data/`, `src/goe/offload/transport/` and turns `goe.py`, `offload_status_report.py`, `offload_source_data.py`, `offload_transport.py`, `factory/offload_transport_factory.py` into facades.

### 2. Wave plan (covers every package under `src/goe` after Chapters 2.1-2.2)

| Task | Paths | Live baseline errors (canonical gate, `46890a8`) |
| :--- | :--- | :--- |
| 1.1 Wave 1 foundation | `src/goe/__init__.py`, `src/goe/exceptions.py`, `src/goe/lib/`, `src/goe/config/`, `src/goe/util/`, `src/goe/filesystem/`, `src/goe/persistence/` | 176 |
| 1.2 Wave 2 service, CLI, orchestration | `src/goe/goe.py`, `src/goe/cli/`, `src/goe/listener/`, `src/goe/connect/`, `src/goe/schema_sync/`, `src/goe/scripts/`, `src/goe/orchestration/` | 197 (117 of them from code Chapter 2.2 moves out of `goe.py` into `orchestration/`) |
| 1.3 Wave 3 offload core | `src/goe/offload/*.py`, `src/goe/offload/factory/`, `src/goe/offload/operation/`, `src/goe/offload/staging/`, `src/goe/offload/source_data/`, `src/goe/offload/transport/`, `src/goe/report/` | 318 |
| 1.4 Wave 4 RDBMS frontends | `src/goe/offload/oracle/`, `src/goe/offload/teradata/`, `src/goe/offload/microsoft/` | 208 |
| 1.5 Wave 5 backends and Spark | `src/goe/offload/bigquery/`, `src/goe/offload/hadoop/`, `src/goe/offload/snowflake/`, `src/goe/offload/spark/` | 134 |
| 1.6 Global ratchet | `pyproject.toml`, residual dead-code findings in `tests/` and `tools/` | — |

The previous three-task plan put 660 offload errors and the global switch in one task and omitted `hadoop/`, `microsoft/`, `snowflake/`, `spark/`, `teradata/`, `src/goe/report/`, `source_data/`, and `transport/` from its file list; Wave 3 was split by the base-interface/adapter boundary so each task fits one invocation and `[override]` fixes flow from base classes (1.3) to adapters (1.4, 1.5).

### 3. Typing and dead-code rules

1. Annotate with PEP 585 builtins and PEP 604 unions (`list[str]`, `dict[str, Any]`, `X | None`); use `collections.abc` for `Sequence`, `Mapping`, `Iterable`, `Callable`, `Iterator`.
2. Do not add `# type: ignore` (zero exist at baseline; repo rules forbid inline comments). Use annotations, `isinstance`/`is not None` narrowing, `assert`, or `typing.cast`.
3. Type-only imports go in a module-level `if TYPE_CHECKING:` block. Keep the CLI lazy-import pattern (`src/goe/cli/_lazy.py`, `if TYPE_CHECKING:` + `_LAZY_IMPORTS` + `bind_lazy_imports`) intact.
4. Behavior is unchanged: when a fix would change runtime behavior (for example a real `None` bug), stop and record it in the task's `## Notes & Discoveries` and route it through `revise` instead of fixing it inside the ratchet.
5. Each wave also removes `F401`/`F841`/`ERA001` findings in its paths (`uv run ruff check --no-fix --select F401,F841,ERA001 <paths>` reaches zero), deleting dead code rather than annotating it.
6. Re-export facades from Chapter 2.2 use `from x import name as name`, which mypy and ruff treat as explicit re-exports; do not add `__all__` to them.

### 4. Requirement traceability (PRD 2 §2 row 2.3, §4)

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| Annotate all live packages; zero canonical-gate errors per wave | 1.1-1.5 | canonical wave gate per task |
| Remove `ignore_errors` for `goe.listener.*`, `goe.connect.*`, `goe.schema_sync.*` | 1.6 (code proven clean in 1.2) | `uv run mypy src/goe`, gate proof |
| Eliminate the 14 `disable_error_code` entries; enable `check_untyped_defs`, `disallow_incomplete_defs`, `warn_redundant_casts`, `warn_unused_ignores`, `warn_no_return`, `warn_unused_configs` | 1.6 | gate proof, `uv run mypy src/goe` |
| Enforce `F401`, `F841`, `ERA001` in `make lint` | 1.6 | `make lint`, gate proof |

## Implementation Plan

- [ ] 1.1 [Wave 1: foundation packages](tasks/1.1.md)
- [ ] 1.2 [Wave 2: CLI, listener, connect, schema sync, scripts, orchestration](tasks/1.2.md)
- [ ] 1.3 [Wave 3: offload core, factories, operations, staging, source data, transport, report](tasks/1.3.md)
- [ ] 1.4 [Wave 4: Oracle, Teradata, Microsoft frontends](tasks/1.4.md)
- [ ] 1.5 [Wave 5: BigQuery, Hadoop, Snowflake, Spark backends](tasks/1.5.md)
- [ ] 1.6 [Global strict mypy and dead-code ratchet in pyproject.toml](tasks/1.6.md)

## Continuity Snapshot

- **State**: `planned`; current task: none; claimant: none; last verified checkpoint: none.
- **Decisions**: none pending.
- **Blockers**: Chapter 2.2 complete (new module layout exists); PRD 1 dead modules deleted.
- **Next exact step**: claim Task 1.1 and run its canonical wave gate to record the initial error count.
- **Plan identity**: `plan_revision: 2`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/workflow.md` (lint/test commands), `.agents/bundles/knowledge/patterns/cli-architecture.md` (lazy imports), `.agents/bundles/product/tech-stack.md`.
