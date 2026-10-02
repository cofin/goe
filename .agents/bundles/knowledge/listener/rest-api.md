---
type: Reference
title: Listener REST API Architecture
description: Litestar application factory, Granian ASGI runtime, authentication guards, MCP tools, and endpoint catalog
tags:
  - reference
  - listener
  - api
  - litestar
  - security
updated_at: "2026-10-02T19:33:00Z"
---

# Listener REST API Architecture

The GOE Listener (`src/goe/listener/`) exposes metadata, execution status, MCP tools, and asynchronous job dispatching via a Litestar REST API.

## Application Architecture

- **Framework**: Litestar (`>=2.8.0`) in [`src/goe/listener/app.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/app.py) with `msgspec.Struct` request/response schemas (`src/goe/listener/schemas/`).
- **ASGI Runtime**: `litestar-granian` (`GranianPlugin`, [`src/goe/listener/asgi.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/asgi.py), and [`src/goe/cli/commands/listener.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/cli/commands/listener.py)) running on `uvloop`.
- **Plugins & Middleware**:
  - `CompressionConfig`: Gzip/Brotli response compression.
  - `CORSConfig`: Cross-origin policies across `/api/*` endpoints.
  - `AutowirePlugin` (`litestar-autowire`): Declarative dependency injection for `SystemService` and repository clients.
  - `LitestarMCP` (`litestar-mcp`): Exposes GOE orchestration operations as MCP tools and resources (`src/goe/listener/mcp.py`).

## Authentication & Security

- **API Key Header**: `x-goe-console-key` validated via `console_key_guard` (`src/goe/listener/security.py`).
- **Validation**: Constant-time comparison (`secrets.compare_digest`) against `OFFLOAD_LISTENER_SHARED_TOKEN`.
- **Authorization**: Invalid or missing keys return `HTTP 401 Unauthorized`.

## Endpoint Catalog

### System Endpoints (`/api/system/`)
- `GET /api/system/status/`: Liveness health check (`{"status": "OK"}`).
- `GET /api/system/config/`: Returns system configuration, deterministic endpoint UUIDs, active listener cluster nodes, and full JSON Schema for offload options.
- `GET /api/system/schemas/`: Lists offloadable schemas, table counts, hybrid views, and sizes.
- `GET /api/system/schemas/{schema_name}/{table_name}/columns/`: Detailed column metadata, datatypes, precision, scale, and partition positions.
- `GET /api/system/schemas/{schema_name}/{table_name}/partitions/`: Partition high-water marks, row counts, and subpartitions.

### Orchestration Endpoints (`/api/orchestration/`)
- `GET /api/orchestration/executions/?include_steps=bool`: Historical command executions from repository.
- `GET /api/orchestration/executions/{execution_id}/`: Specific execution metadata.
- `GET /api/orchestration/executions/{execution_id}/execution-log/`: Reads active/archived execution log files from disk or GCS.
- `POST /api/orchestration/offload/`: Validates parameters, checks table locks, generates `ExecutionId`, and dispatches offload asynchronously into background detached worker thread (`run_and_detach`). Returns `{"execution_id": "<uuid>"}` immediately.
