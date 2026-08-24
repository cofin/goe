---
type: Task
id: rich_click_cli_overhaul_20260823:offload_command_migration
title: Implement goe offload Subcommand with Rich Options
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - task
  - cli
  - offload
  - rich-click
depends_on:
  - rich_click_cli_overhaul_20260823:cli_root_and_styling
files:
  - src/goe/cli/commands/offload.py
tests:
  - tests/unit
verification_strategy: behavior_tdd
---

# Task: Implement goe offload Subcommand with Rich Options

## Objective
Implement `goe offload` command migrating legacy options from `src/goe/orchestration/cli_entry_points.py` to structured Click options with option groups (Source Table, Target Options, Partitioning, Execution Mode).

## Implementation Details

1. Create `src/goe/cli/commands/offload.py`.
2. Define `@cli.command(name="offload")`:
   - Source table options: `-t, --table`, `-s, --schema`.
   - Execution options: `-x, --execute`, `--dry-run`, `--force`.
   - Partitioning options: `--partition-name`, `--older-than-date`, `--less-than-value`.
   - Target options: `--target-table-name`, `--target-dataset`.
3. Delegate to `goe.orchestration.offload_handler.offload_table()` with validated parameters.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: `goe offload --help` missing.
- **Final Evidence**: `uv run goe offload --help` displays all option groups cleanly; dry-run offload test executes with `CliRunner`.
