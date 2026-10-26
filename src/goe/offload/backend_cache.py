# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Per-session write-through cached catalog for backend table metadata."""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any

import msgspec

from goe.offload.schema.column_spec import ColumnSpec, get_column_names, match_table_column
from goe.typing import FrozenBaseStruct

__all__ = [
    "BackendTableSnapshot",
    "CachedBackendCatalog",
]


class BackendTableSnapshot(FrozenBaseStruct, frozen=True):
    """Immutable point-in-time metadata snapshot for a single backend table or view."""

    db_name: str
    table_name: str
    exists: bool
    fetched_at: float
    is_view: bool = False
    columns: tuple[ColumnSpec, ...] | None = None
    partition_columns: tuple[ColumnSpec, ...] | None = None
    clustering_columns: tuple[str, ...] | None = None
    size_bytes: int | None = None
    size_calculated: bool = False
    row_count: int | None = None
    row_count_calculated: bool = False
    native_handle: Any = None

    def replace(self, **changes: Any) -> "BackendTableSnapshot":
        """Return a modified copy of this snapshot."""
        return msgspec.structs.replace(self, **changes)


class CachedBackendCatalog:
    """Session-scoped LRU and monotonic-TTL catalog cache with write-through DDL/load invalidation."""

    def __init__(
        self,
        *,
        case_sensitive: bool = False,
        no_caching: bool = False,
        ttl_seconds: float = 60.0,
        maxsize: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._case_sensitive = case_sensitive
        self._no_caching = no_caching
        self._ttl_seconds = ttl_seconds
        self._maxsize = maxsize
        self._clock = clock
        self._lock = threading.RLock()
        self._snapshots: OrderedDict[tuple[str, str], BackendTableSnapshot] = OrderedDict()

    @property
    def no_caching(self) -> bool:
        """Return True when caching is disabled for unit test isolation."""
        return self._no_caching

    def get_snapshot(self, db_name: str, table_name: str) -> BackendTableSnapshot | None:
        """Return a fresh cached snapshot for (db_name, table_name) or None on miss/expiry."""
        if self._no_caching:
            return None
        key = self._normalize_key(db_name, table_name)
        now = self._clock()
        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is None:
                return None
            if now - snapshot.fetched_at > self._ttl_seconds:
                self._snapshots.pop(key, None)
                return None
            self._snapshots.move_to_end(key)
            return snapshot

    def put_snapshot(self, snapshot: BackendTableSnapshot) -> BackendTableSnapshot:
        """Store or replace a table snapshot in the bounded LRU cache."""
        if self._no_caching:
            return snapshot
        key = self._normalize_key(snapshot.db_name, snapshot.table_name)
        with self._lock:
            self._snapshots[key] = snapshot
            self._snapshots.move_to_end(key)
            while len(self._snapshots) > self._maxsize:
                self._snapshots.popitem(last=False)
        return snapshot

    def warm_schema(self, db_name: str, snapshots: Iterable[BackendTableSnapshot]) -> int:
        """Pre-populate the catalog cache with batch-fetched table snapshots for a dataset/schema."""
        if self._no_caching:
            return 0
        count = 0
        for snapshot in snapshots:
            if self._normalize_ident(snapshot.db_name) == self._normalize_ident(db_name):
                self.put_snapshot(snapshot)
                count += 1
        return count

    def table_exists(
        self,
        db_name: str,
        table_name: str,
        loader: Callable[[str, str], bool],
    ) -> bool:
        """Return cached table existence or populate via loader on cache miss."""
        snap = self.get_snapshot(db_name, table_name)
        if snap is not None:
            return snap.exists and not snap.is_view
        exists = bool(loader(db_name, table_name))
        self.put_snapshot(
            BackendTableSnapshot(
                db_name=db_name,
                table_name=table_name,
                exists=exists,
                fetched_at=self._clock(),
            )
        )
        return exists

    def get_columns(
        self,
        db_name: str,
        table_name: str,
        loader: Callable[[str, str], Iterable[ColumnSpec]],
    ) -> list[ColumnSpec]:
        """Return cached table columns or fetch via loader and update the snapshot."""
        snap = self.get_snapshot(db_name, table_name)
        if snap is not None and snap.columns is not None:
            return list(snap.columns)
        cols = tuple(loader(db_name, table_name))
        now = self._clock()
        updated = (
            snap.replace(exists=bool(cols) or snap.exists, columns=cols, fetched_at=now)
            if snap is not None
            else BackendTableSnapshot(
                db_name=db_name,
                table_name=table_name,
                exists=bool(cols),
                columns=cols,
                fetched_at=now,
            )
        )
        self.put_snapshot(updated)
        return list(cols)

    def get_column(
        self,
        db_name: str,
        table_name: str,
        column_name: str,
        loader: Callable[[str, str], Iterable[ColumnSpec]],
    ) -> ColumnSpec | None:
        """Return a single matching column from the cached column list."""
        return match_table_column(column_name, self.get_columns(db_name, table_name, loader))

    def get_column_names(
        self,
        db_name: str,
        table_name: str,
        loader: Callable[[str, str], Iterable[ColumnSpec]],
        conv_fn: Callable[[str], str] | None = None,
    ) -> list[str]:
        """Return column names from the cached column list."""
        return get_column_names(self.get_columns(db_name, table_name, loader), conv_fn=conv_fn)

    def get_partition_columns(
        self,
        db_name: str,
        table_name: str,
        loader: Callable[[str, str], Iterable[ColumnSpec]],
    ) -> list[ColumnSpec]:
        """Return cached partition columns or fetch via loader and update the snapshot."""
        snap = self.get_snapshot(db_name, table_name)
        if snap is not None and snap.partition_columns is not None:
            return list(snap.partition_columns)
        part_cols = tuple(loader(db_name, table_name))
        now = self._clock()
        updated = (
            snap.replace(partition_columns=part_cols, fetched_at=now)
            if snap is not None
            else BackendTableSnapshot(
                db_name=db_name,
                table_name=table_name,
                exists=True,
                partition_columns=part_cols,
                fetched_at=now,
            )
        )
        self.put_snapshot(updated)
        return list(part_cols)

    def get_table_size(
        self,
        db_name: str,
        table_name: str,
        loader: Callable[[str, str], int | None],
        *,
        no_cache: bool = False,
    ) -> int | None:
        """Return cached table size in bytes or fetch via loader."""
        if no_cache:
            return loader(db_name, table_name)
        snap = self.get_snapshot(db_name, table_name)
        if snap is not None and snap.size_calculated:
            return snap.size_bytes
        size_bytes = loader(db_name, table_name)
        now = self._clock()
        updated = (
            snap.replace(size_bytes=size_bytes, size_calculated=True, fetched_at=now)
            if snap is not None
            else BackendTableSnapshot(
                db_name=db_name,
                table_name=table_name,
                exists=size_bytes is not None,
                size_bytes=size_bytes,
                size_calculated=True,
                fetched_at=now,
            )
        )
        self.put_snapshot(updated)
        return size_bytes

    def get_table_row_count(
        self,
        db_name: str,
        table_name: str,
        loader: Callable[[str, str], int | None],
    ) -> int | None:
        """Return cached table row count or fetch via loader."""
        snap = self.get_snapshot(db_name, table_name)
        if snap is not None and snap.row_count_calculated:
            return snap.row_count
        row_count = loader(db_name, table_name)
        now = self._clock()
        updated = (
            snap.replace(row_count=row_count, row_count_calculated=True, fetched_at=now)
            if snap is not None
            else BackendTableSnapshot(
                db_name=db_name,
                table_name=table_name,
                exists=row_count is not None,
                row_count=row_count,
                row_count_calculated=True,
                fetched_at=now,
            )
        )
        self.put_snapshot(updated)
        return row_count

    def get_native_handle(
        self,
        db_name: str,
        table_name: str,
        loader: Callable[[str, str], Any],
    ) -> Any:
        """Return a cached SDK table object (such as google.cloud.bigquery.Table) or load and cache it."""
        snap = self.get_snapshot(db_name, table_name)
        if snap is not None and snap.native_handle is not None:
            return snap.native_handle
        handle = loader(db_name, table_name)
        now = self._clock()
        updated = (
            snap.replace(exists=True, native_handle=handle, fetched_at=now)
            if snap is not None
            else BackendTableSnapshot(
                db_name=db_name,
                table_name=table_name,
                exists=True,
                native_handle=handle,
                fetched_at=now,
            )
        )
        self.put_snapshot(updated)
        return handle

    def on_create_table(
        self,
        db_name: str,
        table_name: str,
        columns: Iterable[ColumnSpec] | None = None,
        partition_columns: Iterable[ColumnSpec] | None = None,
    ) -> None:
        """Write-through invalidation or eager snapshot seed when a table is created."""
        self.invalidate_table(db_name, table_name)
        if columns is not None and not self._no_caching:
            self.put_snapshot(
                BackendTableSnapshot(
                    db_name=db_name,
                    table_name=table_name,
                    exists=True,
                    columns=tuple(columns),
                    partition_columns=tuple(partition_columns) if partition_columns is not None else None,
                    size_bytes=0,
                    size_calculated=True,
                    row_count=0,
                    row_count_calculated=True,
                    fetched_at=self._clock(),
                )
            )

    def on_drop_table(self, db_name: str, table_name: str) -> None:
        """Evict cached state when a table or view is dropped."""
        self.invalidate_table(db_name, table_name)

    def on_alter_table(self, db_name: str, table_name: str) -> None:
        """Evict cached schema and handle state when a table is altered."""
        self.invalidate_table(db_name, table_name)

    def on_load_table(self, db_name: str, table_name: str) -> None:
        """Invalidate size, row count, and SDK handle while preserving column definitions after a data load."""
        if self._no_caching:
            return
        key = self._normalize_key(db_name, table_name)
        with self._lock:
            snap = self._snapshots.get(key)
            if snap is not None:
                self._snapshots[key] = snap.replace(
                    exists=True,
                    size_bytes=None,
                    size_calculated=False,
                    row_count=None,
                    row_count_calculated=False,
                    native_handle=None,
                    fetched_at=self._clock(),
                )

    def invalidate_table(self, db_name: str, table_name: str) -> None:
        """Evict a single table entry from the catalog cache."""
        key = self._normalize_key(db_name, table_name)
        with self._lock:
            self._snapshots.pop(key, None)

    def invalidate_schema(self, db_name: str) -> int:
        """Evict all cached tables belonging to db_name."""
        norm_db = self._normalize_ident(db_name)
        with self._lock:
            keys = [k for k in self._snapshots if k[0] == norm_db]
            for key in keys:
                self._snapshots.pop(key, None)
            return len(keys)

    def clear(self) -> None:
        """Remove all cached snapshots."""
        with self._lock:
            self._snapshots.clear()

    def _normalize_ident(self, name: str) -> str:
        return name if self._case_sensitive else name.upper()

    def _normalize_key(self, db_name: str, table_name: str) -> tuple[str, str]:
        return (self._normalize_ident(db_name), self._normalize_ident(table_name))
