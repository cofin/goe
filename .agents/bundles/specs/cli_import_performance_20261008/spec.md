---
type: Spec
flow_id: cli_import_performance_20261008
title: Modern Borderless CLI Styling & Zero-Type-Loss Import Performance
state: completed
plan_revision: 1
plan_commit: null
state_revision: 3
current_task: null
last_operation: 20261008T165930Z-flow-completion-complete-00
operation_targets:
  - cli_import_performance_20261008
last_verified_checkpoint: HEAD
created_at: 2026-10-08T16:51:00Z
updated_at: 2026-10-08T16:59:30Z
description: Configure borderless modern rich-click CLI formatting and reduce goe CLI startup/menu latency by ~10x (~1.57s to ~150ms) via zero-type-loss PEP 562 lazy binding and transitive import decoupling
parent_prd: null
research:
  - research/cli_import_performance/research.md
tags:
  - spec
  - cli
  - performance
  - rich-click
  - typing
---

# Spec: Modern Borderless CLI Styling & Zero-Type-Loss Import Performance (`cli_import_performance_20261008`)

## 1. Objective & Scope

1. **Modern Borderless Rich-Click Formatting (`REQ-PERF-01`)**:
   - Configure `rich-click` in [`src/goe/cli/config.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/config.py) via `click.RichHelpConfiguration(...).dump_to_globals()` with `theme="slim"`, `text_markup="rich"`, `style_options_panel_box="BLANK"`, `style_commands_panel_box="BLANK"`, borderless section titles (`Core Orchestration Commands`, `Service & Maintenance Commands`), and `command_groups`/`option_groups` preserved.
   - Remove the duplicate `print_heading()` call on bare `goe` in [`src/goe/cli/main.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/main.py) so `goe` and `goe --help` render a single header with parsed Rich markup and zero box borders.
2. **Zero-Type-Loss Lazy Subcommand & Backend Symbol Resolution (`REQ-PERF-02`)**:
   - Create [`src/goe/cli/_lazy.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/_lazy.py) providing `LazyImportMap`, `resolve_lazy_attribute(module_name, lazy_imports, name)`, and `bind_lazy_imports(module_name, lazy_imports)`.
   - Convert [`src/goe/cli/common.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/common.py), [`src/goe/cli/commands/connect.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/connect.py), [`src/goe/cli/commands/listener.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/listener.py), [`src/goe/cli/commands/offload.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/offload.py), [`src/goe/cli/commands/report.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/report.py), [`src/goe/cli/commands/sync.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/sync.py), and [`src/goe/cli/commands/validate.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/validate.py) to use top-level `if TYPE_CHECKING:` imports + PEP 562 `__getattr__` + `bind_lazy_imports(__name__, _LAZY_IMPORTS)` at callback execution entry.
   - Preserve 100% of `mypy` and `pyright` static type hints at both module export boundaries and function call sites inside command callbacks (`LOAD_GLOBAL`), zero function-scoped imports (`PLC0415`), and 100% `unittest.mock.patch("goe.cli.commands.<cmd>.<symbol>")` compatibility.
3. **Transitive Import Decoupling (`REQ-PERF-03`)**:
   - Convert [`src/goe/listener/utils/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/__init__.py) to `if TYPE_CHECKING:` + PEP 562 `__getattr__` for `orchestrate` and `ping` so importing `goe.listener.utils.cache` from `offload_messages.py` does not eagerly import `litestar`, `numpy`, or `lark` (~303 ms saved across all non-Listener CLI commands).
   - Defer `GCS_MIN_BLOCK_SIZE` resolution in [`src/goe/util/goe_log_fh.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/goe_log_fh.py) via `if TYPE_CHECKING:` + PEP 562 `__getattr__` and `bind_lazy_imports(__name__, _LAZY_IMPORTS)` inside `GOELogFileHandle._get_fs()` when opening `gs://` paths (~218 ms saved across local-log CLI executions).

---

## 2. Requirements & Acceptance Criteria

- **REQ-PERF-01**: `goe` and `goe --help` render borderless modern output (`"╭"`, `"╰"`, `"│"` absent), parse Rich markup (`"[bold"`, `"[dim]"` absent), and preserve all `COMMAND_GROUPS` and `OPTION_GROUPS`.
- **REQ-PERF-02**: `src/goe/cli/_lazy.py`, `src/goe/cli/common.py`, and `src/goe/cli/commands/{connect,listener,offload,report,sync,validate}.py` use `if TYPE_CHECKING:` + PEP 562 `__getattr__` + `bind_lazy_imports(__name__, _LAZY_IMPORTS)` so importing `goe.cli.main` and running `--help` / `--version` does not load `goe.goe`, `goe.connect.connect`, `granian`, `httpx`, `oracledb`, `litestar`, or `gcsfs`, while preserving 100% of static type hints (`uv run mypy src/goe`) and existing `@patch(...)` unit tests.
- **REQ-PERF-03**: Importing `goe.listener.utils.cache` or `goe.util.goe_log_fh` does not eagerly import `goe.listener.utils.orchestrate` (`litestar`, `numpy`) or `gcsfs.core`, while preserving `goe.listener.utils.{cache,groupby,orchestrate,ping,system}` and `goe.util.goe_log_fh.GCS_MIN_BLOCK_SIZE` attribute access and static types.

---

## Implementation Plan

### Phase 1: Zero-Type-Loss CLI Lazy Binding & Transitive Import Decoupling

- [x] Task T1.1: [Borderless Rich-Click Config & Zero-Type-Loss CLI Lazy Binding](tasks/T1.1.md) (`files`: `src/goe/cli/_lazy.py`, `src/goe/cli/__init__.py`, `src/goe/cli/common.py`, `src/goe/cli/config.py`, `src/goe/cli/main.py`, `src/goe/cli/commands/connect.py`, `src/goe/cli/commands/listener.py`, `src/goe/cli/commands/offload.py`, `src/goe/cli/commands/report.py`, `src/goe/cli/commands/sync.py`, `src/goe/cli/commands/validate.py`; `tests`: `tests/unit/cli/test_cli_root.py`, `tests/unit/cli/test_common_options.py`, `tests/unit/cli/test_connect_command.py`, `tests/unit/cli/test_listener_command.py`, `tests/unit/cli/test_offload_command.py`, `tests/unit/cli/test_report_command.py`, `tests/unit/cli/test_sync_command.py`, `tests/unit/cli/test_validate_command.py`)
- [x] Task T1.2: [Transitive Import Decoupling in `goe.listener.utils` & `goe.util.goe_log_fh`](tasks/T1.2.md) (`depends_on`: `["cli_import_performance_20261008:T1.1"]`; `files`: `src/goe/listener/utils/__init__.py`, `src/goe/util/goe_log_fh.py`; `tests`: `tests/unit/cli/test_cli_root.py`, `tests/unit/listener/test_cache.py`, `tests/unit/listener/test_deprecation_shims.py`, `tests/unit/listener/test_jobs.py`)

---

## 4. Requirement-to-Task & Test Traceability Matrix

| Requirement ID | Description | Task ID | Target Source Files | Verification Test Files |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-PERF-01** | Borderless modern `rich-click` configuration and single-heading root help | `T1.1` | `src/goe/cli/config.py`, `src/goe/cli/main.py` | `tests/unit/cli/test_cli_root.py` |
| **REQ-PERF-02** | Zero-type-loss lazy CLI imports (`if TYPE_CHECKING:` + `bind_lazy_imports` + PEP 562 `__getattr__`) | `T1.1` | `src/goe/cli/_lazy.py`, `src/goe/cli/common.py`, `src/goe/cli/commands/*.py` | `tests/unit/cli/test_*.py` |
| **REQ-PERF-03** | Lazy `orchestrate`/`ping` in `goe.listener.utils.__init__` and lazy `gcsfs.core` in `goe.util.goe_log_fh` | `T1.2` | `src/goe/listener/utils/__init__.py`, `src/goe/util/goe_log_fh.py` | `tests/unit/cli/test_cli_root.py`, `tests/unit/listener/test_*.py` |

---

## Continuity Snapshot

- **Active Flow**: `cli_import_performance_20261008`
- **Lifecycle State**: `completed`
- **Current Task**: `null`
- **Claimant**: `null`
- **Last Verified Checkpoint**: `HEAD`
- **Decisions**: Use `if TYPE_CHECKING:` + PEP 562 `__getattr__` + `bind_lazy_imports(__name__, _LAZY_IMPORTS)` in `src/goe/cli/_lazy.py` so 100% of static type hints at module boundaries and call sites are preserved while deferring heavy runtime imports until command execution; keep `from goe.cli.main import cli, main` in `src/goe/cli/__init__.py` because `goe.cli.main` is now lightweight (<3ms) and lazy attribute resolution on `goe.cli` would collide with the `goe.cli.main` submodule attribute.
- **Recent Discoveries**: `.venv/bin/goe` reduced from 1573.3 ms to 170.9 ms (9.2x faster); `import goe.offload.offload_messages` reduced from 900+ ms to 415.8 ms; 86 unit tests pass and `mypy src/goe` passes across all 231 source files.
- **Blockers & Unblock Conditions**: None
- **Next Exact Step**: Completed
- **Plan Identity**: `plan_revision: 1`, `plan_commit: null`
- **State Identity**: `revision: 3`, `last_operation: 20261008T165930Z-flow-completion-complete-00`, `operation_targets: ["cli_import_performance_20261008"]`
- **Relevant Knowledge Paths**: `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/patterns/cli-architecture.md`

