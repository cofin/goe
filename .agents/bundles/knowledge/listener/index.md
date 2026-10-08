---
type: Reference
title: GOE Listener REST Service
description: Asynchronous REST and MCP service powered by Litestar, Granian ASGI runtime, litestar-queues, and embedded in-process caching
tags:
  - reference
  - listener
  - api
  - litestar
  - index
---

# GOE Listener REST Service

This section documents the architecture, endpoints, background worker queues, and caching mechanics of the **GOE Listener** service (`src/goe/listener/`).

## Chapters

- [REST API Architecture](rest-api.md) - Litestar application factory, Granian ASGI runner, `litestar-security` authentication, `litestar-autowire` DI, `litestar-mcp` tools, and endpoint catalog.
- [Workers & Embedded Caching](worker-and-redis.md) - `litestar-queues` embedded ASGI background tasks, cluster node heartbeats, scheduled cron workers, and in-process `MemoryCache`.
