# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Bounded singleflight cache and execution-event invalidation sink for GOE Listener."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from goe.typing import FrozenBaseStruct

__all__ = (
    "CacheEntry",
    "ListenerCache",
    "ListenerCacheSink",
    "get_listener_cache",
)


class CacheEntry(FrozenBaseStruct, frozen=True):
    """Immutable cache value wrapper with monotonic expiration timestamp."""

    value: Any
    expires_at: float


class ListenerCache:
    """Bounded LRU cache with monotonic TTL and async singleflight loading."""

    def __init__(self, max_entries: int = 2048, default_ttl_seconds: float = 60.0) -> None:
        self._max_entries = max(1, max_entries)
        self._default_ttl_seconds = default_ttl_seconds
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        """Return cached value for key if present and unexpired, else None."""
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now >= entry.expires_at:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return entry.value

    async def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """Store value at key with TTL and enforce LRU capacity bound."""
        ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        expires_at = time.monotonic() + max(0.0, ttl)
        async with self._lock:
            self._entries[key] = CacheEntry(value=value, expires_at=expires_at)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        ttl_seconds: float | None = None,
    ) -> Any:
        """Return cached value or coalesce concurrent misses into one loader call."""
        cached = await self.get(key)
        if cached is not None:
            return cached

        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and time.monotonic() < entry.expires_at:
                self._entries.move_to_end(key)
                return entry.value
            existing_future = self._inflight.get(key)
            if existing_future is None:
                loop = asyncio.get_running_loop()
                future: asyncio.Future[Any] = loop.create_future()
                self._inflight[key] = future
                is_leader = True
            else:
                future = existing_future
                is_leader = False

        if not is_leader:
            return await asyncio.shield(future)

        try:
            loaded = await loader()
            await self.set(key, loaded, ttl_seconds=ttl_seconds)
            future.set_result(loaded)
            return loaded
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            async with self._lock:
                self._inflight.pop(key, None)

    async def invalidate_prefix(self, prefix: str) -> int:
        """Evict all keys starting with prefix and return the number of evicted entries."""
        async with self._lock:
            matching = [k for k in self._entries if k.startswith(prefix)]
            for key in matching:
                self._entries.pop(key, None)
            return len(matching)

    def invalidate_prefix_sync(self, prefix: str) -> int:
        """Synchronously evict all keys starting with prefix from worker threads."""
        matching = [k for k in list(self._entries.keys()) if k.startswith(prefix)]
        for key in matching:
            self._entries.pop(key, None)
        return len(matching)

    async def clear(self) -> None:
        """Clear all entries from the cache."""
        async with self._lock:
            self._entries.clear()


class ListenerCacheSink:
    """Execution event sink that invalidates ListenerCache entries on step completion."""

    def __init__(self, cache: ListenerCache, owner_table: str | None = None) -> None:
        self._cache = cache
        self._owner_table = owner_table.upper() if owner_table else None

    def emit(self, event: Any) -> None:
        """Invalidate execution and table metadata cache entries when steps finish."""
        event_kind = getattr(event, "kind", None) or type(event).__name__
        if event_kind in ("step_finished", "command_finished", "StepFinishedEvent", "CommandFinishedEvent"):
            self._cache.invalidate_prefix_sync("executions:")
            if self._owner_table and "." in self._owner_table:
                owner, table = self._owner_table.split(".", 1)
                self._cache.invalidate_prefix_sync(f"schemas:{owner}")
                self._cache.invalidate_prefix_sync(f"tables:{owner}:{table}")
            else:
                self._cache.invalidate_prefix_sync("schemas:")
                self._cache.invalidate_prefix_sync("tables:")

    def close(self) -> None:
        """No-op close hook satisfying ExecutionSink protocol."""


_default_cache: ListenerCache | None = None


def get_listener_cache() -> ListenerCache:
    """Return the default process-scoped ListenerCache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = ListenerCache()
    return _default_cache
