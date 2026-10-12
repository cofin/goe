---
type: Spec
flow_id: core_god_module_decomposition_20261010
title: "Chapter 2.2: Core God-Module Decomposition (Orchestration, Status Report, Source Data & Transport)"
state: completed
plan_revision: 3
plan_commit: null
state_revision: 5
current_task: null
last_operation: finish
operation_targets:
  - core_god_module_decomposition_20261010
last_verified_checkpoint: 71c18e8
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-11T18:01:15Z
description: "Decompose goe.py, offload_status_report.py, offload_source_data.py, offload_transport.py and offload_transport_factory.py into cohesive modules by verbatim moves, delete proven dead code, and leave each legacy module as a definition-free re-export facade that serves exactly its observed import surface."
tags:
  - refactoring
  - architecture
  - orchestration
  - report
  - source-data
  - transport
  - dead-code-elimination
parent: prd_02_core_typing_options_and_decomposition_20261010
depends_on:
  - typed_msgspec_option_model_20261010
research: []
---

# Chapter 2.2: Core God-Module Decomposition

## Specification

### 1. Context and baseline

- **Baseline commit**: line numbers refer to `46890a8`. Earlier chapters edit these files first; locate code by symbol name.
  - `src/goe/goe.py`: PRD 1 Chapter 1.1 Task 1.2 removes the `RedisClient` import (L24), `redis_execution_id`/`redis_in_error` (L248-249), the `redis_publish` branch of `log()` (L256-283), `redis_publish=False` arguments in `log_command_line()` (L303-307), and `init_redis_execution_id` (L1107-1109). Chapter 2.1 Task 1.3 replaces `EXPECTED_OFFLOAD_ARGS` (L153-240) with an import from `goe.config.options`, imports `OptionValueError` from `goe.exceptions`, and deletes everything from `check_posint` (L2666) to end of file.
  - `src/goe/offload/offload_status_report.py`: Chapter 2.1 Task 1.2 deletes `get_offload_status_report_opts` (L3602-3673) and the `optparse` import, and makes `offload_status_report_run(options: StatusReportOptions)` require its argument.
  - `src/goe/offload/offload_transport.py`, `tests/unit/offload/test_offload_transport.py`: listed as files of PRD 1 Chapter 1.2 Task 1.3 (Dataproc impersonation work).
  - `src/goe/orchestration/orchestration_runner.py`: PRD 1 Chapter 1.1 Task 1.2 removes `init_redis_execution_id`; it then imports only `OffloadOperation`, `get_log_fh`, `get_offload_target_table`, `init`, `init_log`, `offload_table` from `goe.goe`, all served by the facade, so this chapter does not edit it.
- **Verified sizes at baseline**: `goe.py` 3,127 lines, `offload_status_report.py` 3,794, `offload_source_data.py` 2,874, `offload_transport.py` 2,511, `factory/offload_transport_factory.py` 200 (12,506 total).
- **Characterization baseline (every task)**: `uv run pytest tests/unit` (includes the PRD 1 golden suite `tests/unit/characterization/test_offload_bigquery_golden.py` from `oracle_ci_and_bigquery_test_harness_20261010:1.3`) and `GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only -q` (PRD 1 makes collection offline-safe; integration modules import 40+ facade symbols, so collection proves the facade surfaces). Each task adds one focused characterization test written and passing before code moves.

### 2. Rules for every task

1. **Verbatim body moves with public-before-private ordering**: function and method bodies, signatures, and constants move unchanged (only import lines and class method order change). Within every module and class, all public functions/methods and dunder lifecycle methods (`__init__`, `__del__`, etc.) are grouped at the top before any private (`_...`) helper functions/methods (`# PUBLIC METHODS` immediately after `__init__`/`__del__`, `# PRIVATE METHODS` at the bottom of each class). No behavior edits, renames, or reformatting beyond `uv run ruff format`.
2. **Facade contract (replaces the old `<= 60 LOC` budget)**: after the task, the legacy module body is exactly a module docstring followed by `from <new module> import name as name` statements. It re-exports exactly the names other code imports from it, computed by the surface scanner in each worksheet (ImportFrom statements, `("module", "name")` lazy-import tuples in `src/goe/cli`, and `"module.name"` patch strings, across `src/`, `tests/`, `tools/`). The redundant `as name` alias marks explicit re-exports for ruff `F401` and mypy. A fixed line budget is not used because `ruff format` explodes multi-name imports one per line, which makes the transport facade (40+ names) exceed 60 lines while still containing zero definitions.
3. **New package `__init__.py` files contain only the SPDX header and a one-line docstring.** `src/goe/orchestration/__init__.py` and `src/goe/offload/__init__.py` are empty at baseline and `goe.offload.offload_messages` imports `goe.orchestration.command_steps` at module load; re-exporting submodules from a package `__init__` would execute the whole package on that import and create import cycles.
4. **Dead code is deleted only with zero-caller evidence** (`git grep -n "\b<name>\b" -- src tests tools` returns only the definition) recorded in the task's Notes.
5. **Mutable module state** (`options`, `log_fh`, `suppress_stdout_override`, `ts` in `goe.py`) lives in exactly one module and is never re-exported by value.

### 3. Target layout

| Legacy module | New modules |
| :--- | :--- |
| `src/goe/goe.py` | `src/goe/orchestration/constants.py`, `src/goe/orchestration/logging_init.py`, `src/goe/orchestration/operation.py`, `src/goe/orchestration/execution.py` |
| `src/goe/offload/offload_status_report.py` | `src/goe/report/__init__.py`, `src/goe/report/models.py`, `src/goe/report/demo_data.py`, `src/goe/report/renderers.py`, `src/goe/report/collector.py` |
| `src/goe/offload/offload_source_data.py` | `src/goe/offload/source_data/__init__.py`, `base.py`, `predicate.py`, `full.py`, `ipa_range.py`, `ipa_list.py`, `factory.py` |
| `src/goe/offload/offload_transport.py`, `src/goe/offload/factory/offload_transport_factory.py` | `src/goe/offload/transport/__init__.py`, `constants.py`, `availability.py`, `base.py`, `spark_thrift.py`, `spark_submit.py`, `query_import.py`, `factory.py` |

Downstream contracts kept: `choose_offload_transport_method` lives in `src/goe/offload/transport/factory.py` and `OffloadTransportQueryImport` in `src/goe/offload/transport/query_import.py` (referenced by `bigquery_first_backend_modernization_20261010`).

### 4. Requirements and traceability

| ID | Requirement | Task | Verification artifact |
| :--- | :--- | :--- | :--- |
| FR-1 | `goe.py` split into `src/goe/orchestration/` with steps, locking, repo lifecycle, dry-run/execute, and CLI/listener entrypoints unchanged; dead `silent_close`, `normalise_column_transformations`, `canonical_to_rdbms_mappings`, `get_synthetic_partition_cols`, `dev_logger`, and the write-only `execution_id` global deleted | 1.1 | `tests/unit/orchestration/test_goe_orchestration_characterization.py`, surface/facade checks |
| FR-2 | `offload_status_report.py` split into `src/goe/report/` preserving CSV/TEXT/JSON/RAW output, summary/detail levels, demo mode, and HTML lookup path; dead `_pretty_print_report_data`, `datetime_literal_to_hv` deleted | 1.2 | `tests/unit/report/test_offload_status_report_characterization.py` |
| FR-3 | `offload_source_data.py` split into `src/goe/offload/source_data/` preserving full/partitioned, IPA range/list/list-as-range, predicate (PBO), subpartition behavior; dead `override_source_partitions` and `OffloadSourceDataIUPartitioned` deleted | 1.3 | `tests/unit/offload/test_offload_source_data.py` |
| FR-4 | `offload_transport.py` and `offload_transport_factory.py` split into `src/goe/offload/transport/` preserving QueryImport, SparkThrift, SparkSubmit (and canaries), availability checks, method selection, factory, connectivity checkers, polling validation, SCN/staging checks | 1.4 | `tests/unit/offload/test_offload_transport.py`, `tests/unit/offload/test_offload_transport_functions.py`, `tests/unit/offload/test_offload_transport_rdbms_api.py` |
| NFR-1 | Legacy modules are definition-free facades serving their observed surface | 1.1-1.4 | facade structure and surface heredocs |
| NFR-2 | No new F401/F841/ERA001 findings in moved code | 1.1-1.4 | `uv run ruff check --no-fix --select F401,F841,ERA001 <new modules>` |
| NFR-3 | SPDX headers, PEP 585/604, no inline comments in new code; `ruff check`, `ruff format --check`, `mypy src/goe` green | 1.1-1.4 | Verification blocks |
| NFR-4 | Every decomposed module, class, and characterization test places public/dunder functions and methods before private (`_...`) helpers | 1.1-1.4 | AST public-before-private check in Verification blocks |

### 5. Resolved decisions

- **`D-2.2-A` (RESOLVED)** — The HTML report template `offload_status_report/goe_offload_status_report.html` does not exist in this repository (`git ls-files` has no `templates/offload_status_report/`; upstream `gluent/goe` keeps it under repo-root `templates/`), so HTML output raises `jinja2.TemplateNotFound` at baseline. Preserve the lookup path (`src/goe/templates/`) verbatim and characterize the current failure; restoring or removing HTML is out of scope for this behavior-preserving chapter.
- **`D-2.2-B` (RESOLVED)** — `OffloadStatusReport.__init__` reads `self._execute` (L190, L239) before assigning it (L243), so constructing the report raises `AttributeError` at baseline, and it opens an Oracle connection. The characterization test builds the instance with `OffloadStatusReport.__new__` and sets only the attributes the demo/report path reads; the constructor defect is preserved verbatim in this behavior-preserving decomposition.

### 6. File ownership

| Task | Owned files | Depends on |
| :--- | :--- | :--- |
| 1.1 | `src/goe/goe.py`, `src/goe/orchestration/constants.py`, `src/goe/orchestration/logging_init.py`, `src/goe/orchestration/operation.py`, `src/goe/orchestration/execution.py`, `tests/unit/orchestration/test_goe_orchestration_characterization.py` | — |
| 1.2 | `src/goe/offload/offload_status_report.py`, `src/goe/report/__init__.py`, `src/goe/report/models.py`, `src/goe/report/demo_data.py`, `src/goe/report/renderers.py`, `src/goe/report/collector.py`, `tests/unit/report/__init__.py`, `tests/unit/report/test_offload_status_report_characterization.py` | 1.1 |
| 1.3 | `src/goe/offload/offload_source_data.py`, `src/goe/offload/source_data/__init__.py`, `src/goe/offload/source_data/base.py`, `src/goe/offload/source_data/predicate.py`, `src/goe/offload/source_data/full.py`, `src/goe/offload/source_data/ipa_range.py`, `src/goe/offload/source_data/ipa_list.py`, `src/goe/offload/source_data/factory.py`, `tests/unit/offload/test_offload_source_data.py` | 1.2 |
| 1.4 | `src/goe/offload/offload_transport.py`, `src/goe/offload/factory/offload_transport_factory.py`, `src/goe/offload/transport/__init__.py`, `src/goe/offload/transport/constants.py`, `src/goe/offload/transport/availability.py`, `src/goe/offload/transport/base.py`, `src/goe/offload/transport/spark_thrift.py`, `src/goe/offload/transport/spark_submit.py`, `src/goe/offload/transport/query_import.py`, `src/goe/offload/transport/factory.py`, `tests/unit/offload/test_offload_transport.py` | 1.3 |

Tasks are sequential (each ends green) even though their files are disjoint, so a failure in one move never masks another.

## Implementation Plan

- [x] 1.1 [Decompose `goe.py` into `src/goe/orchestration/`](tasks/1.1.md) (91d4036)
- [x] 1.2 [Decompose `offload_status_report.py` into `src/goe/report/`](tasks/1.2.md) (4cc4d5c)
- [x] 1.3 [Decompose `offload_source_data.py` into `src/goe/offload/source_data/`](tasks/1.3.md) (cede44d)
- [x] 1.4 [Decompose `offload_transport.py` and its factory into `src/goe/offload/transport/`](tasks/1.4.md) (71c18e8)

## Continuity Snapshot

- **State**: `completed`; current task: none; claimant: none; last verified checkpoint: `71c18e8`.
- **Decisions**: `D-2.2-A` (missing HTML template) and `D-2.2-B` (OSR constructor seam) resolved as described in §5.
- **Blockers**: none.
- **Next exact step**: proceed to Chapter 2.3 (`strict_mypy_type_safety_ratchet_20261010`).
- **Plan identity**: `plan_revision: 3`, `plan_commit: null`. **State identity**: `state_revision: 5`.
- **Relevant knowledge**: `.agents/bundles/knowledge/architecture/`, `.agents/bundles/knowledge/transport/`, `.agents/bundles/knowledge/patterns/offload-and-typing.md`.
