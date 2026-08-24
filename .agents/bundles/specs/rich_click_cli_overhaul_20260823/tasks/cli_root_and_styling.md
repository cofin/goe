---
type: Task
id: rich_click_cli_overhaul_20260823:cli_root_and_styling
title: Build Root CLI Entrypoint with Rich-Click Configuration and Console Styling
description: Build unified root CLI entrypoint in src/goe/cli/main.py with rich-click configuration and styling.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - feature
  - cli
  - rich-click
  - entrypoint
depends_on: []
files:
  - src/goe/cli/__init__.py
  - src/goe/cli/main.py
  - src/goe/cli/config.py
  - src/goe/cli/console.py
  - pyproject.toml
tests:
  - tests/unit/cli/test_cli_root.py
verification_strategy: behavior_tdd
---

# Task: Build Root CLI Entrypoint with Rich-Click Configuration and Console Styling

## Objective
Create `src/goe/cli/` root package with `main.py`, `config.py`, and `console.py`. Configure `rich-click` global settings, define the root `@click.group` `cli`, add common flags (`--verbose`, `--vv`, `--quiet`, `--no-ansi`, `--version`), establish command groups ("Core Orchestration Commands", "Service & Maintenance Commands"), and register `goe = "goe.cli.main:cli"` in `pyproject.toml` under `[project.scripts]`.

## Implementation Details
1. Create `src/goe/cli/config.py` configuring rich-click styling and command groups.
2. Create `src/goe/cli/console.py` providing shared Rich console and message helpers.
3. Create `src/goe/cli/main.py` with `@click.group` `cli` and subcommands registration.
4. Register `goe = "goe.cli.main:cli"` in `pyproject.toml`.
5. Author `tests/unit/cli/test_cli_root.py`.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/cli/test_cli_root.py -v
  ```
- **Expected Output**: Root CLI tests pass green.\n