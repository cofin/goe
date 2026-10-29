# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Thread-safe bounded LRU+TTL cache for frontend catalog snapshots and session contexts."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from goe.offload.oracle.catalog import (
    OracleCatalogService,
    OracleSessionContext,
    OracleTableSnapshot,
)
from goe.typing import BaseStruct

__all__ = [
    "FrontendCatalogCache",
    "get_frontend_catalog_cache",
]

_DEFAULT_CACHE: FrontendCatalogCache | None = None
_DEFAULT_CACHE_LOCK = threading.Lock()


def get_frontend_catalog_cache() -> FrontendCatalogCache:
    """Return the process-wide default FrontendCatalogCache singleton."""
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        with _DEFAULT_CACHE_LOCK:
            if _DEFAULT_CACHE is None:
                _DEFAULT_CACHE = FrontendCatalogCache()
    return _DEFAULT_CACHE


class _CachedSnapshotEntry(BaseStruct):
    expires_at: float
    snapshot: Any


class _CachedContextEntry(BaseStruct):
    expires_at: float
    context: OracleSessionContext


class FrontendCatalogCache:
    """Bounded LRU+TTL cache with per-key singleflight deduplication for frontend metadata."""

    def __init__(
        self,
        *,
        catalog_service: OracleCatalogService | None = None,
        max_entries: int = 512,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._catalog_service = catalog_service or OracleCatalogService()
        self._max_entries = max(1, max_entries)
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._snapshots: OrderedDict[tuple[str, str, str], _CachedSnapshotEntry] = OrderedDict()
        self._contexts: dict[str, _CachedContextEntry] = {}
        self._inflight: dict[tuple[Any, ...], threading.Event] = {}

    def get_table_snapshot(
        self,
        dsn: str,
        owner: str,
        table_name: str,
        driver: Any,
        *,
        force_refresh: bool = False,
    ) -> OracleTableSnapshot | None:
        """Return a cached or freshly fetched OracleTableSnapshot for (dsn, owner, table_name)."""
        return self.get_or_load_snapshot(
            dsn,
            owner,
            table_name,
            lambda: self._catalog_service.fetch_table_snapshot(driver, owner, table_name),
            force_refresh=force_refresh,
        )

    def get_or_load_snapshot(
        self,
        dsn: str,
        owner: str,
        table_name: str,
        loader: Callable[[], Any],
        *,
        force_refresh: bool = False,
    ) -> Any:
        """Return a cached or freshly loaded table catalog snapshot for (dsn, owner, table_name)."""
        key = (dsn.strip().lower(), owner.strip().upper(), table_name.strip().upper())
        flight_key = ("table", *key)

        while True:
            with self._lock:
                now = self._clock()
                if not force_refresh and key in self._snapshots:
                    entry = self._snapshots[key]
                    if entry.expires_at > now:
                        self._snapshots.move_to_end(key)
                        return entry.snapshot
                    del self._snapshots[key]

                wait_event = self._inflight.get(flight_key)
                if wait_event is None:
                    my_event = threading.Event()
                    self._inflight[flight_key] = my_event
                    break

            wait_event.wait()
            force_refresh = False

        try:
            snapshot = loader()
            with self._lock:
                self._snapshots[key] = _CachedSnapshotEntry(
                    expires_at=self._clock() + self._ttl_seconds,
                    snapshot=snapshot,
                )
                self._snapshots.move_to_end(key)
                while len(self._snapshots) > self._max_entries:
                    self._snapshots.popitem(last=False)
            return snapshot
        finally:
            with self._lock:
                done = self._inflight.pop(flight_key, None)
                if done is not None:
                    done.set()

    def get_session_context(
        self,
        dsn: str,
        driver: Any,
        *,
        force_refresh: bool = False,
    ) -> OracleSessionContext:
        """Return a cached or freshly fetched OracleSessionContext for dsn."""
        norm_dsn = dsn.strip().lower()
        flight_key = ("ctx", norm_dsn)

        while True:
            with self._lock:
                now = self._clock()
                if not force_refresh and norm_dsn in self._contexts:
                    entry = self._contexts[norm_dsn]
                    if entry.expires_at > now:
                        return entry.context
                    del self._contexts[norm_dsn]

                wait_event = self._inflight.get(flight_key)
                if wait_event is None:
                    my_event = threading.Event()
                    self._inflight[flight_key] = my_event
                    break

            wait_event.wait()
            force_refresh = False

        try:
            ctx = self._catalog_service.fetch_session_context(driver)
            with self._lock:
                self._contexts[norm_dsn] = _CachedContextEntry(
                    expires_at=self._clock() + self._ttl_seconds,
                    context=ctx,
                )
            return ctx
        finally:
            with self._lock:
                done = self._inflight.pop(flight_key, None)
                if done is not None:
                    done.set()

    def invalidate_table(self, dsn: str, owner: str, table_name: str) -> None:
        """Evict the cached snapshot for a single (dsn, owner, table_name)."""
        key = (dsn.strip().lower(), owner.strip().upper(), table_name.strip().upper())
        with self._lock:
            self._snapshots.pop(key, None)

    def invalidate_schema(self, dsn: str, owner: str) -> None:
        """Evict all cached snapshots belonging to (dsn, owner)."""
        norm_dsn = dsn.strip().lower()
        norm_owner = owner.strip().upper()
        with self._lock:
            to_remove = [k for k in self._snapshots if k[0] == norm_dsn and k[1] == norm_owner]
            for k in to_remove:
                del self._snapshots[k]

    def clear(self) -> None:
        """Clear all cached table snapshots and session contexts."""
        with self._lock:
            self._snapshots.clear()
            self._contexts.clear()
