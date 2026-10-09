---
type: Reference
title: Listener REST API Architecture
description: Litestar application factory, Granian ASGI runtime, litestar-security authentication, MCP tools, and endpoint catalog
tags:
  - reference
  - listener
  - api
  - litestar
  - security
updated_at: "2026-10-04T18:27:30Z"
---

# Listener REST API Architecture

The GOE Listener (`src/goe/listener/`) exposes metadata, execution status, MCP tools, and asynchronous job dispatching via a Litestar REST API.

## Application Architecture

- **Framework**: Litestar (`>=2.8.0`) in [`src/goe/listener/app.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/app.py) with `msgspec.Struct` request/response schemas ([`src/goe/listener/schemas.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/schemas.py)).
- **ASGI Runtime**: `litestar-granian` (`GranianPlugin`, [`src/goe/listener/asgi.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/asgi.py), [`src/goe/listener/__main__.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/__main__.py), and [`src/goe/cli/commands/listener.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/listener.py)) running on `uvloop`.
- **Plugins & Middleware**:
  - `SecurityPlugin` (`litestar-security`): Enforces `x-goe-console-key` header authentication via `ConsoleKeySlot` and `ConsoleKeyAuthenticator` (`src/goe/listener/security.py`).
  - `QueuePlugin` (`litestar-queues`): Embedded in-memory task queue (`queue_backend="memory"`, `WorkerConfig(placement="asgi")`).
  - `AutowirePlugin` (`litestar-autowire`): Declarative discovery of controllers and `@task` handlers across `domain_packages=["goe.listener"]` with `integrations=["queues"]`.
  - `LitestarMCP` (`litestar-mcp`): Exposes GOE listener routes marked with `mcp_tool=` as MCP tools (`src/goe/listener/mcp.py`).
  - `CompressionConfig`: Gzip response compression.
  - `CORSConfig`: Cross-origin policies across `/api/*` endpoints.

## Authentication & Security

- **API Key Header**: `x-goe-console-key` extracted by `ConsoleKeySlot` and verified by `ConsoleKeyAuthenticator` (`src/goe/listener/security.py`).
- **Validation**: Constant-time comparison (`secrets.compare_digest`) against `OFFLOAD_LISTENER_SHARED_TOKEN` (`settings.shared_token`). When `OFFLOAD_LISTENER_SHARED_TOKEN` is unset, local unauthenticated access is permitted.
- **Public & Excluded Routes**: `GET /api/system/status/` declares `auth=public()`, Litestar OpenAPI routes (`/docs`, `/schema`) are public, and `/mcp` is excluded.
- **Authorization**: Invalid or missing keys when `shared_token` is configured return `HTTP 401 Unauthorized`.

## Endpoint Catalog

### System Endpoints (`/api/system/`)
- `GET /api/system/status/`: Liveness health check (`{"status": "OK"}`).
- `GET /api/system/config/`: Returns `ListenerConfig` (`endpoint_id`, `listener_group_id`, `db_unique_name`, `active_listeners`, `version`, `frontend_type`, `backend_type`, and optional `offload_options`, `present_options`, `prepare_options`; `mcp_tool="get_listener_config"`).
- `GET /api/system/schemas/`: Lists offloadable schemas, table counts, hybrid views, and sizes (`mcp_tool="get_offloadable_schemas"`).
- `GET /api/system/schemas/{schema_name}/`: Lists offloadable tables for a schema (`mcp_tool="get_offloadable_tables"`).
- `GET /api/system/schemas/{schema_name}/{table_name}/columns/`: Detailed column metadata (`ColumnDetail` with `data_precision`, `data_scale`, `is_nullable`, `partition_position`, `subpartition_position`; `mcp_tool="get_table_columns"`).
- `GET /api/system/schemas/{schema_name}/{table_name}/partitions/`: Partition high-water marks and nested subpartitions (`SubPartitionDetail` structs normalized via `.to_dict()` and grouped by `partition_name`; `mcp_tool="get_table_partitions"`).

### Orchestration Endpoints (`/api/orchestration/`)
- `GET /api/orchestration/executions/?include_steps=bool`: Historical command executions from repository (`mcp_tool="get_command_executions"`).
- `GET /api/orchestration/executions/{execution_id}/`: Specific execution metadata (`mcp_tool="get_command_execution"`).
- `GET /api/orchestration/executions/{execution_id}/execution-log/`: Reads active/archived execution log files from disk (`mcp_tool="get_command_execution_log"`).
- `POST /api/orchestration/offload/`: Validates `OffloadOptions`, normalizes parameters to canonical `EXPECTED_OFFLOAD_ARGS` keys via `data.to_params_dict()`, checks table locks, generates `ExecutionId`, and enqueues `jobs.run_offload_job` via `QueueService` (`mcp_tool="execute_offload"`). Returns `{"execution_id": "<uuid>", "status": "QUEUED"}`.

