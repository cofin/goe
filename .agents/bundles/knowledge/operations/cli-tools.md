---
type: Reference
title: CLI Utilities Reference
description: Command-line reference for offload, connect, logmgr, agg_validate, and listener tools
tags:
  - reference
  - operations
  - cli
  - tools
---

# CLI Utilities Reference

The GOE framework provides a unified `rich-click` CLI registered as `goe` (`src/goe/cli/main.py`):

## 1. `goe offload`
Primary CLI for executing data offloading operations.

### Common Options
- `-t, --table <owner.table>`: Fully qualified table name to offload.
- `-x, --execute`: Executes the offload (dry-run without this flag).
- `--target <bigquery|snowflake|synapse|impala|hive>`: Target backend platform.
- `--older-than-days <days>`: Offload partitions older than N days.
- `--older-than-date <YYYY-MM-DD>`: Offload partitions older than specific date.
- `--less-than-value <val>`: Offload range partitions below specific integer boundary.
- `--partition-names <p1,p2>`: Explicit comma-separated partition list.
- `--offload-predicate <sql>`: Lark-parsed WHERE predicate for PBO offload.
- `--reset-backend-table`: Drop and recreate target table and cached metadata.
- `--preserve-load-table`: Keep intermediate staging files and tables for inspection.
- `--no-ansi`: Disable terminal ANSI colors.

## 2. `goe connect`
Pre-flight environment and connectivity validation suite powered by `ConnectRunner` (`src/goe/connect/runner.py`) and `ConnectivityReport` (`src/goe/connect/models.py`).

### Modes & Flags
- `goe connect`: Runs concurrent pre-flight checks (`run_bounded`) across OS (`/etc/os-release` `PRETTY_NAME`), SSH transport hosts, frontend database, backend cloud platform, and Spark loopback networking.
- `goe connect --json`: Emits structured `ConnectivityReport` JSON via `goe.serializers`.
- Listener endpoint: `GET /api/system/connectivity/` (and MCP tool `check_connectivity`) delegates to `ConnectRunner`.

### Exit Codes
- `0`: Success (all checks passed).
- `1`: Fatal error.
- `2`: Verification failure.
- `3`: Non-fatal warning.

## 3. `goe validate`
Cross-database data consistency and aggregation validator.

### Options
- `-t, --table <owner.table>`: Table to validate.
- `--verify-row-count <minus|aggregate>`: Row count comparison or deep multi-column aggregation.
- `--as-of-scn <scn>`: Flashback SCN on Oracle source.
- `-F, --filter-clause <where>`: Custom filter predicate.

## 4. `goe sync` & `goe report`
- `goe sync`: Detects upstream RDBMS column/type changes and synchronizes target cloud DW schemas.
- `goe report`: Generates HTML/console status reports summarizing offloaded tables and hybrid views.

## 5. `goe logmgr`
Log rotation and retention utility designed for scheduled execution.
- Scans `$OFFLOAD_HOME/log` for log files older than `LOG_MV_MINS` (default 60m).
- Archives into `$OFFLOAD_HOME/log/archive/YYYY.MM.DD/`.

## 6. `goe listener`
ASGI server and worker runner for the GOE Listener REST and MCP service.
- Runs the Litestar application (`goe.listener.app:create_app`) via the `litestar-granian` Rust ASGI runtime (`uvloop`) and manages background queue workers.
