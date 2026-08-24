---
type: Task
id: rich_click_cli_overhaul_20260823:cli_root_and_styling
title: Build Root CLI Entrypoint with Rich-Click Configuration
description: Build unified root CLI entrypoint in src/goe/cli/main.py with rich-click configuration and styling.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - feature
  - cli
  - rich-click
  - entrypoint
depends_on:
files:
  - src/goe/cli/main.py
  - pyproject.toml
tests:
  - tests/unit
verification_strategy: behavior_tdd
---

# Task: Build Root CLI Entrypoint with Rich-Click Configuration

## Objective
Create `src/goe/cli/main.py` configuring `rich-click` global settings, top-level `@click.group`, version display, and register `goe` in `[project.scripts]`.

## Implementation Details

1. Configure `rich-click` in `src/goe/cli/main.py`:
   - `click.rich_click.USE_RICH_MARKUP = True`
   - `click.rich_click.SHOW_ARGUMENTS = True`
   - `click.rich_click.GROUP_ARGUMENTS_OPTIONS = True`
   - `click.rich_click.STYLE_ERRORS_SUGGESTION = "yellow italic"`
   - `click.rich_click.ERRORS_SUGGESTION = "Try running '--help' for available commands."`
2. Create root CLI group `cli()`:
   - Include version option `@click.version_option(package_name="goe-framework", prog_name="GOE")`.
3. Register `[project.scripts] goe = "goe.cli.main:cli"` in `pyproject.toml`.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Command `goe --help` fails as unrecognized.
- **Final Evidence**: `uv run goe --help` displays styled Rich CLI help text; `uv run goe --version` prints current version.
