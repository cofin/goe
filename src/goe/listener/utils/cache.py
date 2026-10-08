# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Embedded in-process memory cache utility."""

import fnmatch
import logging
import threading
import time
import warnings
from datetime import timedelta
from typing import Any, ClassVar


def _resolve_expiry(ttl: int | float | timedelta | None) -> float | None:
    """Resolve a TTL value in seconds or timedelta to a monotonic expiration timestamp."""
    if ttl is None:
        return None
    seconds = ttl.total_seconds() if isinstance(ttl, timedelta) else float(ttl)
    return time.monotonic() + seconds


class MemoryCache:
    """Thread-safe async in-process memory cache with TTL and pattern matching."""

    _instance: ClassVar["MemoryCache | None"] = None
    _store: ClassVar[dict[str, tuple[Any, float | None]]] = {}
    _lock: ClassVar[threading.RLock] = threading.RLock()
    logger: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __new__(cls) -> "MemoryCache":
        """Return singleton MemoryCache instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _purge_expired(cls) -> None:
        """Remove all expired entries from the backing store."""
        now = time.monotonic()
        with cls._lock:
            expired_keys = [
                k for k, (_, expires_at) in cls._store.items() if expires_at is not None and now >= expires_at
            ]
            for k in expired_keys:
                cls._store.pop(k, None)

    @classmethod
    def _get_entry(cls, key: str) -> tuple[bool, Any, float | None]:
        """Retrieve a live entry from the store, evicting it if expired."""
        with cls._lock:
            entry = cls._store.get(key)
            if entry is None:
                return False, None, None
            value, expires_at = entry
            if expires_at is not None and time.monotonic() >= expires_at:
                cls._store.pop(key, None)
                return False, None, None
            return True, value, expires_at

    @classmethod
    def get_client(cls) -> type["MemoryCache"]:
        """Return the active cache class for compatibility."""
        return cls

    @classmethod
    async def close_client(cls) -> None:
        """Close the cache client."""
        cls.logger.debug("Closing MemoryCache client.")

    @classmethod
    async def ping(cls) -> bool:
        """Verify cache availability."""
        return True

    @classmethod
    async def set(cls, key: str, value: Any, ttl: int | float | timedelta | None = None) -> bool:
        """Store a value under key with an optional TTL."""
        expires_at = _resolve_expiry(ttl)
        with cls._lock:
            cls._store[key] = (value, expires_at)
        return True

    @classmethod
    async def get(cls, key: str) -> Any | None:
        """Retrieve a value by key, returning None when missing or expired."""
        found, value, _ = cls._get_entry(key)
        return value if found else None

    @classmethod
    async def mget(cls, keys: list[str]) -> list[Any | None]:
        """Retrieve values for multiple keys in order."""
        return [await cls.get(k) for k in keys]

    @classmethod
    async def delete(cls, *keys: str) -> int:
        """Delete one or more keys and return the number of removed keys."""
        removed = 0
        with cls._lock:
            for key in keys:
                found, _, _ = cls._get_entry(key)
                if found:
                    cls._store.pop(key, None)
                    removed += 1
        return removed

    @classmethod
    async def keys(cls, pattern: str = "*") -> list[str]:
        """Return all non-expired keys matching a glob pattern."""
        cls._purge_expired()
        with cls._lock:
            return [k for k in cls._store if fnmatch.fnmatchcase(k, pattern)]

    @classmethod
    async def scan(cls, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]:
        """Scan keyspace for non-expired keys matching an optional glob pattern."""
        matching = await cls.keys(match or "*")
        if count is not None:
            matching = matching[:count]
        return 0, matching

    @classmethod
    async def delete_keys(cls, pattern: str) -> int:
        """Delete all non-expired keys matching a glob pattern."""
        matching = await cls.keys(pattern)
        if matching:
            return await cls.delete(*matching)
        return 0

    @classmethod
    async def exists(cls, key: str) -> int:
        """Return 1 if key exists and is not expired, otherwise 0."""
        found, _, _ = cls._get_entry(key)
        return 1 if found else 0

    @classmethod
    async def expire(cls, key: str, ttl: int | float | timedelta) -> bool:
        """Update the TTL on an existing non-expired key."""
        with cls._lock:
            found, value, _ = cls._get_entry(key)
            if not found:
                return False
            cls._store[key] = (value, _resolve_expiry(ttl))
            return True

    @classmethod
    async def rpush(cls, key: str, value: Any, ttl: int | float | timedelta | None = None) -> int:
        """Append one or more values to a list stored at key."""
        with cls._lock:
            found, current, existing_expiry = cls._get_entry(key)
            if not found:
                items: list[Any] = []
            elif isinstance(current, list):
                items = current
            else:
                raise TypeError("WRONGTYPE Operation against a key holding the wrong kind of value")

            if isinstance(value, list):
                items.extend(value)
            else:
                items.append(value)

            expires_at = _resolve_expiry(ttl) if ttl is not None else existing_expiry
            cls._store[key] = (items, expires_at)
            return len(items)

    @classmethod
    async def lrange(cls, key: str, start: int, end: int) -> list[Any]:
        """Return an inclusive slice of elements from a list stored at key."""
        with cls._lock:
            found, current, _ = cls._get_entry(key)
            if not found or not isinstance(current, list):
                return []
            length = len(current)
            if end == -1:
                stop: int | None = None
            elif end < 0:
                stop = max(0, length + end + 1)
            else:
                stop = end + 1
            return list(current[start:stop])

    @classmethod
    async def clear(cls) -> None:
        """Clear all keys from the in-memory store."""
        with cls._lock:
            cls._store.clear()

    def __getattr__(self, name: str) -> Any:
        """Support attribute lookups when goe.listener.utils.cache is bound to the singleton instance."""
        if name == "RedisClient":
            warnings.warn(
                "goe.listener.utils.cache.RedisClient is deprecated and will be removed in GOE 2.0.0; "
                "use MemoryCache instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return MemoryCache
        if name == "MemoryCache":
            return MemoryCache
        if name == "MemorySyncCache":
            return MemorySyncCache
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


class MemorySyncCache:
    """Thread-safe synchronous interface over MemoryCache storage."""

    logger: ClassVar[logging.Logger] = logging.getLogger(__name__)

    @classmethod
    def connect(cls, redis_connection_kwargs: dict[str, Any] | None = None) -> type["MemorySyncCache"]:
        """Return the synchronous cache interface."""
        return cls

    @classmethod
    def get_client(cls, redis_connection_kwargs: dict[str, Any] | None = None) -> type["MemorySyncCache"]:
        """Return the synchronous cache interface."""
        return cls

    @classmethod
    def close_client(cls) -> None:
        """Close the synchronous cache client."""
        cls.logger.debug("Closing MemorySyncCache client.")

    @classmethod
    def ping(cls) -> bool:
        """Verify cache availability."""
        return True

    @classmethod
    def set(cls, key: str, value: Any, ttl: int | float | timedelta | None = None) -> bool:
        """Store a value under key with an optional TTL."""
        with MemoryCache._lock:
            MemoryCache._store[key] = (value, _resolve_expiry(ttl))
        return True

    @classmethod
    def get(cls, key: str) -> Any | None:
        """Retrieve a value by key, returning None when missing or expired."""
        found, value, _ = MemoryCache._get_entry(key)
        return value if found else None

    @classmethod
    def mget(cls, keys: list[str]) -> list[Any | None]:
        """Retrieve values for multiple keys in order."""
        return [cls.get(k) for k in keys]

    @classmethod
    def delete(cls, *keys: str) -> int:
        """Delete one or more keys and return the number of removed keys."""
        removed = 0
        with MemoryCache._lock:
            for key in keys:
                found, _, _ = MemoryCache._get_entry(key)
                if found:
                    MemoryCache._store.pop(key, None)
                    removed += 1
        return removed

    @classmethod
    def keys(cls, pattern: str = "*") -> list[str]:
        """Return all non-expired keys matching a glob pattern."""
        MemoryCache._purge_expired()
        with MemoryCache._lock:
            return [k for k in MemoryCache._store if fnmatch.fnmatchcase(k, pattern)]

    @classmethod
    def scan(cls, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]:
        """Scan keyspace for non-expired keys matching an optional glob pattern."""
        matching = cls.keys(match or "*")
        if count is not None:
            matching = matching[:count]
        return 0, matching

    @classmethod
    def exists(cls, key: str) -> int:
        """Return 1 if key exists and is not expired, otherwise 0."""
        found, _, _ = MemoryCache._get_entry(key)
        return 1 if found else 0

    @classmethod
    def expire(cls, key: str, ttl: int | float | timedelta) -> bool:
        """Update the TTL on an existing non-expired key."""
        with MemoryCache._lock:
            found, value, _ = MemoryCache._get_entry(key)
            if not found:
                return False
            MemoryCache._store[key] = (value, _resolve_expiry(ttl))
            return True

    @classmethod
    def rpush(cls, key: str, value: Any, ttl: int | float | timedelta | None = None) -> int:
        """Append one or more values to a list stored at key."""
        with MemoryCache._lock:
            found, current, existing_expiry = MemoryCache._get_entry(key)
            if not found:
                items: list[Any] = []
            elif isinstance(current, list):
                items = current
            else:
                raise TypeError("WRONGTYPE Operation against a key holding the wrong kind of value")

            if isinstance(value, list):
                items.extend(value)
            else:
                items.append(value)

            expires_at = _resolve_expiry(ttl) if ttl is not None else existing_expiry
            MemoryCache._store[key] = (items, expires_at)
            return len(items)

    @classmethod
    def lrange(cls, key: str, start: int, end: int) -> list[Any]:
        """Return an inclusive slice of elements from a list stored at key."""
        with MemoryCache._lock:
            found, current, _ = MemoryCache._get_entry(key)
            if not found or not isinstance(current, list):
                return []
            length = len(current)
            if end == -1:
                stop: int | None = None
            elif end < 0:
                stop = max(0, length + end + 1)
            else:
                stop = end + 1
            return list(current[start:stop])

    @classmethod
    def clear(cls) -> None:
        """Clear all keys from the in-memory store."""
        with MemoryCache._lock:
            MemoryCache._store.clear()


cache = MemoryCache()
sync_cache = MemorySyncCache()


def __getattr__(name: str) -> Any:
    """Emit a DeprecationWarning when legacy RedisClient symbol is accessed."""
    if name == "RedisClient":
        warnings.warn(
            "goe.listener.utils.cache.RedisClient is deprecated and will be removed in GOE 2.0.0; "
            "use MemoryCache instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return MemoryCache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
