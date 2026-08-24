---
type: Spec
flow_id: rich_click_cli_overhaul_20260823
title: Unified Rich-Click CLI Suite & Interactive Terminal UX
state: planned
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
description: Consolidation of legacy optparse scripts into a unified, richly formatted Click CLI suite with subcommands, styled panels, and backward-compatible bin/ wrappers.
tags:
  - spec
  - cli
  - rich-click
  - click
  - terminal
parent_prd: modernization_overhaul_20260823
research:
  - modernization_overhaul_20260822
---

# Flow: Unified Rich-Click CLI Suite & Interactive Terminal UX

**Flow ID:** `rich_click_cli_overhaul_20260823`

## Specification

### Code Analysis Summary
- **Current CLI Structure**: Legacy `optparse` definitions in `src/goe/orchestration/cli_entry_points.py` and disjoint bash wrapper scripts in `bin/` (`bin/offload`, `bin/connect`, `bin/agg_validate`, `bin/schema_sync`, `bin/logmgr`).
- **Target Experience**: Unified `goe` CLI tool with structured subcommands (`offload`, `connect`, `validate`, `sync`, `listener`, `logmgr`), Rich terminal panels, formatted tables, and intuitive help menus.

### Requirements

#### Functional Requirements
1. Build `src/goe/cli/main.py` as the centralized root CLI entrypoint using `rich-click`.
2. Register `goe = "goe.cli.main:cli"` in `pyproject.toml` `[project.scripts]`.
3. Implement `goe offload` subcommand with grouped option sets (source options, target options, partitioning, execution flags).
4. Implement `goe connect` subcommand with Rich colored status grid for pre-flight connectivity verification.
5. Implement `goe validate` (`agg_validate`) subcommand for data and row count verification.
6. Implement `goe sync` (`schema_sync`), `goe logmgr`, and `goe listener` subcommands.
7. Maintain backward-compatible wrapper scripts in `bin/` that forward to `goe <subcommand>`.
8. Write comprehensive CLI unit tests using `pytest-click` and Click's `CliRunner`.

---

## Implementation Plan

### Phase 1: Root CLI Application & Rich Configuration
- [ ] `cli_root_and_styling`: Build `src/goe/cli/main.py`, configure `rich-click` markup, and register `[project.scripts] goe`.

### Phase 2: Core Command Migration
- [ ] `offload_command_migration`: Implement `goe offload` migrating options from `optparse` to Click option groups.
- [ ] `connect_and_validate_commands`: Implement `goe connect` and `goe validate` subcommands with rich table formatting.
- [ ] `sync_logmgr_listener_commands`: Implement `goe sync`, `goe logmgr`, and `goe listener` subcommands.

### Phase 3: Backward Compatibility & CLI Testing
- [ ] `bin_legacy_wrappers_and_testing`: Update `bin/` scripts to delegate to `goe` and add CLI unit tests with `CliRunner`.
