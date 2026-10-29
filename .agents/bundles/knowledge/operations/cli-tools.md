---
type: Reference
title: CLI Utilities Reference
description: Command-line reference for offload, connect, validate, sync, report, logmgr, and listener (Vertebra ASGI, durable worker, and MCP stdio/bridge/inspect) tools
tags:
  - reference
  - operations
  - cli
  - mcp
  - tools
updated_at: "2026-10-29T21:55:00Z"
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
- Listener endpoint: `GET /api/system/connectivity/` (MCP tool `check_connectivity` and resource `goe://system/connectivity`) delegates to `ConnectRunner`.

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
- Listener endpoint: `POST /api/orchestration/validate/` (MCP tool `validate_table`).

## 4. `goe sync` & `goe report`
- `goe sync` (`src/goe/cli/commands/sync.py` -> `SchemaSyncService` in `src/goe/sync/differ.py`):
  - `--include <pattern>`: CSV list of schemas or `schema.table` patterns (default `*.*`).
  - `-x, --execute`: Apply generated `ALTER TABLE` evolution DDL to the target warehouse rather than previewing.
  - `--command-file <path>`: Write generated evolution DDL statements cleanly to a file.
  - Listener endpoints: `GET /api/system/schemas/{schema_name}/{table_name}/drift/` (MCP tool `preview_schema_drift` and resource `goe://schemas/{schema_name}/{table_name}/drift`) and `POST /api/orchestration/sync/` (MCP tool `apply_schema_sync`).
- `goe report` (`src/goe/cli/commands/report.py` -> `StatusReportService` in `src/goe/report/service.py`):
  - Collects source and target partition metrics concurrently (`run_bounded(max_workers=2)`), aggregates table and schema totals via DuckDB 2.0 `GROUP BY ROLLUP`, and renders `HTML`, `TEXT`, `JSON`, `RAW`, or `CSV` at `summary` or `detail` level.
  - `-d, --demo`: Loads the compressed `src/goe/report/fixtures/demo_report.json.gz` fixture into `StatusReportEnvelope` / `OffloadStatusReport`.
  - Listener endpoints: `GET /api/system/reports/status/` (MCP tool `generate_status_report` and resources `goe://reports/status`, `goe://reports/status/{schema_filter}`) and `GET /api/system/schemas/{schema_name}/{table_name}/status/` (MCP tool `get_table_offload_status` and resource `goe://schemas/{schema_name}/{table_name}/status`).

## 5. `goe logmgr`
Log rotation and retention utility designed for scheduled execution.
- Scans `$OFFLOAD_HOME/log` for log files older than `LOG_MV_MINS` (default 60m).
- Archives into `$OFFLOAD_HOME/log/archive/YYYY.MM.DD/`.

## 6. `goe listener`
Vertebra ASGI server, durable background job worker, and Model Context Protocol (`2026-07-28`) CLI (`src/goe/cli/commands/listener.py`).

### Server & Worker Subcommands
- `goe listener start`: Verifies the Vertebra runtime gate (`verify_vertebra_runtime_gate()`) and starts the Litestar application (`goe.listener.asgi:app`) via `vertebra run goe.listener.asgi:app --interface asgi --topology shm --workers <N> --threads 1 --drain-timeout 30`.
- `goe listener start --worker-only`: Runs `DurableJobWorker` against `OracleJobStore` (`GOE_LISTENER_JOBS`) without binding an HTTP socket.
- `goe listener status`: Probes `GET /api/system/status/` via `httpx2.Client` (normalizing `0.0.0.0`/`::` to `127.0.0.1` and forwarding `x-goe-console-key` when `OFFLOAD_LISTENER_SHARED_TOKEN` is configured), exiting `0` when healthy or `1` when unreachable/unhealthy.

### MCP Subcommands (`goe listener mcp`)
- `goe listener mcp stdio`: Runs the GOE Listener MCP server in-process over newline-delimited JSON-RPC `stdin`/`stdout` via `litestar_mcp.mcp.stdio.run_stdio` (`ASGIStreamingTransport`), redirecting root `stdout` log handlers to `sys.stderr` and forwarding `x-goe-console-key` when `shared_token` is configured (`--client-id`, `--owner-id`, `--enable-worker / --no-worker`).
- `goe listener mcp bridge`: Bridges local `stdin`/`stdout` JSON-RPC to a remote Streamable HTTP `POST <endpoint>` (`default: f"{settings.base_url}/mcp"`) via `litestar_mcp.mcp.bridge.run_stdio_streamable_http_bridge` (`--endpoint`, `--token`, `--timeout`, `--sse-read-timeout`).
- `goe listener mcp inspect`: Prints a structured JSON (`--json`) or Rich table summary of all discovered MCP tools, static resources, RFC 6570 resource templates, prompts, and packaged skills.
