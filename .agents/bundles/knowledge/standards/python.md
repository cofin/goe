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
2. **Compatibility**: Target Python >= 3.10 through 3.13.
3. **Environment & Tooling**: Use `uv` for Python package and environment management (`uv run` prefix when executing Python tools). Build backend is managed via `hatchling.build` and dependencies via PEP 735 `[dependency-groups]`.

## Code Style & Formatting

- **Formatter & Linter**: Code must be formatted and linted with `ruff` (`line-length = 120`). Run `make format` or `uv run ruff format src tests tools` and `uv run ruff check src tests tools` before submitting changes.
- **Imports**: All imports must be placed at the top of the file, organized into standard library, third-party packages, and internal `goe` modules. Never use deferred imports within function scopes unless breaking an unavoidable circular dependency.
- **Comments & Docstrings**:
  - Never use in-line comments inside functions.
  - If code requires explanation, document the rationale, edge cases, and design choices within the class or function docstring following PEP 257 (one-line summary, blank line, detailed description).

## Type Hinting & Annotations

- Follow PEP 585 and PEP 604 conventions:
  - Use built-in collection types (`dict`, `list`, `set`, `tuple`) rather than `typing.Dict`, `typing.List`, etc.
  - Use pipe union syntax (`str | None`, `int | float`) where supported or `from __future__ import annotations`.
- Explicitly annotate function parameters, return values, and public class attributes.

## Exception Handling

- Derive domain errors from `OffloadException` in `src/goe/exceptions.py`.
- Never catch generic `Exception` without re-raising or wrapping in a meaningful domain exception with contextual diagnostics.
- Always clean up external resources (database cursors, files, locks) using `try...finally` blocks or context managers.
