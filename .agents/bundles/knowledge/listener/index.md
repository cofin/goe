---
type: Reference
title: GOE Listener REST Service
description: Asynchronous REST API, FastAPI application factory, Gunicorn/Uvicorn workers, and Redis queues
tags:
  - reference
  - listener
  - api
  - fastapi
  - index
---

# GOE Listener REST Service

This section documents the architecture, endpoints, background worker queues, and caching mechanics of the **GOE Listener** service (`src/goe/listener/`).

## Chapters

- [REST API Architecture](rest-api.md) - FastAPI core, Gunicorn/Uvicorn ASGI runner, security tokens, endpoints, and middleware.
- [Workers & Redis Caching](worker-and-redis.md) - Redis connection pool, cluster node heartbeats, background cron workers, and real-time event streaming.
