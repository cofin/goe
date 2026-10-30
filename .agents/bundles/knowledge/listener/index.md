---
type: Reference
title: GOE Listener REST & MCP Service
description: Asynchronous REST and MCP 2026-07-28 service powered by Litestar, Vertebra ASGI runtime, litestar-mcp 0.16.0, Oracle durable job queue, OpenTelemetry instrumentation, and bounded LRU + singleflight caching
tags:
  - reference
  - listener
  - api
  - mcp
  - litestar
  - vertebra
  - opentelemetry
  - index
updated_at: "2026-10-29T21:55:00Z"
---

# GOE Listener REST & MCP Service

This section documents the architecture, REST and MCP `2026-07-28` endpoints, Oracle-backed durable `sqlspec` job queue, Vertebra ASGI runtime gate, OpenTelemetry instrumentation, and bounded LRU + singleflight caching mechanics of the **GOE Listener** service (`src/goe/listener/`).

## Chapters

- [REST API & MCP Architecture](rest-api.md) - Litestar application factory, Vertebra ASGI runtime (`vertebra run goe.listener.asgi:app` and `verify_vertebra_runtime_gate`), `litestar-security` authentication across REST and `POST /mcp`, native `litestar-mcp 0.16.0` (`MCPConfig`, `MCPTaskConfig`, `MCPSkillsConfig`), `ConfirmationGate` MRTR + HMAC-SHA256 confirmation gating (`src/goe/listener/mcp.py`), `OpenTelemetryPlugin` / observational MCP span hooks (`src/goe/listener/telemetry.py`), and the full controller catalog (`SystemController`, `SchemasController`, `TablesController`, `OrchestrationController`, `GOEResourcesController`, `GOEPromptController`).
- [Workers & Embedded Caching](worker-and-redis.md) - Oracle-backed durable `sqlspec` job queue (`OracleJobStore` with `FOR UPDATE SKIP LOCKED` on `GOE_LISTENER_JOBS` and cooperative `CANCEL_REQUESTED` cancellation in `src/goe/listener/jobs/`), `DurableJobWorker` (`goe listener start --worker-only`) with `_CooperativeCancelSink`, cluster node heartbeats (`GOE_LISTENER_ENDPOINTS`), and bounded LRU + singleflight `ListenerCache` + `ListenerCacheSink` (`src/goe/listener/cache.py`).
