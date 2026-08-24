---
type: Reference
title: Listener REST API Architecture
description: FastAPI application factory, middleware, authentication, error mapping, and endpoint catalog
tags:
  - reference
  - listener
  - api
  - endpoints
  - security
---

# Listener REST API Architecture

The GOE Listener (`src/goe/listener/`) exposes metadata, execution status, and asynchronous job dispatching via a high-performance REST API.

## Application Architecture

- **Framework**: FastAPI with `ORJSONResponse` default response class.
- **Master Arbiter**: Gunicorn with custom `UvicornWorker` (`uvloop` event loop, `httptools` parser).
- **Middleware**:
  - `CompressionMiddleware`: Streaming Brotli (`br`) and gzip compression.
  - `SecurityHeaderMiddleware`: Injects HSTS headers.
  - `CORSMiddleware`: Restricts `/api/*` endpoints.

## Authentication & Security

- **API Key Header**: `x-goe-console-key`.
- **Validation**: Compares incoming token against `OFFLOAD_LISTENER_SHARED_TOKEN` (decryptable via `PASSWORD_KEY_FILE`).
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
