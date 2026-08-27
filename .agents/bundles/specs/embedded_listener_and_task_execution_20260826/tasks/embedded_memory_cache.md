---
type: Task
id: embedded_listener_and_task_execution_20260826:embedded_memory_cache
title: Implement Thread-Safe Embedded In-Memory TTL Cache
description: Implement MemoryCache with TTL expiration, pattern matching (keys, scan), ping, get, set, delete, mget in src/goe/listener/utils/cache.py, and update periodic_tasks.py and heartbeat.py.
state: open
created_at: "2026-08-26T21:20:00Z"
updated_at: "2026-08-26T21:23:00Z"
tags:
  - cache
  - in-memory
  - ttl
  - listener
depends_on:
  - embedded_listener_and_task_execution_20260826:pyproject_dependency_reduction
files:
  - src/goe/listener/utils/cache.py
  - src/goe/listener/services/periodic_tasks.py
  - src/goe/listener/services/heartbeat.py
tests:
  - tests/unit/listener/test_cache.py
  - tests/unit/listener/test_system_controllers.py
verification_strategy: behavior_tdd
---

# Task: Implement Thread-Safe Embedded In-Memory TTL Cache

## Objective
Replace the Valkey/Redis network client in `src/goe/listener/utils/cache.py` with an embedded, thread-safe asynchronous `MemoryCache` supporting key-value storage with TTL expiration, wildcard pattern matching (`keys`, `scan`, `delete_keys`), and compatibility methods. Update `src/goe/listener/services/periodic_tasks.py` and `src/goe/listener/services/heartbeat.py`.

## Implementation Details

### 1. `src/goe/listener/utils/cache.py`
Implement `MemoryCache` with an internal dictionary storing `(value, epoch_expiration)` tuples, protected by `threading.RLock()` for thread safety:
```python
# Standard Library
import fnmatch
import logging
import time
from datetime import timedelta
from threading import RLock
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryCache:
    """Thread-safe in-memory key-value cache with TTL expiration.

    Provides an embedded caching layer matching Redis interface conventions
    without requiring an external broker daemon.
    """

    _instance: Optional["MemoryCache"] = None
    _lock: RLock = RLock()

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}

    def __new__(cls) -> "MemoryCache":
        """Singleton instance loader."""
        if cls._instance is not None:
            return cls._instance
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._store = {}
        return cls._instance

    def _is_expired(self, expiry: float | None) -> bool:
        if expiry is None:
            return False
        return time.time() > expiry

    def _prune_expired(self) -> None:
        now = time.time()
        expired_keys = [k for k, (_, exp) in self._store.items() if exp is not None and now > exp]
        for k in expired_keys:
            self._store.pop(k, None)

    async def ping(self) -> bool:
        """Ping memory cache."""
        return True

    async def get(self, key: str) -> Any | None:
        """Get value by key if not expired."""
        with self._lock:
            if key not in self._store:
                return None
            val, exp = self._store[key]
            if self._is_expired(exp):
                del self._store[key]
                return None
            return val

    async def set(self, key: str, value: Any, ttl: int | timedelta | None = None) -> bool:
        """Set key to hold value with optional TTL in seconds or timedelta."""
        expiry: float | None = None
        if isinstance(ttl, timedelta):
            expiry = time.time() + ttl.total_seconds()
        elif isinstance(ttl, (int, float)):
            expiry = time.time() + float(ttl)

        with self._lock:
            self._store[key] = (value, expiry)
        return True

    async def mget(self, keys: list[str]) -> list[Any | None]:
        """Get values of multiple keys."""
        with self._lock:
            results: list[Any | None] = []
            for k in keys:
                if k in self._store:
                    val, exp = self._store[k]
                    if self._is_expired(exp):
                        del self._store[k]
                        results.append(None)
                    else:
                        results.append(val)
                else:
                    results.append(None)
            return results

    async def delete(self, *keys: str) -> int:
        """Delete keys from cache."""
        count = 0
        with self._lock:
            for k in keys:
                if self._store.pop(k, None) is not None:
                    count += 1
        return count

    async def delete_keys(self, pattern: str) -> int:
        """Delete all keys matching glob pattern."""
        with self._lock:
            matching = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            for k in matching:
                del self._store[k]
            return len(matching)

    async def keys(self, pattern: str = "*") -> list[str]:
        """Return non-expired keys matching glob pattern."""
        with self._lock:
            self._prune_expired()
            return [k for k in self._store if fnmatch.fnmatch(k, pattern)]

    async def scan(self, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]:
        """Scan keyspace matching pattern (returns cursor 0 and list of matched keys)."""
        matched = await self.keys(match or "*")
        if count is not None and count > 0:
            matched = matched[:count]
        return 0, matched

    async def exists(self, key: str) -> bool:
        """Check if non-expired key exists in cache."""
        val = await self.get(key)
        return val is not None

    async def expire(self, key: str, ttl: int | timedelta) -> bool:
        """Set expiration on an existing key."""
        with self._lock:
            if key not in self._store:
                return False
            val, exp = self._store[key]
            if self._is_expired(exp):
                del self._store[key]
                return False
            expiry = (
                time.time() + ttl.total_seconds()
                if isinstance(ttl, timedelta)
                else time.time() + float(ttl)
            )
            self._store[key] = (val, expiry)
            return True

    async def close_client(self) -> None:
        """Compatibility no-op."""
        pass

    def get_client(self) -> "MemoryCache":
        """Compatibility method returning self."""
        return self


cache = MemoryCache()
```

### 2. `src/goe/listener/services/heartbeat.py`
- Remove `from valkey.exceptions import ValkeyError as RedisError`.
- In `_periodically_publish`, catch generic `Exception` for resilient logging without Valkey dependencies.

### 3. `src/goe/listener/services/periodic_tasks.py`
- Verify metadata publishers (`publish_heartbeat`, `publish_schemas`, `publish_command_executions`) interact directly with `utils.cache.set()` and `utils.cache.get()`.

## Implementation Checklist
- [ ] Implement thread-safe `MemoryCache` singleton in `src/goe/listener/utils/cache.py`.
- [ ] Support `get`, `set`, `mget`, `delete`, `delete_keys`, `keys`, `scan`, `ping`, `exists`, `expire`, `close_client`.
- [ ] Export `cache = MemoryCache()` in `src/goe/listener/utils/cache.py`.
- [ ] Update `src/goe/listener/services/heartbeat.py` to remove `valkey` imports.
- [ ] Author `tests/unit/listener/test_cache.py` validating TTL expiration, pattern matching, and concurrent access.

## Verification Strategy
- **Command:**
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/listener/test_cache.py
  ```
- **Success Criteria:** `MemoryCache` passes 100% of unit tests with zero external connection requirements.
