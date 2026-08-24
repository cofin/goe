---
type: Task
id: rich_click_cli_overhaul_20260823:offload_command_migration
title: Implement goe offload Subcommand with Structured Click Option Groups
description: Implement goe offload subcommand migrating legacy optparse options to structured Click option groups.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - migration
  - cli
  - offload
  - rich-click
depends_on:
  - rich_click_cli_overhaul_20260823:cli_root_and_styling
files:
  - src/goe/cli/commands/offload.py
  - src/goe/orchestration/cli_entry_points.py
tests:
  - tests/unit/cli/test_offload_command.py
verification_strategy: behavior_tdd
---

# Task: Implement goe offload Subcommand with Structured Click Option Groups

## Objective
Implement `src/goe/cli/commands/offload.py` defining the `goe offload` subcommand. Migrate all 40+ legacy options from `src/goe/goe.py` and `src/goe/offload/offload.py` into 5 distinct `rich-click` option groups, validate inputs, adapt parameters to an options namespace, and delegate execution to `OrchestrationRunner().offload(...)`.

## Implementation Details
1. Configure 5 option groups in `click.rich_click.OPTION_GROUPS["goe offload"]`:
   - Target & Source Selection
   - Execution & Control
   - Partitioning & Incremental Controls
   - Data Types & Schema Controls
   - Transport & Performance
2. Implement `@click.command("offload")` with all options.
3. Adapt arguments to `offload_by_cli(options)`.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/cli/test_offload_command.py -v
  ```
- **Expected Output**: Offload CLI option parsing and adapter tests pass green.\n