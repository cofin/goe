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

The GOE framework provides a suite of CLI tools in `bin/`:

## 1. `bin/offload`
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

## 2. `bin/connect`
Pre-flight environment and connectivity validation suite.

### Modes & Flags
- `bin/connect`: Runs complete pre-flight check across OS, configuration permissions (`640`), frontend database, backend cloud platform, and Spark loopback networking.
- `bin/connect --upgrade-environment-file`: Inspects `offload.env` against reference template and appends missing variables.

### Exit Codes
- `0`: Success (all checks passed).
- `1`: Fatal error.
- `2`: Verification failure.
- `3`: Non-fatal warning.

## 3. `bin/agg_validate`
Cross-database data consistency and aggregation validator.

### Options
- `-t, --table <owner.table>`: Table to validate.
- `--verify-row-count <minus|aggregate>`: Row count comparison or deep multi-column aggregation.
- `--as-of-scn <scn>`: Flashback SCN on Oracle source.
- `-F, --filter-clause <where>`: Custom filter predicate.

## 4. `bin/logmgr`
Log rotation and archiving shell script designed for cron execution.
- Scans `$OFFLOAD_HOME/log` for log files older than `LOG_MV_MINS` (default 60m).
- Archives into `$OFFLOAD_HOME/log/archive/YYYY.MM.DD/`.

## 5. `bin/listener`
Multi-process supervisor for the GOE Listener REST service.
- Spawns heartbeat publisher, background task workers, and Gunicorn/Uvicorn HTTP servers.
