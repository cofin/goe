---
type: Task
id: embedded_listener_and_task_execution_20260826:embedded_memory_cache
title: Implement Thread-Safe Embedded In-Memory TTL Cache
description: Implement MemoryCache with TTL expiration, pattern matching (keys, scan), ping, get, set, delete, mget, rpush, lrange in src/goe/listener/utils/cache.py, and update periodic_tasks.py and system.py.
state: closed
priority: P1
plan_revision: 2
plan_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
state_revision: 3
claimed_by: null
claimed_at: null
blocked_reason: null
unblock_condition: null
next_step: null
last_operation: 20261002T211500Z-flow-finish-00
operation_targets: []
last_verified_at: "2026-10-02T21:15:00Z"
last_verified_commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
verification_evidence: "uv run pytest tests/unit/listener/test_cache.py"
commit: 617461544b8f90c02cfd24c31f9846a7d126cc64
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-10-02T21:15:00Z"
tags:
  - refactor
  - cache
  - in-memory
  - ttl
  - listener
depends_on:
  - embedded_listener_and_task_execution_20260826:pyproject_dependency_reduction
files:
  - src/goe/listener/utils/cache.py
  - src/goe/listener/services/periodic_tasks.py
  - src/goe/listener/services/system.py
tests:
  - tests/unit/listener/test_cache.py
  - tests/unit/listener/test_system_controllers.py
verification_strategy: behavior_tdd
---

# Task: Implement Thread-Safe Embedded In-Memory TTL Cache

## Objective
Replace the Valkey/Redis network client in `src/goe/listener/utils/cache.py` with an embedded, thread-safe asynchronous `MemoryCache` supporting key-value and list storage (`rpush`, `lrange`) with TTL expiration, wildcard pattern matching (`keys`, `scan`, `delete_keys`), and compatibility methods. Update `src/goe/listener/services/periodic_tasks.py` and `src/goe/listener/services/system.py` to eliminate import-time side effects.

## Context

### 1. `src/goe/listener/utils/cache.py`
Implement `MemoryCache` and `MemorySyncCache` with an internal dictionary storing `(value, epoch_expiration)` tuples, protected by `threading.RLock()` for thread safety.

### 2. `src/goe/listener/services/periodic_tasks.py` & `system.py`
- Lazily initialize `SystemService` via `get_system_service()` to avoid import-time side effects.
- Verify metadata publishers (`publish_heartbeat`, `publish_schemas`, `publish_command_executions`) interact directly with `utils.cache.set()` and `utils.cache.get()`.

## Steps
- [x] Implement thread-safe `MemoryCache` and `MemorySyncCache` singletons in `src/goe/listener/utils/cache.py`.
- [x] Support `get`, `set`, `mget`, `delete`, `delete_keys`, `keys`, `scan`, `ping`, `exists`, `expire`, `rpush`, `lrange`, `close_client`.
- [x] Export `cache = MemoryCache()` in `src/goe/listener/utils/cache.py`.
- [x] Refactor `src/goe/listener/services/periodic_tasks.py` and `src/goe/listener/services/system.py`.
- [x] Author `tests/unit/listener/test_cache.py` validating TTL expiration, pattern matching, list operations, and concurrent access.

## Verification
```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_cache.py
```

## Acceptance Criteria
- [x] `MemoryCache` passes 100% of unit tests with zero external connection requirements.

## Notes & Discoveries
- Implemented `MemoryCache` (async) and `MemorySyncCache` (sync) sharing the same thread-safe `_store` dictionary so synchronous CLI/offload operations and async Listener routes inspect the same in-process cache.
