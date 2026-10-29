---
type: Guide
title: Python Development Standards
description: Coding standards, formatting, docstrings, typing rules, and exception handling for Python in GOE
tags:
  - guide
  - standards
  - python
  - coding-conventions
---

# Python Development Standards

## Core Principles

1. **Clarity & Readability**: Write clean, modular, and explicit Python code. Avoid clever tricks where simple constructs suffice.
2. **Compatibility**: Target Python >= 3.12 through 3.14.
3. **Environment & Tooling**: Use `uv` for Python package and environment management (`uv run` prefix when executing Python tools). Build backend is managed via `hatchling.build` and dependencies via PEP 735 `[dependency-groups]`.

## Code Style, Member Ordering & Formatting

- **Formatter & Linter**: Code must be formatted and linted with `ruff` (`line-length = 120`). Run `make format` or `uv run ruff format .` and `uv run ruff check .` before submitting changes.
- **Dead-Code Enforcement (`ERA001`, `F401`, `F841`)**: `[tool.ruff.lint]` in [`pyproject.toml`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/pyproject.toml) enforces `ERA` (commented-out code), `F401` (unused imports), and `F841` (unused local variables) across `src/goe/` and `tests/`. Delete unused code and imports rather than commenting them out.
- **Copyright & License Headers**: All source files must start with the standard 2-line SPDX header (`# SPDX-FileCopyrightText: <year> The GOE Authors` and `# SPDX-License-Identifier: Apache-2.0`), automatically enforced via Ruff `CPY001`.
- **Imports & Optional Dependency Guards**:
  - Place all imports at module top-level (or in a module-level `if TYPE_CHECKING:` block for type-only imports), organized into standard library, third-party packages, and internal `goe` modules.
  - When a module imports third-party packages from optional extras (`hadoop`: `hdfs`, `requests_kerberos`, `impyla`, `thrift_sasl`; `snowflake`; `sql_server`: `pymssql`; `synapse`/`teradata`: `pyodbc`) and is imported by core/connect modules in base CI (`uv sync --dev --locked`), guard those imports at module top-level with `try: ... except ModuleNotFoundError:`. If a class in the module subclasses an optional base class (e.g. `class GOEWebHdfsClient(KerberosClient)` in [`src/goe/filesystem/web_hdfs.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/filesystem/web_hdfs.py)), bind the fallback to `object` (not `None`) so class creation succeeds at import time.
- **Public-Before-Private Function & Method Ordering**:
  - In every module and class under `src/goe/`, group all public functions/methods and dunder lifecycle methods (`__init__`, `__del__`, `__enter__`, `__exit__`, `__str__`, `__getattr__`, etc.) at the top of the module or class body (`# PUBLIC METHODS`), and place all private (`_...`) helper functions/methods at the bottom (`# PRIVATE METHODS`).
- **Comments & Docstrings**:
  - Never use in-line comments inside functions.
  - If code requires explanation, document the rationale, edge cases, and design choices within the class or function docstring following PEP 257 (one-line summary, blank line, detailed description).

## Type Hinting & Strict `mypy` Enforcement

- **PEP 585 & PEP 604**:
  - Use built-in collection types (`dict`, `list`, `set`, `tuple`) rather than `typing.Dict`, `typing.List`, etc., and `collections.abc` for `Sequence`, `Mapping`, `Iterable`, `Callable`, `Iterator`.
  - Use pipe union syntax (`str | None`, `int | float`). Do not add `from __future__ import annotations` to modules defining `msgspec.Struct` classes (`msgspec` resolves field annotations at class definition time).
- **Strict `mypy` Ratchet (`[tool.mypy]`)**:
  - `pyproject.toml` enforces `check_untyped_defs = true`, `disallow_incomplete_defs = true`, `warn_no_return = true`, `warn_redundant_casts = true`, `warn_unused_configs = true`, `warn_unused_ignores = true`, and `disable_error_code = []` across all 245 source files in `src/goe/` (only `tests.*` has `ignore_errors = true`).
  - **Zero `# type: ignore` Directives**: Never add `# type: ignore` in `src/goe/`. Resolve type narrowing via explicit annotations, `isinstance` / `is not None` guards, `assert`, or `typing.cast`.

## Exception Handling & Architecture Boundary Gate

- Derive domain errors from `GOEError` in [`src/goe/exceptions.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/exceptions.py) (`ConfigurationError(exit_code=2)`, `ValidationError(exit_code=2)`, `AuthenticationError(exit_code=1)`, `FrontendError(exit_code=1)`, `BackendError(exit_code=1)`, `TransportError(exit_code=1)`, `PersistenceError(exit_code=1)`, `OrchestrationError(exit_code=1)`, plus `OffloadException(GOEError)` and `OptionValueError = OffloadOptionError(ValidationError)`).
- Never catch generic `Exception` without re-raising or wrapping in a meaningful domain exception with contextual diagnostics.
- Always clean up external resources (database cursors, files, locks) using `try...finally` blocks or context managers.
- Run [`tools/verify_architecture.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tools/verify_architecture.py) (wired into `make lint` and baselined via [`tools/architecture_baseline.toml`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/tools/architecture_baseline.toml)) to enforce `raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`, and `stale-baseline` rules.

