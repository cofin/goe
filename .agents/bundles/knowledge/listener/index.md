---
type: Reference
title: GOE Listener REST Service
description: Asynchronous REST and MCP service powered by Litestar, Vertebra ASGI runtime, durable SQLSpec job queue, OpenTelemetry instrumentation, and bounded LRU + singleflight caching
tags:
  - reference
  - listener
  - api
  - litestar
  - vertebra
  - opentelemetry
  - index
updated_at: "2026-10-28T21:19:00Z"
---

# GOE Listener REST Service

This section documents the architecture, endpoints, durable `sqlspec` job queue, Vertebra ASGI runtime gate, OpenTelemetry instrumentation, and bounded LRU + singleflight caching mechanics of the **GOE Listener** service (`src/goe/listener/`).

## Chapters

- [REST API Architecture](rest-api.md) - Litestar application factory, Vertebra ASGI runtime (`vertebra run goe.listener.asgi:app` and `verify_vertebra_runtime_gate`), `litestar-security` authentication across REST and `/mcp`, `ConfirmationGate` + diagnostic MCP tools (`src/goe/listener/mcp.py`), `OpenTelemetryPlugin` / MCP telemetry (`src/goe/listener/telemetry.py`), and endpoint catalog (`SystemController`, `SchemasController`, `TablesController`, `OrchestrationController`).
- [Workers & Embedded Caching](worker-and-redis.md) - Durable `sqlspec` job queue (`OracleJobStore` with `FOR UPDATE SKIP LOCKED` and `SqliteJobStore` WAL fallback in `src/goe/listener/jobs/`), `DurableJobWorker` (`goe listener start --worker-only`), cluster node heartbeats (`OFFLOAD_NODE_HEARTBEAT`), and bounded LRU + singleflight `ListenerCache` + `ListenerCacheSink` (`src/goe/listener/cache.py`).
