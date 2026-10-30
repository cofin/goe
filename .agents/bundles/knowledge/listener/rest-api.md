---
type: Reference
title: Listener REST API & MCP Architecture
description: Litestar application factory, Vertebra ASGI runtime, litestar-security authentication, native litestar-mcp 0.16.0 tools/resources/prompts/skills, ConfirmationGate MRTR + HMAC gating, OpenTelemetry instrumentation, and endpoint catalog
tags:
  - reference
  - listener
  - api
  - mcp
  - litestar
  - vertebra
  - security
  - opentelemetry
updated_at: "2026-10-29T21:55:00Z"
---

# Listener REST API & MCP Architecture

The GOE Listener (`src/goe/listener/`) exposes database catalog discovery, dry-run offload planning, schema drift reconciliation, cross-database validation, durable job execution, and native Model Context Protocol (`2026-07-28`) capabilities via a Litestar application running on the Vertebra Rust/PyO3 HTTP runtime.

## Application Architecture

- **Framework**: Litestar (`>=2.8.0`) in `src/goe/listener/app.py` with `FrozenBaseStruct` request/response schemas (`src/goe/listener/schemas.py`), auto-discovered controllers (`AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"]))`), and domain services (`SystemService` in `src/goe/listener/services/system.py` and `ListenerOperationsService` in `src/goe/listener/services/operations.py`).
- **ASGI Runtime**: Vertebra (`src/goe/listener/asgi.py`, `src/goe/listener/vertebra_gate.py`, and `src/goe/cli/commands/listener.py`), validated before launch by `verify_vertebra_runtime_gate()` (asserting lifespan failure propagation and slow-upload streaming concurrency) and invoked via `build_vertebra_command()` (`vertebra run goe.listener.asgi:app --interface asgi --topology shm --workers <N> --threads 1 --drain-timeout 30`). `vertebra.extensions.litestar.LitestarPlugin` is registered when available.
- **Plugins & Middleware**:
  - `SecurityPlugin` (`litestar-security`): Enforces `x-goe-console-key` header authentication via `ConsoleKeySlot` and `ConsoleKeyAuthenticator` (`src/goe/listener/security.py`) across both REST `/api/*` and `POST /mcp`.
  - `LitestarMCP` (`litestar-mcp==0.16.0`): Configures stateless Streamable HTTP (`POST /mcp` for MCP `2026-07-28`) via `build_mcp_config()` (`src/goe/listener/mcp.py`) with `MCPTaskConfig()` (`io.modelcontextprotocol/tasks`), `MCPSkillsConfig` (`skill://goe-*/SKILL.md` from `src/goe/listener/skills/`), and purely observational `before_tool_call` / `after_tool_call` OpenTelemetry hooks (`src/goe/listener/telemetry.py`).
  - `OpenTelemetryPlugin` (`litestar.plugins.opentelemetry`, lazily bound in `src/goe/listener/telemetry.py`): Enabled when `GOE_OTEL_ENABLED=true` and `opentelemetry-instrumentation-asgi` is installed, propagating W3C trace context across HTTP requests, durable `DurableJobWorker` jobs (`traceparent` / `tracestate`), and MCP tool calls (`goe.mcp.tool.<name>`).
  - `CompressionConfig`: Gzip response compression.
  - `CORSConfig`: Cross-origin policies across `/api/*` endpoints.

## Authentication & Mutating Tool Safety Gate

- **API Key Header**: `x-goe-console-key` extracted by `ConsoleKeySlot` and verified by `ConsoleKeyAuthenticator` (`src/goe/listener/security.py`) using constant-time comparison (`secrets.compare_digest`) against `OFFLOAD_LISTENER_SHARED_TOKEN` (`settings.shared_token`). When `OFFLOAD_LISTENER_SHARED_TOKEN` is unset, local unauthenticated access is permitted.
- **Public & Excluded Routes**: `GET /api/system/status/` and `HEAD /api/system/status/` declare `auth=public()`, and Litestar OpenAPI routes (`/docs`, `/schema`) are public (`exclude_paths=["/schema"]`). `POST /mcp` is protected by `SecurityPlugin(required("console-key"))` via `MCPConfig(route_opt={AUTH_POLICY_OPT_KEY: required("console-key")})` and excluded from OpenAPI (`include_in_schema=False`).
- **Handler-Level MCP Confirmation Gate (`ConfirmationGate` in `src/goe/listener/mcp.py`)**:
  - Mutating handlers (`execute_offload` and `apply_schema_sync` when `execute=True`) check for an active MCP request context (`get_mcp_request_context()`). Direct HTTP REST `POST` callers have no MCP context and execute without an extra confirmation round-trip.
  - Under MCP (`POST /mcp` or `goe listener mcp stdio`), `ConfirmationGate.require_mcp_confirmation()` enforces two paths:
    1. **Two-round MRTR (`MCPInputRequiredResult`)**: When invoked without confirmation, the handler returns `MCPInputRequiredResult` (`task_input_before_start=True`) with `input_requests={"confirm": ..., "confirmation_token": ...}` and `request_state` containing a newly minted HMAC-SHA256 token bound to `(tool_name, owner_table, canonical_payload_sha256, exp_epoch)` (`settings.confirmation_ttl_seconds`, default `300s`). The client completes Round 2 by passing `inputResponses={"confirm": True}` and `requestState` (or `inputResponses={"confirmation_token": "<token>"}`).
    2. **One-round Preview Token**: Calling `preview_offload_plan` or `preview_schema_drift` (`goe://schemas/{schema_name}/{table_name}/drift`) mints a `ConfirmationChallenge` whose `confirmation_token` can be passed directly in the request body (`confirmation_token` field) or `X-GOE-Confirmation-Token` header.

## REST & MCP Endpoint Catalog

### System, Schemas & Tables Endpoints (`/api/system/`)
- `GET /api/system/status/` (`HEAD /api/system/status/`): Public liveness health check (`{"status": "OK"}`; `mcp_exclude=True`).
- `GET /api/system/connectivity/`: Runs `ConnectRunner` connectivity probes (`@mcp_tool("check_connectivity")`).
- `GET /api/system/config/`: Returns `ListenerConfig` including active listener endpoints from `job_store.list_active_heartbeats()` (`@mcp_tool("get_listener_config")`).
- `GET /api/system/reports/status/`: Collects a multi-table or single-table `StatusReportEnvelope` via `StatusReportService` with wired source/target partition fetchers (`@mcp_tool("generate_status_report", task_support="optional")`).
- `GET /api/system/schemas/`: Lists offloadable schemas (`@mcp_tool("get_offloadable_schemas")`).
- `GET /api/system/schemas/{schema_name}/`: Lists offloadable tables for a schema (`@mcp_tool("get_offloadable_tables")`).
- `GET /api/system/schemas/{schema_name}/{table_name}/columns/`: Column metadata for a table (`@mcp_tool("get_table_columns")`).
- `GET /api/system/schemas/{schema_name}/{table_name}/partitions/`: Partition high-water marks and nested subpartitions (`@mcp_tool("get_table_partitions")`).
- `GET /api/system/schemas/{schema_name}/{table_name}/status/`: Single-table `TableStatusReport` (`@mcp_tool("get_table_offload_status")`).
- `GET /api/system/schemas/{schema_name}/{table_name}/drift/`: Hydrates live frontend/backend columns via `SchemaSyncService` and returns `SchemaDiff` with `ddl_statements` and an `apply_schema_sync` `ConfirmationChallenge` (`@mcp_tool("preview_schema_drift")`).
- `GET /api/system/schemas/{schema_name}/{table_name}/metadata/`: Returns persisted `TableOffloadMetadataResponse` from `OracleRepositoryService.get_offload_metadata` or `404 TableMetadataNotFound` (`@mcp_tool("get_table_offload_metadata")`).

### Orchestration Endpoints (`/api/orchestration/`)
- `GET /api/orchestration/executions/`: Historical command executions (`@mcp_tool("get_command_executions")`).
- `GET /api/orchestration/executions/{execution_id}/`: Specific execution metadata (`@mcp_tool("get_command_execution")`).
- `GET /api/orchestration/executions/{execution_id}/execution-log/`: Reads bounded execution log tail (`settings.max_log_bytes`) with `log_resource_uri="goe://executions/{execution_id}/log"` (`@mcp_tool("get_command_execution_log")`).
- `GET /api/orchestration/executions/{execution_id}/execution-log/link/`: Returns an `MCPResourceLink` pointing to `goe://executions/{execution_id}/log` (`@mcp_tool("get_execution_log_link")`).
- `GET /api/orchestration/jobs/`: Lists durable jobs from `OracleJobStore` (`@mcp_tool("list_offload_jobs")`).
- `GET /api/orchestration/jobs/{execution_id}/`: Retrieves a single durable `JobStatusResponse` by `execution_id` (`@mcp_tool("get_offload_job")`).
- `POST /api/orchestration/offload/preview/`: Runs `OffloadPipeline.plan()` and `BoundaryResolutionStage(PredicateCompiler())` in read-only mode via `ListenerOperationsService.preview_offload` and returns `OffloadPlanPreview` with a signed `ConfirmationChallenge` (`@mcp_tool("preview_offload_plan")`).
- `POST /api/orchestration/offload/`: Enqueues a durable background offload job into `OracleJobStore` and returns `CommandScheduled` (`MCPToolResult` with `goe://jobs/{execution_id}` and `goe://executions/{execution_id}/log` `MCPResourceLink` blocks under MCP; `@mcp_tool("execute_offload", task_support="optional", task_input_before_start=True)`).
- `POST /api/orchestration/sync/`: Preview or apply target warehouse schema evolution DDL under `orchestration_lock_for_table` via `ListenerOperationsService.synchronize_schema` (`@mcp_tool("apply_schema_sync", task_support="optional", task_input_before_start=True)`).
- `POST /api/orchestration/validate/`: Executes read-only cross-database count, aggregation, or DuckDB 2.0 row-diff validation via `ListenerOperationsService.validate_table` (`@mcp_tool("validate_table", task_support="optional")`).
- `POST /api/orchestration/executions/{execution_id}/cancel/`: Requests cooperative cancellation of a `PENDING`, `CLAIMED`, or `RUNNING` job in `OracleJobStore` (`@mcp_tool("cancel_offload_job")`).

### Dedicated MCP Resources (`GOEResourcesController`), Prompts (`GOEPromptController`) & Skills
- **`GOEResourcesController` (`src/goe/listener/controllers/resources.py`, `path="/api/_mcp/resources"`, `include_in_schema=False`)**:
  - Static resources: `goe://system/status`, `goe://system/connectivity`, `goe://system/config`, `goe://reports/status`, `goe://schemas`, `goe://executions`, `goe://jobs` (plus built-in `litestar://openapi`).
  - RFC 6570 resource templates: `goe://reports/status/{schema_filter}`, `goe://schemas/{schema_name}/tables`, `goe://schemas/{schema_name}/{table_name}/columns`, `goe://schemas/{schema_name}/{table_name}/partitions`, `goe://schemas/{schema_name}/{table_name}/status`, `goe://schemas/{schema_name}/{table_name}/drift`, `goe://schemas/{schema_name}/{table_name}/metadata`, `goe://executions/{execution_id}`, `goe://executions/{execution_id}/log`, `goe://jobs/{execution_id}`.
- **`GOEPromptController` (`src/goe/listener/controllers/prompts.py`, `path="/api/prompts"`, `include_in_schema=False`)**:
  - Guided DBA workflow prompts: `plan_table_offload`, `diagnose_failed_execution`, `reconcile_schema_drift`, `audit_schema_readiness`.
- **Packaged MCP Skills (`src/goe/listener/skills/<name>/SKILL.md`)**:
  - Exposed via `skills/list`, `skills/get`, `resources/directory/read`, and `resources/read` (`skill://goe-offload-operations/SKILL.md`, `skill://goe-diagnostics-and-recovery/SKILL.md`, `skill://goe-schema-drift-and-validation/SKILL.md`).
