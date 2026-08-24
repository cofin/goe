---
type: Task
id: rich_click_cli_overhaul_20260823:sync_logmgr_listener_commands
title: Implement goe sync, goe logmgr, and goe listener Subcommands
description: Implement goe sync, goe logmgr, and goe listener subcommands within the unified CLI suite.
state: complete
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T23:30:00Z"
tags:
  - feature
  - cli
  - sync
  - listener
  - logmgr
depends_on:
  - rich_click_cli_overhaul_20260823:cli_root_and_styling
files:
  - src/goe/cli/commands/sync.py
  - src/goe/cli/commands/logmgr.py
  - src/goe/cli/commands/listener.py
  - src/goe/schema_sync/schema_sync.py
tests:
  - tests/unit/cli/test_sync_command.py
  - tests/unit/cli/test_logmgr_command.py
verification_strategy: behavior_tdd
---

# Task: Implement goe sync, goe logmgr, and goe listener Subcommands

## Objective
Implement `src/goe/cli/commands/sync.py` (schema drift analysis and automated DDL migration), `src/goe/cli/commands/logmgr.py` (cross-platform log rotation and archive management replacing bash script), and `src/goe/cli/commands/listener.py` (service startup, stop, and status).

## Implementation Details
1. Create `src/goe/cli/commands/sync.py` executing `schema_sync`.
2. Create `src/goe/cli/commands/logmgr.py` implementing pure Python log archiving and purging.
3. Create `src/goe/cli/commands/listener.py` exposing `start`, `stop`, `status` subcommands.

## Verification Strategy
- **Strategy**: `behavior_tdd`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/cli/test_sync_command.py tests/unit/cli/test_logmgr_command.py -v
  ```
- **Expected Output**: Sync and Logmgr unit tests pass green.\n