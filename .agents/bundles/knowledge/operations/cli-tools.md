---
type: Reference
title: CLI Utilities Reference
description: Command-line reference for offload, connect, validate, sync, report, logmgr, and listener tools
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
- `--offload-predicate <sql>`: DSL predicate parsed into `PredicateExpr` (`src/goe/offload/predicates/`) for predicate-based offload.
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
Cross-database data consistency and aggregation validator powered by `CrossDbValidationBuilder` and `CrossDbValidator` (`src/goe/offload/validation/`).

### Options
- `-d, --schema <owner>` / `-t, --table <table>`: Schema and table to validate.
- `-a, --agg-fns <csv>`: Comma-separated aggregate functions (`COUNT`, `MIN`, `MAX`, `SUM`, `AVG`, `STDDEV`), packed up to 64 aggregates per query.
- `--scn <scn>`: Flashback SCN (`AS OF SCN :scn`) on Oracle source.
- `-f, --filters <where>`: Custom filter predicate validated via `CrossDbValidationBuilder.parse_filter_tuples` / `DialectSqlEngine.transpile_safe_filter`.
- `--diff`: Stream primary-key and column projections from source and target into an in-memory DuckDB 2.0 relation and run bidirectional `EXCEPT` to isolate row-level discrepancies (`CrossDbValidator.run_row_diff`).

## 4. `goe sync` & `goe report`
- `goe sync` (`src/goe/cli/commands/sync.py` -> `SchemaSyncService` in `src/goe/sync/differ.py`):
  - `--include <pattern>`: CSV list of schemas or `schema.table` patterns (default `*.*`).
  - `-x, --execute`: Apply generated `ALTER TABLE` evolution DDL to the target warehouse rather than previewing.
  - `--command-file <path>`: Write generated evolution DDL statements cleanly to a file.
  - Listener endpoint: `GET /api/system/schemas/{schema_name}/{table_name}/drift/` (`mcp_tool="preview_schema_drift"`).
- `goe report` (`src/goe/cli/commands/report.py` -> `StatusReportService` in `src/goe/report/service.py`):
  - Collects source and target partition metrics concurrently (`run_bounded(max_workers=2)`), aggregates table and schema totals via DuckDB 2.0 `GROUP BY ROLLUP`, and renders `HTML`, `TEXT`, `JSON`, `RAW`, or `CSV` at `summary` or `detail` level.
  - `-d, --demo`: Loads the compressed `src/goe/report/fixtures/demo_report.json.gz` fixture into `StatusReportEnvelope` / `OffloadStatusReport`.
  - Listener endpoint: `GET /api/system/schemas/{schema_name}/{table_name}/status/` (`mcp_tool="get_table_offload_status"`).

## 5. `goe logmgr`
Log rotation and retention utility designed for scheduled execution.
- Scans `$OFFLOAD_HOME/log` for log files older than `LOG_MV_MINS` (default 60m).
- Archives into `$OFFLOAD_HOME/log/archive/YYYY.MM.DD/`.

## 6. `goe listener`
ASGI server and worker runner for the GOE Listener REST and MCP service.
- Runs the Litestar application (`goe.listener.app:create_app`) via the `litestar-granian` Rust ASGI runtime (`uvloop`) and manages background queue workers.
