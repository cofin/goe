---
type: Task
id: rich_click_cli_overhaul_20260823:bin_legacy_wrappers_and_testing
title: Provide Backward-Compatible bin/ Wrappers and Comprehensive CLI Test Suite
description: Update legacy bin/ scripts as backward-compatible delegation wrappers and add CLI unit tests.
state: complete
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T23:30:00Z"
tags:
  - refactor
  - cli
  - wrappers
  - compatibility
  - test
depends_on:
  - rich_click_cli_overhaul_20260823:cli_root_and_styling
  - rich_click_cli_overhaul_20260823:offload_command_migration
  - rich_click_cli_overhaul_20260823:connect_and_validate_commands
  - rich_click_cli_overhaul_20260823:sync_logmgr_listener_commands
files:
  - bin/offload
  - bin/connect
  - bin/agg_validate
  - bin/schema_sync
  - bin/logmgr
  - bin/listener
  - bin/offload_status_report
  - tests/unit/cli/
tests:
  - tests/unit/cli/
verification_strategy: behavior_tdd
---

# Task: Provide Backward-Compatible bin/ Wrappers and Comprehensive CLI Test Suite

## Objective
Update all legacy scripts in `bin/` (`offload`, `connect`, `agg_validate`, `schema_sync`, `logmgr`, `listener`, `offload_status_report`) to delegate cleanly to `goe <subcommand> "$@"` with a deprecation warning, and author a comprehensive test suite across `tests/unit/cli/`.

## Target Wrapper Pattern
```bash
#!/usr/bin/env bash
echo "DEPRECATION WARNING: '$0' is deprecated. Use 'goe <subcommand>' instead." >&2
exec goe <subcommand> "$@"
```

## Itemized Checklist
- [ ] Update `bin/offload` -> `exec goe offload "$@"`.
- [ ] Update `bin/connect` -> `exec goe connect "$@"`.
- [ ] Update `bin/agg_validate` -> `exec goe validate "$@"`.
- [ ] Update `bin/schema_sync` -> `exec goe sync "$@"`.
- [ ] Update `bin/logmgr` -> `exec goe logmgr "$@"`.
- [ ] Update `bin/listener` -> `exec goe listener start "$@"`.
- [ ] Run full `tests/unit/cli/` test suite with `CliRunner`.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/cli/ -v
  ```
- **Expected Output**: 100% passing CLI unit tests.\n