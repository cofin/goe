---
type: Reference
title: Listener Workers & Redis Caching
description: Valkey/Redis caching, cluster node heartbeats, litestar-queues background tasks, and real-time event streaming
tags:
  - reference
  - listener
  - redis
  - workers
  - queues
---

# Listener Workers & Redis Caching

The Listener uses Valkey/Redis (`src/goe/listener/utils/cache.py`) and `litestar-queues` (`QueuePlugin` in `src/goe/listener/app.py` and `src/goe/listener/jobs.py`) for background task execution, metadata caching, cluster node registration, and event streaming.

## Cache Architecture (`src/goe/listener/utils/cache.py`)

- **Topologies**: Standalone Valkey/Redis, Sentinel HA clusters (`redis_use_sentinel`), and TLS-encrypted connections (`rediss://`).
- **Lifecycle**: Asynchronous client managed across the Litestar application lifespan.

## Heartbeat & Metadata Publishers (`src/goe/listener/services/heartbeat.py` & `periodic_tasks.py`)

- Broadcasts node metadata every `OFFLOAD_LISTENER_HEARTBEAT_INTERVAL` seconds to key `goe:listener:endpoints:{group_id}:{endpoint_id}` with URL `http(s)://{ip}:{port}` and TTL of 60s.
- Enables multi-node listener cluster discovery and load balancing.

## Background Tasks & Queues (`src/goe/listener/jobs.py` & `worker.py`)

- **Queue Plugin**: Configured via `QueuePlugin` (`litestar-queues`) in `src/goe/listener/app.py`.
- **Registered Jobs**:
  - `publish-command-executions`: Syncs database command execution history into cache (`TTL: 10000s`).
  - `publish-schemas`: Scans database schemas and caches table, column, and partition metadata with bounded concurrency (`CapacityLimiter`).
  - `run_offload_job`: Executes asynchronous offload commands scheduled via `POST /api/orchestration/offload/`.

## Real-Time Event Streaming

- During offload execution, log events from `OffloadMessages` are serialized via `msgspec` and appended (`RPUSH`) to Redis key `goe:run:<execution_id>` with a 48-hour TTL.
- Allows external WebSockets and UI consoles to stream live offload progress without polling log files on disk.
