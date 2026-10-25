# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the thread-safe FrontendCatalogCache and OracleRepositoryService delegation."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from goe.offload.frontend_cache import FrontendCatalogCache
from goe.offload.oracle.catalog import (
    OracleCatalogService,
    OracleColumnMeta,
    OraclePartitionMeta,
    OracleSessionContext,
    OracleStorageStats,
    OracleSubpartitionMeta,
    OracleTableSnapshot,
)
from goe.persistence.oracle.oracle_repository import OracleRepositoryService


class _CountingCatalogService(OracleCatalogService):
    def __init__(self, delay: float = 0.0) -> None:
        super().__init__()
        self.delay = delay
        self.table_calls = 0
        self.ctx_calls = 0
        self._lock = threading.Lock()

    def fetch_table_snapshot(self, driver: Any, owner: str, table_name: str) -> OracleTableSnapshot:
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.table_calls += 1
        return _dummy_snapshot(owner.upper(), table_name.upper())

    def fetch_session_context(self, driver: Any) -> OracleSessionContext:
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.ctx_calls += 1
        return _dummy_context()


def test_cache_hit_and_ttl_expiry() -> None:
    now = [100.0]
    svc = _CountingCatalogService()
    cache = FrontendCatalogCache(
        catalog_service=svc,
        max_entries=4,
        ttl_seconds=10.0,
        clock=lambda: now[0],
    )

    s1 = cache.get_table_snapshot("ora-dsn", "sh", "sales", object())
    s2 = cache.get_table_snapshot("ora-dsn", "SH", "SALES", object())
    assert s1 == s2
    assert svc.table_calls == 1

    now[0] = 111.0
    cache.get_table_snapshot("ora-dsn", "SH", "SALES", object())
    assert svc.table_calls == 2


def test_lru_eviction_and_invalidation() -> None:
    svc = _CountingCatalogService()
    cache = FrontendCatalogCache(
        catalog_service=svc,
        max_entries=2,
        ttl_seconds=300.0,
    )
    cache.get_table_snapshot("dsn", "SH", "T1", object())
    cache.get_table_snapshot("dsn", "SH", "T2", object())
    cache.get_table_snapshot("dsn", "SH", "T1", object())
    cache.get_table_snapshot("dsn", "SH", "T3", object())
    assert svc.table_calls == 3

    cache.get_table_snapshot("dsn", "SH", "T1", object())
    assert svc.table_calls == 3

    cache.get_table_snapshot("dsn", "SH", "T2", object())
    assert svc.table_calls == 4

    cache.invalidate_table("dsn", "SH", "T1")
    cache.get_table_snapshot("dsn", "SH", "T1", object())
    assert svc.table_calls == 5

    cache.invalidate_schema("dsn", "SH")
    cache.get_table_snapshot("dsn", "SH", "T1", object())
    assert svc.table_calls == 6


def test_singleflight_deduplicates_concurrent_callers() -> None:
    svc = _CountingCatalogService(delay=0.05)
    cache = FrontendCatalogCache(
        catalog_service=svc,
        max_entries=16,
        ttl_seconds=300.0,
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(cache.get_table_snapshot, "dsn", "SH", "SALES", object()) for _ in range(8)]
        results = [f.result() for f in futures]

    assert svc.table_calls == 1
    assert all(r == results[0] for r in results)


def test_oracle_repository_service_table_introspection_uses_cache() -> None:
    svc = _CountingCatalogService()
    cache = FrontendCatalogCache(catalog_service=svc)

    class _FakeRegistry:
        settings = SimpleNamespace(dsn="ora-dsn")
        session_calls = 0

        @contextmanager
        def adm_session(self, *, action: str | None = None) -> Any:
            self.session_calls += 1
            yield object()

    fake_registry = _FakeRegistry()
    opts = SimpleNamespace(
        ora_repo_user="GOE_REPO",
        ora_adm_user="GOE_ADM",
        ora_adm_user_pass="secret",
        ora_app_user="GOE_APP",
        backend_distribution="GCP",
    )
    repo = OracleRepositoryService(
        opts,
        registry=fake_registry,
        catalog_cache=cache,
    )

    cols = repo.get_table_columns("sh", "sales")
    parts = repo.get_table_partitions("sh", "sales")
    subparts = repo.get_table_subpartitions("sh", "sales")

    assert len(cols) == 1
    assert cols[0].column_name == "ID"
    assert cols[0].partition_position == 1
    assert len(parts) == 1
    assert parts[0]["partition_name"] == "P1"
    assert len(subparts) == 1
    assert subparts[0].subpartition_name == "P1_SP1"
    assert svc.table_calls == 1


def _dummy_snapshot(owner: str = "SH", table_name: str = "SALES") -> OracleTableSnapshot:
    return OracleTableSnapshot(
        owner=owner,
        table_name=table_name,
        iot_type=None,
        partitioned=True,
        partitioning_type="RANGE",
        subpartitioning_type="LIST",
        degree="1",
        compression=None,
        compress_for=None,
        stats=OracleStorageStats(num_rows=10),
        columns=(OracleColumnMeta(column_id=1, name="ID", data_type="NUMBER", partition_position=1),),
        constraints=(),
        indexes=(),
        partitions=(
            OraclePartitionMeta(
                partition_name="P1",
                partition_position=1,
                high_value_csv="100",
                high_value_literals=(100,),
                subpartition_count=1,
                num_rows=10,
                size_in_bytes=1024,
                subpartitions=(
                    OracleSubpartitionMeta(
                        partition_name="P1",
                        partition_position=1,
                        subpartition_name="P1_SP1",
                        subpartition_position=1,
                        high_value_csv="'US'",
                        high_value_literals=("US",),
                        num_rows=10,
                        size_in_bytes=1024,
                    ),
                ),
            ),
        ),
        subpartitions=(
            OracleSubpartitionMeta(
                partition_name="P1",
                partition_position=1,
                subpartition_name="P1_SP1",
                subpartition_position=1,
                high_value_csv="'US'",
                high_value_literals=("US",),
                num_rows=10,
                size_in_bytes=1024,
            ),
        ),
    )


def _dummy_context() -> OracleSessionContext:
    return OracleSessionContext(
        version="23.4.0.24.05",
        db_unique_name="FREE",
        current_scn=100,
        compatible="23.0.0",
        db_block_size=8192,
        max_string_size="STANDARD",
        cell_offload_processing=False,
        current_user="GOE_ADM",
    )
