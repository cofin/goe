# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for in-memory async and sync listener caches."""

import time

import pytest

from goe.listener.utils.cache import MemoryCache, MemorySyncCache


@pytest.mark.anyio
async def test_memory_cache_async_operations() -> None:
    """Verify async MemoryCache set, get, mget, keys, scan, exists, expire, and delete."""
    cache = MemoryCache()
    await cache.clear()

    assert await cache.ping() is True
    assert await cache.set("goe:test:key1", {"value": 1}) is True
    assert await cache.set("goe:test:key2", {"value": 2}, ttl=60) is True
    assert await cache.get("goe:test:key1") == {"value": 1}

    mget_result = await cache.mget(["goe:test:key1", "goe:test:key2", "goe:test:missing"])
    assert mget_result == [{"value": 1}, {"value": 2}, None]

    matched_keys = await cache.keys("goe:test:*")
    assert sorted(matched_keys) == ["goe:test:key1", "goe:test:key2"]

    cursor, scanned_keys = await cache.scan("goe:test:*")
    assert cursor == 0
    assert sorted(scanned_keys) == ["goe:test:key1", "goe:test:key2"]

    assert await cache.exists("goe:test:key1") == 1
    assert await cache.exists("goe:test:missing") == 0
    assert await cache.expire("goe:test:key1", 120) is True
    assert await cache.expire("goe:test:missing", 120) is False

    assert await cache.delete("goe:test:key1") == 1
    assert await cache.get("goe:test:key1") is None
    assert await cache.delete_keys("goe:test:*") == 1
    assert await cache.get("goe:test:key2") is None


def test_memory_sync_cache_and_shared_store() -> None:
    """Verify sync MemorySyncCache list operations, TTL expiration, and shared backing store."""
    sync_cache = MemorySyncCache.connect()
    sync_cache.clear()

    assert sync_cache.ping() is True
    assert sync_cache.set("goe:sync:k1", "alpha", ttl=60) is True
    assert sync_cache.get("goe:sync:k1") == "alpha"
    assert sync_cache.exists("goe:sync:k1") == 1
    assert sync_cache.expire("goe:sync:k1", 30) is True

    assert sync_cache.rpush("goe:sync:logs", ["line-1", "line-2"]) == 2
    assert sync_cache.rpush("goe:sync:logs", "line-3") == 3
    assert sync_cache.lrange("goe:sync:logs", 0, -1) == ["line-1", "line-2", "line-3"]
    assert sync_cache.lrange("goe:sync:logs", 0, 1) == ["line-1", "line-2"]

    sync_cache.set("goe:sync:ephemeral", "temp", ttl=0)
    time.sleep(0.01)
    assert sync_cache.get("goe:sync:ephemeral") is None

    assert sync_cache.delete("goe:sync:k1", "goe:sync:logs") == 2
    assert sync_cache.close_client() is None
