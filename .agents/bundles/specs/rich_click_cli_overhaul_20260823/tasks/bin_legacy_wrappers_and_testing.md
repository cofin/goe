---
type: Task
id: rich_click_cli_overhaul_20260823:bin_legacy_wrappers_and_testing
title: Provide Backward-Compatible bin/ Wrappers and CLI Unit Test Suite
description: Update legacy bin/ scripts as backward-compatible delegation wrappers and add CLI unit tests.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - refactor
  - cli
  - wrappers
  - compatibility
  - test
depends_on:
  - rich_click_cli_overhaul_20260823:offload_command_migration
  - rich_click_cli_overhaul_20260823:connect_and_validate_commands
  - rich_click_cli_overhaul_20260823:sync_logmgr_listener_commands
files:
  - bin/offload
  - bin/connect
  - bin/agg_validate
  - bin/schema_sync
  - bin/logmgr
  - tests/unit/cli/
tests:
  - tests/unit
verification_strategy: behavior_tdd
---

# Task: Provide Backward-Compatible bin/ Wrappers and CLI Unit Test Suite

## Objective
Update existing executable scripts in `bin/` (`offload`, `connect`, `agg_validate`, `schema_sync`, `logmgr`) to delegate to `goe <subcommand>` with deprecation notices, and author a complete unit test suite for all CLI commands using Click's `CliRunner`.

## Implementation Details

1. Update wrapper scripts in `bin/`:
   - `bin/offload` -> delegates to `uv run goe offload "$@"`.
   - `bin/connect` -> delegates to `uv run goe connect "$@"`.
   - `bin/agg_validate` -> delegates to `uv run goe validate "$@"`.
   - `bin/schema_sync` -> delegates to `uv run goe sync "$@"`.
   - `bin/logmgr` -> delegates to `uv run goe logmgr "$@"`.
2. Create unit tests in `tests/unit/cli/`:
   - Test help messages, argument validation, and option parsing using `click.testing.CliRunner`.
   - Assert exit codes and error output format.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Legacy bash scripts invoking deprecated optparse entrypoints.
- **Final Evidence**: `uv run pytest tests/unit/cli/` passes 100% green; `bin/offload --help` successfully forwards to `goe offload --help`.
