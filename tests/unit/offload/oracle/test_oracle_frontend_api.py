# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OracleFrontendApi delegation to FrontendCatalogCache and OracleCatalogService."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from goe.offload.frontend_cache import FrontendCatalogCache
from goe.offload.oracle.catalog import (
    OracleCatalogService,
    OracleColumnMeta,
    OracleConstraintMeta,
    OraclePartitionMeta,
    OracleSessionContext,
    OracleStorageStats,
    OracleSubpartitionMeta,
    OracleTableSnapshot,
)
from goe.offload.oracle.oracle_frontend_api import OracleFrontendApi


class _DummyMessages:
    def log(self, *args: Any, **kwargs: Any) -> None:
        pass

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeDriver:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, sql: str, params: Any = None, **kwargs: Any) -> Any:
        self.executed.append(sql)
        return None


class _FakeRegistry:
    def __init__(self, driver: _FakeDriver | None = None) -> None:
        self.driver = driver or _FakeDriver()

    @contextmanager
    def adm_session(self) -> Any:
        yield self.driver


class _StubCatalogService(OracleCatalogService):
    def __init__(self) -> None:
        super().__init__()
        self.table_calls = 0
        self.ctx_calls = 0

    def fetch_table_snapshot(self, driver: Any, owner: str, table_name: str) -> OracleTableSnapshot:
        self.table_calls += 1
        return OracleTableSnapshot(
            owner=owner.upper(),
            table_name=table_name.upper(),
            iot_type=None,
            partitioned=True,
            partitioning_type="RANGE",
            subpartitioning_type="LIST",
            degree="4",
            compression="ENABLED",
            compress_for="QUERY HIGH",
            stats=OracleStorageStats(num_rows=500, blocks=20, avg_row_len=40, size_in_bytes=163840),
            columns=(
                OracleColumnMeta(
                    column_id=1,
                    name="ID",
                    data_type="NUMBER",
                    data_length=22,
                    data_precision=10,
                    data_scale=0,
                    nullable=False,
                    partition_position=1,
                ),
                OracleColumnMeta(
                    column_id=2,
                    name="REGION",
                    data_type="VARCHAR2",
                    data_length=10,
                    char_length=10,
                    char_used="B",
                    nullable=True,
                    subpartition_position=1,
                ),
            ),
            constraints=(
                OracleConstraintMeta(
                    constraint_name="PK_SALES",
                    constraint_type="P",
                    status="ENABLED",
                    validated="VALIDATED",
                    column_names=("ID",),
                ),
            ),
            indexes=(),
            partitions=(
                OraclePartitionMeta(
                    partition_name="P1",
                    partition_position=1,
                    high_value_csv="100",
                    high_value_literals=(100,),
                    subpartition_count=1,
                    num_rows=500,
                    blocks=20,
                    avg_row_len=40,
                    size_in_bytes=163840,
                ),
            ),
            subpartitions=(
                OracleSubpartitionMeta(
                    partition_name="P1",
                    partition_position=1,
                    subpartition_name="P1_US",
                    subpartition_position=1,
                    high_value_csv="'US'",
                    high_value_literals=("US",),
                    num_rows=500,
                    blocks=20,
                    avg_row_len=40,
                    size_in_bytes=163840,
                ),
            ),
        )

    def fetch_session_context(self, driver: Any) -> OracleSessionContext:
        self.ctx_calls += 1
        return OracleSessionContext(
            version="23.4.0.24.05",
            db_unique_name="FREE",
            current_scn=55555,
            compatible="23.0.0",
            db_block_size=8192,
            max_string_size="STANDARD",
            cell_offload_processing=False,
            current_user="GOE_ADM",
        )


def test_oracle_frontend_api_catalog_methods_use_cached_snapshot() -> None:
    svc = _StubCatalogService()
    cache = FrontendCatalogCache(catalog_service=svc)
    reg = _FakeRegistry()
    api = OracleFrontendApi(
        _dummy_options(),
        "ORACLE",
        _DummyMessages(),
        do_not_connect=True,
        registry=reg,
        catalog_cache=cache,
        catalog_service=svc,
    )

    cols = api.get_columns("SH", "SALES")
    pcols = api.get_partition_columns("SH", "SALES")
    spcols = api.get_subpartition_columns("SH", "SALES")
    pk_cols = api.get_primary_key_column_names("SH", "SALES")
    row_cnt = api.get_table_row_count_from_metadata("SH", "SALES")
    tab_size = api.get_table_size("SH", "SALES")
    exists = api.table_exists("SH", "SALES")
    is_iot = api.is_iot("SH", "SALES")

    assert len(cols) == 2
    assert [c.name for c in pcols] == ["ID"]
    assert [c.name for c in spcols] == ["REGION"]
    assert pk_cols == ["ID"]
    assert row_cnt == 500
    assert tab_size == 163840
    assert exists is True
    assert is_iot is False
    assert svc.table_calls == 1

    assert api.frontend_version() == "23.4.0.24.05"
    assert api.get_db_unique_name() == "FREE"
    assert api.get_current_scn() == 55555
    assert api.get_session_user() == "GOE_ADM"
    assert svc.ctx_calls == 1


def test_oracle_frontend_api_ddl_invalidates_cache() -> None:
    svc = _StubCatalogService()
    cache = FrontendCatalogCache(catalog_service=svc)
    reg = _FakeRegistry()
    api = OracleFrontendApi(
        _dummy_options(),
        "ORACLE",
        _DummyMessages(),
        do_not_connect=True,
        registry=reg,
        catalog_cache=cache,
        catalog_service=svc,
    )

    api.get_columns("SH", "SALES")
    assert svc.table_calls == 1

    api.execute_ddl('DROP TABLE "SH"."SALES"', log_level=None)
    api.get_columns("SH", "SALES")
    assert svc.table_calls == 2


def _dummy_options() -> Any:
    return SimpleNamespace(
        ora_adm_user="GOE_ADM",
        ora_adm_pass="secret",
        ora_app_user="GOE_APP",
        ora_app_pass="secret",
        rdbms_dsn="ora-dsn",
    )
