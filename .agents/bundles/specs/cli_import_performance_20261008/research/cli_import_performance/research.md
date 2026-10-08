---
type: Research
research_id: "cli_import_performance"
title: GOE CLI Import Performance & Startup Latency Optimization
description: Primary-source import-graph profiling and lazy-loading architectural research for the unified goe CLI
scope: architecture
tags:
  - research
  - cli
  - performance
  - imports
  - rich-click
status: stable
state: promoted
promoted_to: "cli_import_performance_20261008"
created_at: "2026-10-08T16:38:00Z"
updated_at: "2026-10-08T16:50:00Z"
---

# Research: GOE CLI Import Performance & Startup Latency Optimization (`cli_import_performance`)

## Research Question

Why does invoking the unified `goe` CLI (`uv run goe`, `goe --help`, `goe --version`, or `goe <subcommand> --help`) take ~1.5–1.6 seconds to render the terminal menu, and how can we reduce CLI startup and help-rendering latency by ~10x (~1.5s &rarr; ~150ms) while preserving all existing Click option metadata, `bin/*` wrappers, and unit test `@patch("goe.cli.commands.<cmd>.<symbol>")` seams?

## Scope & Method

- **Primary Sources Inspected**:
  - CLI Package & Entrypoints: [`src/goe/cli/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/__init__.py), [`src/goe/cli/main.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/main.py), [`src/goe/cli/config.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/config.py), [`src/goe/cli/common.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/common.py), [`src/goe/cli/console.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/console.py)
  - Subcommand Modules: [`src/goe/cli/commands/connect.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/connect.py), [`src/goe/cli/commands/listener.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/listener.py), [`src/goe/cli/commands/logmgr.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/logmgr.py), [`src/goe/cli/commands/offload.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/offload.py), [`src/goe/cli/commands/report.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/report.py), [`src/goe/cli/commands/sync.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/sync.py), [`src/goe/cli/commands/validate.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/validate.py)
  - Transitive Import Hotspots: [`src/goe/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/__init__.py), [`src/goe/config/orchestration_defaults.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/config/orchestration_defaults.py), [`src/goe/config/orchestration_config.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/config/orchestration_config.py), [`src/goe/config/config_validation_functions.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/config/config_validation_functions.py), [`src/goe/filesystem/goe_dfs.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/filesystem/goe_dfs.py), [`src/goe/offload/offload_messages.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_messages.py), [`src/goe/listener/utils/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/__init__.py), [`src/goe/listener/utils/orchestrate.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/orchestrate.py), [`src/goe/util/goe_log_fh.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/goe_log_fh.py), [`src/goe/util/json_tools.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/json_tools.py)
  - Unit Test Seams: [`tests/unit/cli/`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/)
- **Profiling Method**:
  - Measured cumulative and self module import durations via `python -X importtime -c "import goe.cli.main"` and isolated subprocess benchmarks (`time.perf_counter()`).

---

## Executive Summary

Profiling `goe.cli.main` reveals that **~1,171 ms of pure Python module import time** (~1,530–1,635 ms total wall-clock subprocess time) occurs before a single line of `cli()` executes—even when only rendering `goe`, `goe --help`, or `goe --version`.

By contrast, importing `rich_click`, `goe` root config auto-discovery (`dotenv`), and constructing the 7 Click subcommand definitions without their heavy backend execution dependencies takes **~156 ms** wall-clock (**a 10.5x speedup / ~90% latency reduction**).

Furthermore, two hidden transitive import cascades inside `goe.listener.utils.__init__` and `goe.util.goe_log_fh` add **~521 ms** of unnecessary imports (`litestar`, `numpy`, `lark`, and `gcsfs`) to every non-Listener CLI command execution (`offload`, `connect`, `sync`, `validate`, `report`).

---

## Empirical Import-Time Breakdown (`python -X importtime`)

### 1. End-to-End Subprocess Benchmarks

| Operation | Wall-Clock Latency | Notes |
| --- | --- | --- |
| `python -c "pass"` | **24.3 ms** | Python 3.14 interpreter baseline |
| `import rich_click` | **66.3 ms** | Click + Rich + RichHelpConfiguration |
| `import goe` (root package) | **87.8 ms** | `importlib.metadata.version` + `dotenv` `load_env()` |
| Proposed lightweight CLI (`rich_click` + `load_env` + 7 subcommand definitions + `get_help()`) | **156.5 ms** | **Target menu rendering latency (~10.5x faster)** |
| Current `import goe.cli.main` + `get_help()` | **1,573.3 – 1,636.8 ms** | Eagerly imports all 7 subcommand backends |
| `.venv/bin/goe --help` | **1,476.0 ms** | Installed console script |
| `uv run goe --help` | **1,492.6 ms** | `uv` wrapper + console script |

### 2. Cumulative Import Tree (`import goe.cli.main` = 1,171.21 ms in-process)

```text
1171.21 ms | goe.cli.main
 ├── 1017.89 ms | goe.cli.commands.connect
 │    └── 982.30 ms | goe.connect.connect
 │         └── 964.36 ms | goe.config.orchestration_config
 │              ├──  76.08 ms | oracledb (via goe.config.config_validation_functions)
 │              └── 839.76 ms | goe.filesystem.goe_dfs (google.api_core + offload_messages)
 │                   └── 754.36 ms | goe.offload.offload_messages
 │                        ├── 303.19 ms | goe.listener.utils.cache (triggers goe.listener.utils.__init__)
 │                        │    └── 300.33 ms | goe.listener.utils.orchestrate
 │                        │         ├── 161.54 ms | goe.listener.exceptions -> litestar, litestar.openapi
 │                        │         └── 138.54 ms | goe.orchestration.orchestration_lock -> predicate_offload -> numpy (90.6 ms), lark
 │                        ├── 243.94 ms | goe.util.goe_log_fh
 │                        │    └── 218.06 ms | gcsfs.core (aiohttp, google.auth, requests)
 │                        └── 206.34 ms | goe.util.json_tools
 │                             └── 206.03 ms | sqlspec.utils.serializers (triggers sqlspec.__init__ -> migrations/events)
 ├──   62.16 ms | goe.cli.commands.listener (granian: 28.2 ms, httpx: 31.6 ms, goe.listener.config: 2.3 ms)
 ├──   22.31 ms | goe.cli.commands.report (jinja2: 19.6 ms, oracle_offload_source_table: 1.0 ms)
 ├──    2.68 ms | goe.cli.commands.sync (incremental; 1,448.8 ms standalone)
 ├──    2.11 ms | goe.cli.commands.offload (incremental; 1,303.6 ms standalone)
 ├──    1.80 ms | goe.cli.commands.validate (incremental; 1,331.8 ms standalone)
 └──    0.55 ms | goe.cli.commands.logmgr
```

---

## Detailed Findings

### Finding IMP-1 (Critical): Eager Top-Level Backend Imports Across `src/goe/cli/commands/*.py`
- **Citations**:
  - [`src/goe/cli/main.py:11-17`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/main.py#L11-L17)
  - [`src/goe/cli/commands/connect.py:12-14`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/connect.py#L12-L14)
  - [`src/goe/cli/commands/listener.py:8-15`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/listener.py#L8-L15)
  - [`src/goe/cli/commands/offload.py:12-14`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/offload.py#L12-L14)
  - [`src/goe/cli/commands/report.py:12-15`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/report.py#L12-L15)
  - [`src/goe/cli/commands/sync.py:13-26`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/sync.py#L13-L26)
  - [`src/goe/cli/commands/validate.py:13-17`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/validate.py#L13-L17)
- **Analysis**:
  - Every `@click.command` and `@click.option` decorator in `src/goe/cli/commands/*.py` uses static strings and standard Click types (`str`, `int`, `bool`, `Path`, `click.Choice`). None of the Click command declarations depend on `goe.goe`, `goe.connect.connect`, `goe.listener.config`, `granian`, `httpx`, `goe.offload.offload_status_report`, `goe.schema_sync.schema_sync`, or `goe.scripts.agg_validate` at decoration/help-generation time.
  - Because those backend symbols are imported at module top-level, importing `goe.cli.main` (or running `goe`, `goe --help`, `goe <cmd> --help`, or `goe --version`) eagerly loads the entire GOE orchestration engine, Oracle driver, GCS filesystem, SQLSpec runtime, Litestar web framework, Granian ASGI server, Jinja2, and NumPy.
- **Unit Test Patch Seam Constraint**:
  - Existing unit tests in [`tests/unit/cli/`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/) patch backend symbols directly on the subcommand module namespaces:
    - `goe.cli.commands.connect.{check_config_path, run_connect}` ([`test_connect_command.py:18-19`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/test_connect_command.py#L18-L19))
    - `goe.cli.commands.listener.{Granian, httpx.get}` ([`test_listener_command.py:28,37`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/test_listener_command.py#L28-L37))
    - `goe.cli.commands.offload.offload_by_cli` ([`test_offload_command.py:47`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/test_offload_command.py#L47))
    - `goe.cli.commands.report.offload_status_report_run` ([`test_report_command.py:21`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/test_report_command.py#L21))
    - `goe.cli.commands.sync.{OrchestrationConfig, orchestration_repo_client_factory, run_schema_sync, OffloadMessages, get_log_fh, init, init_log, log_close}` ([`test_sync_command.py:21-28`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/test_sync_command.py#L21-L28))
    - `goe.cli.commands.validate.run_agg_validate` ([`test_validate_command.py:33`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tests/unit/cli/test_validate_command.py#L33))
  - Combining **top-level `if TYPE_CHECKING:` imports**, **PEP 562 module-level `__getattr__`**, and a **`bind_lazy_imports(__name__, _LAZY_IMPORTS)` helper** satisfies all four constraints simultaneously:
    1. **100% Static Type Preservation (`mypy` & `pyright`)**: Because every lazy symbol is imported explicitly inside a module-level `if TYPE_CHECKING:` block, static type checkers see the exact original function/class/constant signatures at every call site inside the command callback (e.g., `run_connect(options)` is statically typed as `Callable[[Namespace], Any]` rather than degrading to `Any` as would happen with `getattr(sys.modules[__name__], "run_connect")(options)`), as well as on external attribute accesses (`from goe.cli.commands.sync import run_schema_sync`).
    2. **Zero Function-Scoped (Nested) Imports**: All `import` statements remain strictly at module top-level (or in the module-level `if TYPE_CHECKING:` block), adhering to `PLC0415` and repository style rules.
    3. **Zero Eager Backend Imports on CLI Menu / Help**: Importing `goe.cli.commands.<cmd>` for `goe`, `goe --help`, or `goe <cmd> --help` executes zero backend imports.
    4. **100% `unittest.mock.patch(...)` Compatibility**:
       - When `@patch("goe.cli.commands.<cmd>.<symbol>")` runs before the command callback, `unittest.mock` resolves `<symbol>` via the module's PEP 562 `__getattr__` and injects a `MagicMock` into `module.__dict__["<symbol>"]`.
       - At the start of the command callback, `bind_lazy_imports(__name__, _LAZY_IMPORTS)` populates `module.__dict__[attr]` **only for keys not already present in `module.__dict__`** (so any `MagicMock` injected by `@patch` is preserved untouched).
       - Subsequent lines in the callback call the symbols directly by identifier (`LOAD_GLOBAL`), achieving full static type safety, zero nested imports, and seamless `@patch` support.

```python
from typing import TYPE_CHECKING, Any

from goe.cli._lazy import bind_lazy_imports, resolve_lazy_attribute

if TYPE_CHECKING:
    from goe.connect.connect import check_config_path, run_connect

_LAZY_IMPORTS: dict[str, tuple[str, str | None]] = {
    "check_config_path": ("goe.connect.connect", "check_config_path"),
    "run_connect": ("goe.connect.connect", "run_connect"),
}


def __getattr__(name: str) -> Any:
    """Lazily import heavy connect runtime dependencies on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
```

And inside `src/goe/cli/_lazy.py`:

```python
import importlib
import sys
from typing import Any

LazyImportMap = dict[str, tuple[str, str | None]]


def resolve_lazy_attribute(module_name: str, lazy_imports: LazyImportMap, name: str) -> Any:
    """Resolve and cache a lazily imported attribute on a module namespace."""
    target = lazy_imports.get(name)
    if target is None:
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
    target_module_name, target_attr = target
    imported = importlib.import_module(target_module_name)
    value = imported if target_attr is None else getattr(imported, target_attr)
    setattr(sys.modules[module_name], name, value)
    return value


def bind_lazy_imports(module_name: str, lazy_imports: LazyImportMap) -> None:
    """Populate module globals for all declared lazy imports Not already bound or patched."""
    module_dict = sys.modules[module_name].__dict__
    for name in lazy_imports:
        if name not in module_dict:
            resolve_lazy_attribute(module_name, lazy_imports, name)
```

### Finding IMP-2 (High): `src/goe/cli/__init__.py` Eagerly Imports `goe.cli.main`
- **Citations**: [`src/goe/cli/__init__.py:6`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/__init__.py#L6)
- **Analysis**:
  - `src/goe/cli/__init__.py` executes `from goe.cli.main import cli, main` at package import time.
  - Consequently, importing *any* submodule under `goe.cli.*` (such as `goe.cli.config`, `goe.cli.console`, or `goe.cli.common`) first executes `goe.cli.__init__`, which pulls in `goe.cli.main` and all 7 subcommand modules.
  - Replacing the eager import in `src/goe/cli/__init__.py` with `if TYPE_CHECKING: from goe.cli.main import cli, main` plus a PEP 562 `__getattr__` lazy re-export keeps static type hints on `from goe.cli import cli, main` intact while allowing `goe.cli.config`, `goe.cli.console`, and `goe.cli.common` to be imported in <60 ms.

### Finding IMP-3 (High): `src/goe/listener/utils/__init__.py` Pulls Litestar & NumPy (~303 ms) into Non-Listener CLI Commands
- **Citations**:
  - [`src/goe/offload/offload_messages.py:16`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_messages.py#L16) (`from goe.listener.utils.cache import MemorySyncCache as cache`)
  - [`src/goe/listener/utils/__init__.py:7-10`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/__init__.py#L7-L10)
  - [`src/goe/listener/utils/orchestrate.py:6-10`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/orchestrate.py#L6-L10)
  - [`src/goe/listener/exceptions/__init__.py:6-15`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/exceptions/__init__.py#L6-L15)
- **Analysis**:
  - `MemorySyncCache` in `src/goe/listener/utils/cache.py` has zero third-party dependencies (only Python stdlib `fnmatch`, `logging`, `threading`, `time`, `warnings`, `datetime`).
  - However, when `offload_messages.py` imports `goe.listener.utils.cache`, Python first executes `src/goe/listener/utils/__init__.py`, which eagerly imports `from goe.listener.utils import orchestrate, system`.
  - `orchestrate.py` imports `goe.listener.exceptions` (which loads `litestar`, `litestar.app`, `litestar.openapi`: **161.5 ms**) and `goe.orchestration.orchestration_lock` (which loads `orchestration_metadata` &rarr; `predicate_offload` &rarr; `numpy` + `lark`: **138.5 ms**).
  - Converting `src/goe/listener/utils/__init__.py` to `if TYPE_CHECKING:` + PEP 562 `__getattr__` lazy re-exports eliminates **~300 ms** of Litestar/OpenAPI and NumPy import overhead from every `offload_messages` consumer without losing static module export types.

### Finding IMP-4 (Medium): `src/goe/util/goe_log_fh.py` Eagerly Imports `gcsfs` (~218 ms) at Module Top-Level
- **Citations**:
  - [`src/goe/util/goe_log_fh.py:4-5,38`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/goe_log_fh.py#L4-L38)
  - [`src/goe/offload/offload_messages.py:19`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/offload/offload_messages.py#L19)
  - [`src/goe/config/config_validation_functions.py:44`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/config/config_validation_functions.py#L44)
- **Analysis**:
  - `src/goe/util/goe_log_fh.py` is imported by both `offload_messages.py` and `config_validation_functions.py` (which only calls the 2-line string check `is_valid_path_for_logs(path)`).
  - Line 5 (`from gcsfs.core import GCS_MIN_BLOCK_SIZE`) eagerly imports `gcsfs.core` (and transitively `aiohttp`, `google.auth`, `requests`, `decorator`), adding **218.1 ms** to startup even when logs are written to local disk (`$OFFLOAD_HOME/log`), which is 99%+ of CLI runs.
  - `GCS_MIN_BLOCK_SIZE` is only used when `path.startswith("gs://")` inside `GOELogFileHandle._get_fs()`. Resolving `GCS_MIN_BLOCK_SIZE` lazily via `importlib.import_module("gcsfs.core")` only when opening a `gs://` log URI saves **~218 ms** across all local-log CLI executions.

### Finding IMP-5 (Low): `src/goe/cli/common.py` Eagerly Imports `goe.config.orchestration_defaults` (~36 ms)
- **Citations**: [`src/goe/cli/common.py:13,157,161`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/common.py#L13)
- **Analysis**:
  - `src/goe/cli/common.py` imports `from goe.config import orchestration_defaults` at module top-level, which imports `goe.offload.offload_constants` and `goe.util.misc_functions` (including `dateutil.parser`: **30.7 ms**).
  - `orchestration_defaults` is only accessed inside `extract_common_options()` for `log_path_default()` and `log_level_default()`. Guarding `from goe.config import orchestration_defaults` under `if TYPE_CHECKING:` and binding it lazily via `bind_lazy_imports(__name__, _LAZY_IMPORTS)` in `extract_common_options()` keeps `--help` and `--version` completely free of `misc_functions` / `dateutil` imports while retaining full static types.

---

## Recommended Architecture & Implementation Plan

1. **Zero-Type-Loss Lazy Subcommand & Backend Symbol Resolution (`src/goe/cli/`)**:
   - Create `src/goe/cli/_lazy.py` with `resolve_lazy_attribute()` and `bind_lazy_imports()`.
   - Replace eager `from goe.cli.main import cli, main` in [`src/goe/cli/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/__init__.py) with `if TYPE_CHECKING:` + PEP 562 `__getattr__`.
   - Convert heavy runtime imports in [`src/goe/cli/commands/connect.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/connect.py), [`listener.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/listener.py), [`offload.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/offload.py), [`report.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/report.py), [`sync.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/sync.py), [`validate.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/validate.py), and [`common.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/common.py) to `if TYPE_CHECKING:` + PEP 562 `__getattr__` + `bind_lazy_imports(__name__, _LAZY_IMPORTS)` at callback entry so every symbol call remains directly typed (`LOAD_GLOBAL`) with zero `Any` degradation.
   - Optionally use a `LazyRichGroup(click.RichGroup)` on `cli` in [`src/goe/cli/main.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/main.py) (with `if TYPE_CHECKING:` imports of all 7 subcommands) so invoking a single subcommand only imports that specific subcommand module.
2. **Transitive Import Decoupling (`src/goe/listener/utils/__init__.py` & `src/goe/util/goe_log_fh.py`)**:
   - Convert [`src/goe/listener/utils/__init__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/__init__.py) to `if TYPE_CHECKING:` + PEP 562 `__getattr__` so importing `goe.listener.utils.cache` does not eagerly import `orchestrate.py` (&rarr; `litestar`, `numpy`).
   - Defer `gcsfs.core.GCS_MIN_BLOCK_SIZE` resolution in [`src/goe/util/goe_log_fh.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/goe_log_fh.py) until a `gs://` path is actually opened.
3. **Verification Gates**:
   - Verify `uv run mypy src/goe` passes with 0 errors and all call-site types preserved.
   - Add an import-isolation and latency test in `tests/unit/cli/test_cli_root.py` verifying that `goe --help` and `goe offload --help` do not load `litestar`, `granian`, `oracledb`, `gcsfs`, or `goe.goe` into `sys.modules`.
   - Verify all existing unit tests in `tests/unit/cli/` pass without modifying their `@patch(...)` targets.

