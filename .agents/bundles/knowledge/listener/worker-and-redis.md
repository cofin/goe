---
type: Reference
title: Listener Workers & Embedded Caching
description: Embedded in-process TTL caching, cluster node heartbeats, litestar-queues background tasks, and real-time event buffering
tags:
  - reference
  - listener
  - cache
  - workers
  - queues
---

# Listener Workers & Embedded Caching

The Listener uses an embedded thread-safe in-process TTL cache (`MemoryCache` and `MemorySyncCache` in [`src/goe/listener/utils/cache.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/utils/cache.py)) and `litestar-queues` (`QueuePlugin` in [`src/goe/listener/app.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/app.py) and [`src/goe/listener/jobs.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/jobs.py)) for background task execution, metadata caching, heartbeat registration, and event buffering without requiring external Redis or Valkey infrastructure.

## Embedded Cache Architecture (`src/goe/listener/utils/cache.py`)

- **Async & Sync Facades**: `MemoryCache` provides an async API for Litestar controllers and periodic tasks, while `MemorySyncCache` provides a synchronous API over the same thread-safe `RLock`-protected backing store for core orchestration modules (`goe.py`, `offload_messages.py`, `connect.py`).
- **TTL & Glob Matching**: Supports monotonic TTL expiration (`set`, `expire`), glob key scanning (`keys`, `scan`, `delete_keys`), multi-key retrieval (`mget`), and list operations (`rpush`, `lrange`).
- **Deprecation Shims**: Accessing `goe.listener.utils.cache.RedisClient` or importing `goe.util.redis_tools` emits a `DeprecationWarning` (scheduled for removal in GOE 2.0.0) and delegates to `MemoryCache` / `MemorySyncCache`.

## Heartbeat & Metadata Publishers (`src/goe/listener/services/periodic_tasks.py`)

- `publish_heartbeat`: Publishes listener endpoint metadata every `OFFLOAD_LISTENER_HEARTBEAT_INTERVAL` seconds to key `goe:listener:endpoints:{group_id}:{endpoint_id}` with URL `http(s)://{ip}:{port}`.
- `publish_schemas`: Queries offloadable schemas and per-schema tables with bounded concurrency (`anyio.Semaphore(4)`) and caches serialized `msgspec` payloads under `goe:listener:metadata:{group_id}:schemas`.
- `publish_command_executions`: Queries command executions and steps and caches serialized `msgspec` payloads under `goe:listener:metadata:{group_id}:command-executions`.

## Background Tasks & Queues (`src/goe/listener/jobs.py`)

- **Queue Plugin**: Configured via `QueuePlugin(QueueConfig(queue_backend="memory", worker=WorkerConfig(placement="asgi")))` and auto-discovered via `AutowirePlugin(AutowireConfig(domain_packages=["goe.listener"], integrations=["queues"]))`.
- **Registered `@task` Jobs**:
  - `system_heartbeat_job` (`interval=30`): Invokes `periodic_tasks.publish_heartbeat()`.
  - `sync_schemas_job` (`cron="*/5 * * * *"`): Invokes `periodic_tasks.publish_schemas()`.
  - `sync_command_executions_job` (`interval=60`): Invokes `periodic_tasks.publish_command_executions()`.
  - `run_offload_job`: Executes asynchronous offload commands scheduled via `POST /api/orchestration/offload/` inside a worker thread (`anyio.to_thread.run_sync`).

## Real-Time Event Buffering

- During offload execution, log events from `OffloadMessages` are serialized via `msgspec` and appended (`rpush`) to `MemorySyncCache` key `goe:run:<execution_id>` with a 48-hour TTL.
