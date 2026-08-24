---
type: Reference
title: Listener Workers & Redis Caching
description: Redis integration, cluster node heartbeats, background cron workers, and real-time event streaming
tags:
  - reference
  - listener
  - redis
  - workers
  - streaming
---

# Listener Workers & Redis Caching

The Listener uses Redis as an async task queue, distributed cache, cluster service registry, and real-time event stream.

## Redis Architecture (`src/goe/listener/utils/cache.py`)

- **Topologies**: Standalone Redis, Sentinel HA clusters (`redis_use_sentinel`), and TLS-encrypted connections (`rediss://`).
- **Connection Pool**: Asynchronous connection pool initialized on FastAPI startup and closed on shutdown.

## Heartbeat Daemon (`src/goe/listener/services/heartbeat.py`)

- Broadcasts node metadata every `OFFLOAD_LISTENER_HEARTBEAT_INTERVAL` seconds to key `goe:listener:endpoints:{group_id}:{endpoint_id}` with URL `http(s)://{ip}:{port}` and TTL of 60s.
- Enables multi-node listener cluster discovery and load balancing.

## Background Worker & Scheduled Tasks (`src/goe/listener/services/periodic_tasks.py`)

- **Queue**: `goe:listener:worker:{listener_group_id}` using `goelib_contrib.worker`.
- **Scheduled Jobs**:
  - `cron:publish-command-executions` (every 2 minutes): Syncs database command execution history into Redis (`TTL: 10000s`).
  - `cron:publish-schemas` (hourly): Scans database schemas and caches table, column, and partition metadata in Redis with parallel worker tasks (concurrency limit = 4).

## Real-Time Event Streaming

- During offload execution, log events from `OffloadMessages` are serialized via `msgspec` and appended (`RPUSH`) to Redis key `goe:run:<execution_id>` with a 48-hour TTL.
- Allows external WebSockets and UI consoles to stream live offload progress without polling log files on disk.
