---
type: Reference
title: Centralized Rich-Click CLI & Legacy Delegators
description: Unified rich-click goe CLI architecture in src/goe/cli/ and backward-compatible bin/ wrapper delegators
tags:
  - pattern
  - cli
  - rich-click
  - entrypoints
updated_at: "2026-10-08T16:39:00Z"
---

# Centralized Rich-Click CLI & Legacy Delegators

## Single Authoritative CLI Entrypoint (`src/goe/cli/`)

- **Package Script**: [`pyproject.toml`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/pyproject.toml) registers the unified CLI entrypoint via `[project.scripts] goe = "goe.cli.main:cli"`.
- **Styling & Command Groups**: [`src/goe/cli/config.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/config.py) configures `rich-click` via `click.RichHelpConfiguration(theme="slim", text_markup="rich", style_options_panel_box="BLANK", style_commands_panel_box="BLANK", command_groups=COMMAND_GROUPS, option_groups=OPTION_GROUPS, ...).dump_to_globals()` with the Google Cloud color palette (`#4285F4`, `#34A853`, `#FBBC04`, `#EA4335`), borderless modern section headings (`Core Orchestration Commands`, `Service & Maintenance Commands`), and logical option groups for complex commands.
- **Shared Common & Global Options**: [`src/goe/cli/common.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/common.py) provides `@common_options` and `extract_common_options(ctx, kwargs)` so global flags (`--version`, `-v/--verbose`, `--vv/--vverbose`, `-q/--quiet`, `--no-ansi`) and the 7 common/hidden engine options (`--log-path`, `--log-level`, `--no-version-check`, `--error-before-step`, `--error-after-step`, `--error-on-token`, `--suppress-stdout`) are accepted both on the root `goe` group and on subcommands (supporting trailing flags and `bin/*` wrapper invocations), falling back to `orchestration_defaults.log_path_default()` and `orchestration_defaults.log_level_default()` so `options.log_path` is never overwritten with `None`.
- **Modular Subcommands**: Implemented under [`src/goe/cli/commands/`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/):
  - `goe offload` — Data offloading with structured option groups (`OPTION_GROUPS["goe offload"]`). Options validated by downstream string validators (such as `--older-than-days` via `check_opt_is_posint`) remain `str`-typed.
  - `goe connect` — Pre-flight connectivity and environment validation (including hidden `--create-backend-db`).
  - `goe validate` — Cross-database row count and aggregation verification (`post_process_args(options)` + exit code propagation).
  - `goe sync` — Schema drift analysis and DDL synchronization (`orchestration_repo_client_factory` + `run_schema_sync` + `try ... finally` cleanup + exit code propagation).
  - `goe report` — Offload status reporting (`default="text"` and `default="summary"` preserved via `ParameterSource.DEFAULT`, plus hidden `-d/--demo`).
  - `goe logmgr` — Log rotation and retention management (falls back to `LOG_MV_MINS` env var when `--min-age-minutes` is omitted).
  - `goe listener` — Litestar/Granian ASGI listener server (`invoke_without_command=True` so bare `goe listener` and `bin/listener` start the server by default and forward group-level flags via `ctx.obj`, alongside `goe listener start` and `goe listener status`).

- **Zero-Type-Loss Lazy Subcommand Bindings**: [`src/goe/cli/_lazy.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/_lazy.py) provides `resolve_lazy_attribute` and `bind_lazy_imports`. Subcommand modules (`src/goe/cli/commands/*.py`) and `src/goe/cli/common.py` declare heavy backend imports inside a module-level `if TYPE_CHECKING:` block, expose PEP 562 `__getattr__` backed by `_LAZY_IMPORTS`, and call `bind_lazy_imports(__name__, _LAZY_IMPORTS)` at callback entry. This keeps CLI help/menu rendering at ~170 ms (zero heavy backend imports) while preserving 100% of `mypy`/`pyright` static type hints at call sites (`LOAD_GLOBAL`), zero nested imports (`PLC0415`), and 100% `@patch("goe.cli.commands.<cmd>.<symbol>")` compatibility.
  - Note: Keep `from goe.cli.main import cli, main` eager in `src/goe/cli/__init__.py` because `goe.cli.main` is lightweight (<3 ms) and lazy attribute resolution on `goe.cli` would collide with the `goe.cli.main` submodule attribute.
  - Transitive import decoupling in [`src/goe/listener/utils/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/__init__.py) (`orchestrate` and `ping` resolved lazily) and [`src/goe/util/goe_log_fh.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/goe_log_fh.py) (`GCS_MIN_BLOCK_SIZE` resolved lazily on `gs://` paths) prevents `offload_messages.py` from eagerly pulling `litestar`, `numpy`, or `gcsfs` into non-Listener CLI commands.

## Legacy `bin/` Wrapper Delegators

Legacy scripts in [`bin/`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/bin/) (`bin/offload`, `bin/connect`, `bin/agg_validate`, `bin/schema_sync`, `bin/logmgr`, `bin/listener`, `bin/offload_status_report`) are maintained strictly as lightweight in-process Python delegators that emit `DeprecationWarning` notices and invoke the corresponding `goe <subcommand>` entrypoint.



