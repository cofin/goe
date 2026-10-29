---
type: Reference
title: Listener REST API Architecture
description: Litestar application factory, Vertebra ASGI runtime, litestar-security authentication, MCP tools with ConfirmationGate, OpenTelemetry instrumentation, and endpoint catalog
tags:
  - reference
  - listener
  - api
  - litestar
  - vertebra
  - security
  - opentelemetry
updated_at: "2026-10-28T21:19:00Z"
---

# Listener REST API Architecture

The GOE Listener (`src/goe/listener/`) exposes metadata, execution status, MCP tools, and durable job dispatching via a Litestar REST API running on the Vertebra Rust/PyO3 HTTP runtime.

## Application Architecture

- **Framework**: Litestar (`>=2.8.0`) in `src/goe/listener/app.py` with `msgspec.Struct` request/response schemas (`src/goe/listener/schemas.py`) and domain-focused controllers (`SystemController`, `SchemasController`, `TablesController`, `OrchestrationController` in `src/goe/listener/controllers/`).
- **ASGI Runtime**: Vertebra (`src/goe/listener/asgi.py`, `src/goe/listener/vertebra_gate.py`, and `src/goe/cli/commands/listener.py`), validated before launch by `verify_vertebra_runtime_gate()` (asserting lifespan failure propagation and slow-upload streaming concurrency) and invoked via `build_vertebra_command()` (`vertebra run goe.listener.asgi:app --interface asgi --topology shm --workers <N> --threads 1 --drain-timeout 30`).
- **Plugins & Middleware**:
  - `SecurityPlugin` (`litestar-security`): Enforces `x-goe-console-key` header authentication via `ConsoleKeySlot` and `ConsoleKeyAuthenticator` (`src/goe/listener/security.py`) across both REST `/api/*` and `/mcp`.
  - `LitestarMCP` (`litestar-mcp`): Exposes GOE listener routes marked with `mcp_tool=` plus 3 read-only diagnostic tools (`preview_offload_plan`, `inspect_active_jobs`, `validate_table_readiness`) and `ConfirmationGate` token enforcement for mutating `execute_offload` (`execute=True`) calls (`src/goe/listener/mcp.py`), with `before_tool_call` / `after_tool_call` span hooks (`goe.mcp.tool.<name>`).
  - `OpenTelemetryPlugin` (`litestar.plugins.opentelemetry`, lazily bound in `src/goe/listener/telemetry.py`): Enabled when `GOE_OTEL_ENABLED=true` and `opentelemetry-instrumentation-asgi` is installed, propagating W3C trace context across HTTP requests, durable `DurableJobWorker` jobs (`traceparent` / `tracestate`), and MCP tool calls.
  - `CompressionConfig`: Gzip response compression.
  - `CORSConfig`: Cross-origin policies across `/api/*` endpoints.

## Authentication & Security

- **API Key Header**: `x-goe-console-key` extracted by `ConsoleKeySlot` and verified by `ConsoleKeyAuthenticator` (`src/goe/listener/security.py`).
- **Validation**: Constant-time comparison (`secrets.compare_digest`) against `OFFLOAD_LISTENER_SHARED_TOKEN` (`settings.shared_token`). When `OFFLOAD_LISTENER_SHARED_TOKEN` is unset, local unauthenticated access is permitted.
- **Public & Excluded Routes**: `GET /api/system/status/` declares `auth=public()`, and Litestar OpenAPI routes (`/docs`, `/schema`) are public (`exclude_paths=["/schema"]`). `/mcp` is protected by `SecurityPlugin` alongside `/api/*`.
- **MCP Confirmation Gate (`ConfirmationGate` in `src/goe/listener/mcp.py`)**: Mutating MCP tool invocations (`execute_offload` with `execute=True`) require a valid HMAC-SHA256 `confirm_token` issued by a dry-run (`execute=False`) call or `preview_offload_plan` within 600 seconds.
- **Authorization**: Invalid or missing keys when `shared_token` is configured return `HTTP 401 Unauthorized`.

## Endpoint Catalog

### System, Schemas & Tables Endpoints (`/api/system/`)
- `GET /api/system/status/`: Liveness health check (`{"status": "OK"}`).
- `GET /api/system/config/`: Returns `ListenerConfig` (`endpoint_id`, `listener_group_id`, `db_unique_name`, `active_listeners`, `version`, `frontend_type`, `backend_type`, and optional `offload_options`, `present_options`, `prepare_options`; `mcp_tool="get_listener_config"`).
- `GET /api/system/schemas/`: Lists offloadable schemas, table counts, hybrid views, and sizes via `SchemasController` and bounded `ListenerCache.get_or_load` (`mcp_tool="get_offloadable_schemas"`).
- `GET /api/system/schemas/{schema_name}/`: Lists offloadable tables for a schema via `SchemasController` (`mcp_tool="get_offloadable_tables"`).
- `GET /api/system/schemas/{schema_name}/{table_name}/columns/`: Detailed column metadata via `TablesController` (`ColumnDetail` with `data_precision`, `data_scale`, `is_nullable`, `partition_position`, `subpartition_position`; `mcp_tool="get_table_columns"`).
- `GET /api/system/schemas/{schema_name}/{table_name}/partitions/`: Partition high-water marks and nested subpartitions via `TablesController` (`mcp_tool="get_table_partitions"`).

### Orchestration Endpoints (`/api/orchestration/`)
- `GET /api/orchestration/executions/?include_steps=bool`: Historical command executions from repository cached via `ListenerCache` (`mcp_tool="get_command_executions"`).
- `GET /api/orchestration/executions/{execution_id}/`: Specific execution metadata (`mcp_tool="get_command_execution"`).
- `GET /api/orchestration/executions/{execution_id}/execution-log/`: Reads active/archived execution log files from disk with canonical path traversal boundary check (`mcp_tool="get_command_execution_log"`).
- `POST /api/orchestration/offload/`: Validates `OffloadOptions`, normalizes parameters to canonical `EXPECTED_OFFLOAD_ARGS` keys via `data.to_params_dict()`, checks table locks, generates `ExecutionId`, injects W3C `traceparent` / `tracestate` when OpenTelemetry is enabled, and persists a `JobRecord` (`status="QUEUED"`) via `JobStoreProtocol.enqueue()` (`mcp_tool="execute_offload"`). Returns `{"execution_id": "<uuid>", "status": "QUEUED"}` (or `HTTP 409 Conflict` on `DuplicateActiveTableJobError` / `OrchestrationLockTimeout`).
- `POST /api/orchestration/executions/{execution_id}/cancel/`: Requests cooperative cancellation of a `QUEUED` or `RUNNING` job in `JobStoreProtocol` (`cancel_requested=True`; transitions `QUEUED` jobs directly to `CANCELLED`).
