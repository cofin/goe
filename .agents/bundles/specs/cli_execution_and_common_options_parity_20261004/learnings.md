---
type: Reference
title: Learnings — CLI Execution & Common Options Parity
description: Implementation learnings, gotchas, and pattern updates from cli_execution_and_common_options_parity_20261004
tags:
  - learnings
  - cli
  - sync
  - validate
  - listener
---

# Learnings: `cli_execution_and_common_options_parity_20261004`

## Phase 1: Common CLI Options, Listener Default Startup, and `sync`/`validate` Execution Parity

### What Changed & Why
- **Shared `@common_options` & `extract_common_options` (`src/goe/cli/common.py`)**: Created a reusable Click option decorator and context merger so global flags (`--version`, `-v/--verbose`, `--vv/--vverbose`, `-q/--quiet`, `--no-ansi`) and the 7 hidden/common engine options (`--log-path`, `--log-level`, `--no-version-check`, `--error-before-step`, `--error-after-step`, `--error-on-token`, `--suppress-stdout`) work whether placed before the subcommand (`goe -v sync ...`), after the subcommand (`goe sync ... -v`), or through `bin/*` wrappers (`bin/schema_sync ... -v`).
- **`goe listener` / `bin/listener` Default Startup (`src/goe/cli/commands/listener.py`)**: Added `invoke_without_command=True` and shared `_listener_server_options` so `bin/listener` and bare `goe listener` immediately invoke `_start_listener_server(...)` while preserving `goe listener start` and `goe listener status`.
- **`goe sync` Runtime Execution Parity (`src/goe/cli/commands/sync.py`)**: Fixed three runtime signature mismatches (`OrchestrationConfig.from_dict`, 2-arg `orchestration_repo_client_factory(config, messages, dry_run=bool(not options.execute), trace_action="repo_client(schema_sync)")`, and 4-arg `run_schema_sync(options, messages, execution_id, repo_client)`), added logging initialization/cleanup (`init(options)`, `init_log("schema_sync")`, `close_log()`), and propagated non-zero return codes via `sys.exit(return_code)`.
- **`goe validate` Post-Processing & Exit Code Parity (`src/goe/cli/commands/validate.py`, `src/goe/scripts/agg_validate.py`)**: Added `post_process_args(options)` before `run_agg_validate(options)`, exposed `--target-name` (`target_owner_name`) and `--dev-log-level`, typed `--as-of-scn` as `int`, exited with `sys.exit(0 if ret else 1)`, and ensured `agg_validate.py:main()` calls `config_file.load_env()` before `config_file.check_config_path()`.

### Files Touched
- `src/goe/cli/common.py`
- `src/goe/cli/main.py`
- `src/goe/cli/commands/listener.py`
- `src/goe/cli/commands/sync.py`
- `src/goe/cli/commands/validate.py`
- `src/goe/scripts/agg_validate.py`
- `tests/unit/cli/test_common_options.py`
- `tests/unit/cli/test_cli_root.py`
- `tests/unit/cli/test_listener_command.py`
- `tests/unit/cli/test_sync_command.py`
- `tests/unit/cli/test_validate_command.py`

### Gotchas & Recoveries
- **`post_process_args(options)` Mutates `options.selects` in Place**: Calling `post_process_args(options)` in `goe validate` runs `csv_split` on `options.selects` (turning `"AMOUNT_SOLD"` into `["AMOUNT_SOLD"]`), populates `options.filters` from `filter_clauses`, `options.group_bys` from `group_by_csv`, and `options.agg_fns` from `agg_fn_csv`. Unit tests mocking `run_agg_validate` must assert the post-processed list structure on `options.selects`.
- **Click Group + Subcommand Flag Precedence**: When the same boolean flags (`-v`, `-q`, `--no-ansi`) are attached to both the root `@click.group()` and subcommands via `@common_options`, subcommand default values (`False`, `None`) would overwrite `ctx.obj` values set on the root group unless merged with `bool(sub_val or root_val)` for booleans and `sub_val if sub_val is not None else root_val` for optional strings (`extract_common_options`).

### Canonical Verification Commands
```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run pytest tests/unit/cli -v
uv run ruff check src/goe/cli src/goe/scripts/agg_validate.py tests/unit/cli
uv run mypy src/goe/cli src/goe/scripts/agg_validate.py
```

## [2026-10-04] Code & Quality Review

**Range:** `1c1973b381950652b6c30a437d833119b2b7465e..c635ac76ab53fbfb3823d317732bed4a49c4da28`
**Issues Found:** 0 (after remediating `log_path_default()` fallback, `sync.py` `try/finally` log handle cleanup, and `listener` group server option forwarding in `c635ac7`)
**Key Findings:**
- `extract_common_options` must fall back to `orchestration_defaults.log_path_default()` and `orchestration_defaults.log_level_default() or "info"` so `options.log_path` is never overwritten with `None` when `--log-path` and `OFFLOAD_LOGFILE` are unset.
- `QualityReport` (`quality-review-v1`): 0 findings (`debloat_source: packaged_skill`).
