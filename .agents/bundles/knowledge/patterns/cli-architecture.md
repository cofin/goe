---
type: Reference
title: Centralized Rich-Click CLI & Legacy Delegators
description: Unified rich-click goe CLI architecture in src/goe/cli/ and backward-compatible bin/ wrapper delegators
tags:
  - pattern
  - cli
  - rich-click
  - entrypoints
updated_at: "2026-10-02T19:33:00Z"
---

# Centralized Rich-Click CLI & Legacy Delegators

## Single Authoritative CLI Entrypoint (`src/goe/cli/`)

- **Package Script**: [`pyproject.toml`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/pyproject.toml) registers the unified CLI entrypoint via `[project.scripts] goe = "goe.cli.main:cli"`.
- **Styling & Command Groups**: [`src/goe/cli/config.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/config.py) configures `rich-click` with the Google Cloud color palette (`#4285F4`, `#34A853`, `#FBBC04`, `#EA4335`), structured command groups (`Core Orchestration Commands`, `Service & Maintenance Commands`), and logical option groups for complex commands.
- **Modular Subcommands**: Implemented under [`src/goe/cli/commands/`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/):
  - `goe offload` — Data offloading with structured option groups.
  - `goe connect` — Pre-flight connectivity and environment validation.
  - `goe validate` — Cross-database row count and aggregation verification.
  - `goe sync` — Schema drift analysis and DDL synchronization.
  - `goe report` — Offload status reporting.
  - `goe logmgr` — Log rotation and retention management.
  - `goe listener` — Litestar/Granian ASGI listener server and worker lifecycle management.

## Legacy `bin/` Wrapper Delegators

Legacy scripts in [`bin/`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/bin/) (`bin/offload`, `bin/connect`, `bin/agg_validate`, `bin/schema_sync`, `bin/logmgr`, `bin/listener`, `bin/offload_status_report`) are maintained strictly as lightweight in-process Python delegators that emit `DeprecationWarning` notices and invoke the corresponding `goe <subcommand>` entrypoint.
