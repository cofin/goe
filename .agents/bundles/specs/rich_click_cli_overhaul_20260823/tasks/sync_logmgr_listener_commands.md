---
type: Task
id: rich_click_cli_overhaul_20260823:sync_logmgr_listener_commands
title: Implement goe sync, goe logmgr, and goe listener Subcommands
description: Implement goe sync, goe logmgr, and goe listener subcommands within the unified CLI suite.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
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
tests:
  - tests/unit
verification_strategy: behavior_tdd
---

# Task: Implement goe sync, goe logmgr, and goe listener Subcommands

## Objective
Implement `goe sync` (`schema_sync` drift detection & DDL execution), `goe logmgr` (log rotation & archiving), and `goe listener` (listener service runner) subcommands in the unified Click CLI.

## Implementation Details

1. Create `src/goe/cli/commands/sync.py`:
   - Inspect schema drift between source RDBMS and target DW; render planned DDL modifications with Rich syntax highlighting.
2. Create `src/goe/cli/commands/logmgr.py`:
   - Purge or archive old offload logs from `$OFFLOAD_HOME/log/`.
3. Create `src/goe/cli/commands/listener.py`:
   - Start and stop the Listener service and workers.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Missing `goe sync`, `goe logmgr`, and `goe listener` commands.
- **Final Evidence**: `uv run goe sync --help`, `uv run goe logmgr --help`, `uv run goe listener --help` execute cleanly; unit tests pass with `CliRunner`.
