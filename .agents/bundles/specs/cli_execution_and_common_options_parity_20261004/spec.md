---
type: Spec
flow_id: cli_execution_and_common_options_parity_20261004
title: CLI Execution & Common Options Parity
state: completed
plan_revision: 2
plan_commit: null
state_revision: 7
current_task: null
last_operation: 20261004T175330Z-flow-completion-complete-c1-00
operation_targets:
  - cli_execution_and_common_options_parity_20261004
last_verified_checkpoint: c635ac76ab53fbfb3823d317732bed4a49c4da28
created_at: 2026-10-04T15:00:00Z
updated_at: 2026-10-04T17:53:30Z
description: Remediate global CLI option handling across subcommands and bin/* wrappers, default listener startup, and runtime execution parity for goe sync and goe validate
parent_prd: v2_main_alignment_remediation_20261004
tags:
  - spec
  - cli
  - sync
  - validate
  - listener
---

# Spec: CLI Execution & Common Options Parity (`cli_execution_and_common_options_parity_20261004`)

## 1. Objective & Scope

Restore 100% execution parity between `main` (`ab4f0f9`) and the unified `rich-click` CLI (`src/goe/cli/` and `bin/*` wrappers) for:
1. **Common / Global CLI Options (`Finding CLI-3`)**: Support `-v/--verbose`, `--vv/--vverbose`, `-q/--quiet`, `--no-ansi`, `--version`, and the 7 common/hidden options from `src/goe/goe.py:2705-2771` (`--log-path`, `--log-level`, `--no-version-check`, `--error-before-step`, `--error-after-step`, `--error-on-token`, `--suppress-stdout`) both at the root `goe` group and on individual subcommands (so both `goe -v offload ...`, `goe offload ... -v`, and `bin/offload ... -v` succeed).
2. **`bin/listener` & `goe listener` Default Startup (`Finding CLI-4`)**: Configure `@click.group(name="listener", invoke_without_command=True)` so running `bin/listener` or `goe listener` without an explicit `start` or `status` subcommand immediately starts the Granian ASGI listener server just as `main:bin/listener` did, while still supporting `goe listener start` and `goe listener status`.
3. **`goe sync` / `bin/schema_sync` Runtime Execution (`Finding CLI-1`)**: Fix the broken `OrchestrationConfig` / `orchestration_repo_client_factory` / `run_schema_sync` call sequence in `src/goe/cli/commands/sync.py:49-78` so `goe sync` initializes logging (`init(options)`, `init_log("schema_sync")`), calls `orchestration_repo_client_factory(config, messages, dry_run=bool(not options.execute), trace_action="repo_client(schema_sync)")`, calls `run_schema_sync(options, messages, execution_id, repo_client)`, closes `repo_client` and the log handle in `finally:`, and propagates non-zero exit codes via `if return_code: sys.exit(return_code)`.
4. **`goe validate` / `bin/agg_validate` Argument Post-Processing & Exit Codes (`Finding CLI-2`, `Finding CORE-1`)**: Call `post_process_args(options)` (`src/goe/scripts/agg_validate.py:146-176`) before `run_agg_validate(options)`, add missing `--target-name` (`target_owner_name`) and `--dev-log-level` (`dev_log_level`, `hidden=True`), set `type=int` on `--as-of-scn`, exit with `sys.exit(0 if ret else 1)`, and ensure `src/goe/scripts/agg_validate.py:259-266` calls `config_file.load_env()` before `config_file.check_config_path()`.

---

## 2. Requirements & Acceptance Criteria

- **REQ-C1-01**: Create `src/goe/cli/common.py` with a reusable `@common_options` decorator and `extract_common_options(ctx, kwargs)` helper that registers and resolves `--version`, `-v/--verbose`, `--vv/--vverbose`, `-q/--quiet`, `--no-ansi`, `--log-path`, `--log-level`, `--no-version-check` (`ver_check`), `--error-before-step`, `--error-after-step`, `--error-on-token`, and `--suppress-stdout`.
- **REQ-C1-02**: Apply `@common_options` to `src/goe/cli/main.py` and `src/goe/cli/commands/listener.py`, and configure `listener` with `invoke_without_command=True` so `bin/listener` and `goe listener` invoke `_start_listener_server(...)` when no subcommand is given while preserving `goe listener start` and `goe listener status`.
- **REQ-C1-03**: Update `src/goe/cli/commands/sync.py` to apply `@common_options`, merge resolved common options via `extract_common_options(ctx, kwargs)`, call `normalise_schema_sync_options(options)`, initialize logging (`init(options)`, `init_log("schema_sync")`), construct `orchestration_repo_client_factory(config, messages, dry_run=bool(not options.execute), trace_action="repo_client(schema_sync)")`, invoke `return_code = run_schema_sync(options, messages, execution_id, repo_client)`, close resources in `finally:`, and exit via `sys.exit(return_code)` when `return_code` is non-zero.
- **REQ-C1-04**: Update `src/goe/cli/commands/validate.py` to apply `@common_options`, add `--target-name` (`"target_owner_name"`) and `--dev-log-level` (`"dev_log_level"`, `hidden=True`), type `--as-of-scn` as `int`, invoke `post_process_args(options)` before `ret = run_agg_validate(options)`, and exit via `sys.exit(0 if ret else 1)`.
- **REQ-C1-05**: Update `src/goe/scripts/agg_validate.py:259-266` so `config_file.load_env()` executes before `config_file.check_config_path()`.

---

## Implementation Plan

### Phase 1: Common CLI Options, Listener Default Startup, and `sync`/`validate` Execution Parity

- [x] Task T1.1: [Common CLI Options Decorator & `listener` Default Startup](tasks/T1.1.md) (`ab561bafc3ec91ada10e330f7ac60e1a90f22867`) (`files`: `src/goe/cli/common.py`, `src/goe/cli/main.py`, `src/goe/cli/commands/listener.py`; `tests`: `tests/unit/cli/test_common_options.py`, `tests/unit/cli/test_cli_root.py`, `tests/unit/cli/test_listener_command.py`)
- [x] Task T1.2: [`goe sync` and `goe validate` Execution Parity](tasks/T1.2.md) (`c635ac76ab53fbfb3823d317732bed4a49c4da28`) (`depends_on`: `["cli_execution_and_common_options_parity_20261004:T1.1"]`; `files`: `src/goe/cli/commands/sync.py`, `src/goe/cli/commands/validate.py`, `src/goe/scripts/agg_validate.py`; `tests`: `tests/unit/cli/test_sync_command.py`, `tests/unit/cli/test_validate_command.py`)

---

## 4. Requirement-to-Task & Test Traceability Matrix

| Requirement ID | Description | Task ID | Target Source Files | Verification Test Files |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-C1-01** | `@common_options` decorator and `extract_common_options` helper in `src/goe/cli/common.py` | `T1.1` | `src/goe/cli/common.py`, `src/goe/cli/main.py` | `tests/unit/cli/test_common_options.py`, `tests/unit/cli/test_cli_root.py` |
| **REQ-C1-02** | `goe listener` / `bin/listener` default `start` invocation with `invoke_without_command=True` | `T1.1` | `src/goe/cli/commands/listener.py` | `tests/unit/cli/test_listener_command.py` |
| **REQ-C1-03** | `goe sync` 2-arg `orchestration_repo_client_factory`, 4-arg `run_schema_sync`, and exit code propagation | `T1.2` | `src/goe/cli/commands/sync.py` | `tests/unit/cli/test_sync_command.py` |
| **REQ-C1-04** | `goe validate` `post_process_args(options)` call, `--target-name`, `--dev-log-level`, `--as-of-scn` `int`, and exit code | `T1.2` | `src/goe/cli/commands/validate.py` | `tests/unit/cli/test_validate_command.py` |
| **REQ-C1-05** | `agg_validate.py` `load_env()` before `check_config_path()` | `T1.2` | `src/goe/scripts/agg_validate.py` | `tests/unit/cli/test_validate_command.py` |

---

## Continuity Snapshot

- **Active Flow**: `cli_execution_and_common_options_parity_20261004`
- **Lifecycle State**: `completed`
- **Current Task**: `null`
- **Claimant**: `null`
- **Last Verified Checkpoint**: `c635ac76ab53fbfb3823d317732bed4a49c4da28`
- **Decisions**: Reusable `@common_options` decorator in `src/goe/cli/common.py` with `orchestration_defaults.log_path_default()` and `log_level_default()` fallback; `@click.group(name="listener", invoke_without_command=True)`; 2-arg `orchestration_repo_client_factory` and 4-arg `run_schema_sync` in `sync.py`; `post_process_args(options)` and exit code propagation in `validate.py`.
- **Recent Discoveries**: Passed correctness review and `quality-review-v1` on `1c1973b381950652b6c30a437d833119b2b7465e..c635ac76ab53fbfb3823d317732bed4a49c4da28` with 0 findings.
- **Blockers & Unblock Conditions**: None
- **Next Exact Step**: Completed
- **Plan Identity**: `plan_revision: 2`, `plan_commit: null`
- **State Identity**: `revision: 7`, `last_operation: 20261004T175330Z-flow-completion-complete-c1-00`, `operation_targets: ["cli_execution_and_common_options_parity_20261004"]`
- **Relevant Knowledge Paths**: `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/patterns/cli-architecture.md`




