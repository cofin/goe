---
type: Reference
title: Centralized Rich-Click CLI
description: Unified rich-click goe CLI architecture in src/goe/cli/ (sole entrypoint)
tags:
  - pattern
  - cli
  - rich-click
  - entrypoints
updated_at: "2026-10-11T15:09:00Z"
---

# Centralized Rich-Click CLI

## Single Authoritative CLI Entrypoint (`src/goe/cli/`)

- **Package Script**: [`pyproject.toml`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/pyproject.toml) registers the unified CLI entrypoint via `[project.scripts] goe = "goe.cli.main:cli"`.
- **Styling & Command Groups**: [`src/goe/cli/config.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/config.py) configures `rich-click` via `click.RichHelpConfiguration(theme="slim", text_markup="rich", style_options_panel_box="BLANK", style_commands_panel_box="BLANK", command_groups=COMMAND_GROUPS, option_groups=OPTION_GROUPS, ...).dump_to_globals()` with the Google Cloud color palette (`#4285F4`, `#34A853`, `#FBBC04`, `#EA4335`), borderless modern section headings (`Core Orchestration Commands`, `Service & Maintenance Commands`), and logical option groups for complex commands.
- **Shared Common & Global Options**: [`src/goe/cli/common.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/common.py) provides `@common_options` and `extract_common_options(ctx, kwargs)` so global flags (`--version`, `-v/--verbose`, `--vv/--vverbose`, `-q/--quiet`, `--no-ansi`) and the 7 common/hidden engine options (`--log-path`, `--log-level`, `--no-version-check`, `--error-before-step`, `--error-after-step`, `--error-on-token`, `--suppress-stdout`) are accepted both on the root `goe` group and on subcommands (supporting trailing flags), falling back to `orchestration_defaults.log_path_default()` and `orchestration_defaults.log_level_default()` so `options.log_path` is never overwritten with `None`.
- **Modular Subcommands**: Implemented under [`src/goe/cli/commands/`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/):
  - `goe offload` — Data offloading with structured option groups (`OPTION_GROUPS["goe offload"]`). Options validated by downstream string validators (such as `--older-than-days` via `check_opt_is_posint`) remain `str`-typed.
  - `goe connect` — Pre-flight connectivity and environment validation (including hidden `--create-backend-db`).
  - `goe validate` — Cross-database row count and aggregation verification (`post_process_args(options)` + exit code propagation).
  - `goe sync` — Schema drift analysis and DDL synchronization (`orchestration_repo_client_factory` + `run_schema_sync` + `try ... finally` cleanup + exit code propagation).
  - `goe report` — Offload status reporting (`default="text"` and `default="summary"` preserved via `ParameterSource.DEFAULT`, plus hidden `-d/--demo`).
  - `goe logmgr` — Log rotation and retention management (falls back to `LOG_MV_MINS` env var when `--min-age-minutes` is omitted).
  - `goe listener` — Litestar/Granian ASGI listener server (`invoke_without_command=True` so bare `goe listener` starts the server by default and forward group-level flags via `ctx.obj`, alongside `goe listener start` and `goe listener status`).

- **Zero-Type-Loss Lazy Subcommand Bindings**: [`src/goe/cli/_lazy.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/_lazy.py) provides `resolve_lazy_attribute` and `bind_lazy_imports`. Subcommand modules (`src/goe/cli/commands/*.py`) and `src/goe/cli/common.py` declare heavy backend imports inside a module-level `if TYPE_CHECKING:` block, expose PEP 562 `__getattr__` backed by `_LAZY_IMPORTS`, and call `bind_lazy_imports(__name__, _LAZY_IMPORTS)` at callback entry. This keeps CLI help/menu rendering at ~170 ms (zero heavy backend imports) while preserving 100% of `mypy`/`pyright` static type hints at call sites (`LOAD_GLOBAL`), zero nested imports (`PLC0415`), and 100% `@patch("goe.cli.commands.<cmd>.<symbol>")` compatibility.
  - Note: Keep `from goe.cli.main import cli, main` eager in `src/goe/cli/__init__.py` because `goe.cli.main` is lightweight (<3 ms) and lazy attribute resolution on `goe.cli` would collide with the `goe.cli.main` submodule attribute.
  - Transitive import decoupling in [`src/goe/listener/utils/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/__init__.py) (`orchestrate` resolved lazily) and [`src/goe/util/goe_log_fh.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/goe_log_fh.py) (`GCS_MIN_BLOCK_SIZE` resolved lazily on `gs://` paths) prevents `offload_messages.py` from eagerly pulling `litestar`, `numpy`, or `gcsfs` into non-Listener CLI commands.

## No Wrapper Scripts

The `goe` console script is the only CLI entrypoint. The legacy `bin/` delegators were deleted in PRD 1 Chapter 1.1; packaging (`Makefile` `target`), Cloud Run (`docs/google_cloud_run/goe.sh`), and docs invoke `goe <subcommand>` directly.

## Idiomatic Code Patterns & Architecture Seams

### 1. Zero-Type-Loss Lazy Subcommand Binding (`src/goe/cli/_lazy.py`)
To achieve sub-200ms CLI startup without sacrificing `mypy` static type checking or unit test mocking:
- Heavy domain dependencies are placed strictly under `if TYPE_CHECKING:` at module top-level.
- Module-level PEP 562 `__getattr__` delegates to `resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)`.
- Command callback bodies invoke `bind_lazy_imports(__name__, _LAZY_IMPORTS)` before calling the implementation.
- `bind_lazy_imports` checks `if name not in module_dict:` before binding, guaranteeing that any mock established via `unittest.mock.patch("goe.cli.commands.<cmd>.<symbol>")` is preserved.

### 2. Typed `msgspec.Struct` Option Construction & Normalization Seam
Every operational subcommand (`connect`, `offload`, `report`, `sync`, `validate`) constructs its typed `msgspec.Struct` option model from [`src/goe/config/options.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/config/options.py) (`ConnectOptions`, `OffloadOperationOptions`, `StatusReportOptions`, `SchemaSyncOptions`, `AggValidateOptions`) via `.from_mapping(options_dict)` without touching `optparse`:
- Precedence is strictly: struct field defaults (`orchestration_defaults.*_default()`) $\to$ `extract_common_options(ctx, kwargs)` $\to$ derived negation/mode flags (`--verify`/`--no-verify`, `--no-modify-hybrid-view`, `-x`/`--execute`) $\to$ non-`None` CLI `kwargs` (converting non-empty tuples from `multiple=True` options to lists).
- **`goe validate`**: Constructs `AggValidateOptions.from_mapping(options_dict)`, invokes `post_process_args(options)` (`src/goe/scripts/agg_validate.py`) to parse CSV filter/select expressions and convert string clauses into structured 3-tuples before calling `run_agg_validate(options)`, and propagates exit codes via `sys.exit(0 if ret else 1)`.
- **`goe sync`**: Constructs `SchemaSyncOptions.from_mapping(options_dict)`, invokes `normalise_schema_sync_options(options)`, and wraps execution in a `try ... finally` block ensuring `repo_client.close()` and `log_close()` are called, propagating non-zero returns via `sys.exit(return_code)`.

### 3. Case-Insensitive Choice Default Preservation
When Click choices use `click.Choice(["HTML", "TEXT", ...], case_sensitive=False)`, Click normalizes `default="text"` to uppercase `"TEXT"`. When downstream engines require lowercase defaults:
```python
if k == "output_format" and ctx.get_parameter_source(k) == click.core.ParameterSource.DEFAULT:
    options_dict[k] = v.lower()
```

### 4. Option Group Test Reflection Pattern
Test suites should dynamically verify that all option flags registered in `OPTION_GROUPS` actually exist in the Click command definition:
```python
defined_opts = {opt for param in command.params for opt in (*param.opts, *param.secondary_opts)}
for group in click.rich_click.OPTION_GROUPS["goe offload"]:
    for flag in group["options"]:
        assert flag in defined_opts
```

## Hard-Won Gotchas & Edge Cases

1. **Rich ANSI Sequences in CI**: GitHub Actions with `TERM=xterm-256color` forces ANSI color sequences into Rich terminal outputs even in headless runners. Unit tests asserting CLI text output must use `click.unstyle(result.output)` before making substring or regex assertions.
2. **String Option Type Preservation**: Options validated by downstream regex validators (such as `--older-than-days` via `re.match(r"^\d+$", v)` in `check_opt_is_posint`) must not be cast to `type=int` in Click, which causes runtime `TypeError`.
3. **Repeatable Options (Tuple to List)**: Click converts options with `multiple=True` (e.g. `--transform-column`) to tuples. Downstream GOE orchestration expects lists for concatenation and iteration; convert via `isinstance(v, tuple): options_dict[k] = list(v)`.
4. **Environment Variable Fallback with `default=None`**: When a CLI option provides an environment variable fallback (e.g. `LOG_MV_MINS` in `goe logmgr`), the Click option default must be `default=None` so the CLI parser can distinguish between an omitted option and an explicit argument.



