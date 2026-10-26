# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BackendCapabilities and CachedBackendCatalog."""

import pytest

from goe.offload.backend_cache import BackendTableSnapshot, CachedBackendCatalog
from goe.offload.backend_capabilities import CAPABILITY_FIELD_MAP, BackendCapabilities
from goe.offload.offload_constants import (
    BIGQUERY_BACKEND_CAPABILITIES,
    CAPABILITY_CASE_SENSITIVE,
    DBTYPE_BIGQUERY,
    DBTYPE_HIVE,
    DBTYPE_IMPALA,
    DBTYPE_SNOWFLAKE,
    DBTYPE_SPARK,
    DBTYPE_SYNAPSE,
    HIVE_BACKEND_CAPABILITIES,
    IMPALA_BACKEND_CAPABILITIES,
    SNOWFLAKE_BACKEND_CAPABILITIES,
    SPARK_BACKEND_CAPABILITIES,
    SYNAPSE_BACKEND_CAPABILITIES,
)
from goe.offload.schema.column_spec import BIGQUERY_TYPE_INT64, BIGQUERY_TYPE_STRING, ColumnDialect, ColumnSpec


@pytest.mark.parametrize(
    ("backend_type", "legacy_dict"),
    [
        (DBTYPE_BIGQUERY, BIGQUERY_BACKEND_CAPABILITIES),
        (DBTYPE_SNOWFLAKE, SNOWFLAKE_BACKEND_CAPABILITIES),
        (DBTYPE_SYNAPSE, SYNAPSE_BACKEND_CAPABILITIES),
        (DBTYPE_HIVE, HIVE_BACKEND_CAPABILITIES),
        (DBTYPE_IMPALA, IMPALA_BACKEND_CAPABILITIES),
        (DBTYPE_SPARK, SPARK_BACKEND_CAPABILITIES),
    ],
)
def test_capabilities_presets_match_legacy_constants(backend_type: str, legacy_dict: dict[str, bool]) -> None:
    """Verify BackendCapabilities presets match all legacy CAPABILITY_* constants."""
    caps = BackendCapabilities.for_backend(backend_type)
    assert caps.backend_type == backend_type
    assert caps.to_capability_dict() == legacy_dict
    for cap_key, expected_val in legacy_dict.items():
        assert caps.supports(cap_key) is expected_val
    with pytest.raises(KeyError, match="Unknown capability"):
        caps.supports("not_a_real_capability")


def test_capabilities_custom_dict_override_and_immutability() -> None:
    """Verify BackendCapabilities.for_backend applies custom capability dict overrides and is frozen."""
    override_dict = dict(BIGQUERY_BACKEND_CAPABILITIES)
    override_dict[CAPABILITY_CASE_SENSITIVE] = True
    caps = BackendCapabilities.for_backend(DBTYPE_BIGQUERY, override_dict)
    assert caps.case_sensitive is True
    assert caps.supports(CAPABILITY_CASE_SENSITIVE) is True
    updated = caps.replace(max_partition_columns=4)
    assert updated.max_partition_columns == 4
    assert caps.max_partition_columns == 1


def test_capabilities_sorted_table_modify_requires_sorted_table() -> None:
    """Verify sorted_table_modify_effective requires both sorted_table and sorted_table_modify."""
    caps_disabled = BackendCapabilities(
        backend_type=DBTYPE_BIGQUERY,
        sorted_table=False,
        sorted_table_modify=True,
    )
    assert caps_disabled.sorted_table_modify_effective is False

    caps_enabled = caps_disabled.replace(sorted_table=True)
    assert caps_enabled.sorted_table_modify_effective is True
    assert len(CAPABILITY_FIELD_MAP) == 34


def test_cached_catalog_hits_and_write_through_invalidation() -> None:
    """Verify CachedBackendCatalog caches repeated lookups and invalidates on DDL and load events."""
    calls = {"exists": 0, "columns": 0, "part_cols": 0, "size": 0, "rows": 0, "handle": 0}
    sample_cols = [
        ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64, nullable=False),
        ColumnSpec(ColumnDialect.BIGQUERY, "NAME", BIGQUERY_TYPE_STRING, nullable=True),
    ]
    sample_part_cols = [sample_cols[0]]

    def load_exists(db: str, tbl: str) -> bool:
        calls["exists"] += 1
        return True

    def load_cols(db: str, tbl: str) -> list[ColumnSpec]:
        calls["columns"] += 1
        return list(sample_cols)

    def load_part_cols(db: str, tbl: str) -> list[ColumnSpec]:
        calls["part_cols"] += 1
        return list(sample_part_cols)

    def load_size(db: str, tbl: str) -> int | None:
        calls["size"] += 1
        return 4096

    def load_rows(db: str, tbl: str) -> int | None:
        calls["rows"] += 1
        return 100

    def load_handle(db: str, tbl: str) -> object:
        calls["handle"] += 1
        return {"sdk_table": f"{db}.{tbl}"}

    catalog = CachedBackendCatalog(case_sensitive=False)
    assert catalog.table_exists("prod_db", "sales", load_exists) is True
    assert catalog.table_exists("PROD_DB", "SALES", load_exists) is True
    assert calls["exists"] == 1

    assert catalog.get_columns("PROD_DB", "SALES", load_cols) == sample_cols
    assert catalog.get_columns("prod_db", "sales", load_cols) == sample_cols
    assert catalog.get_column("prod_db", "sales", "id", load_cols) == sample_cols[0]
    assert catalog.get_column_names("prod_db", "sales", load_cols) == ["ID", "NAME"]
    assert calls["columns"] == 1

    assert catalog.get_partition_columns("PROD_DB", "SALES", load_part_cols) == sample_part_cols
    assert catalog.get_partition_columns("prod_db", "sales", load_part_cols) == sample_part_cols
    assert calls["part_cols"] == 1

    assert catalog.get_table_size("PROD_DB", "SALES", load_size) == 4096
    assert catalog.get_table_size("prod_db", "sales", load_size) == 4096
    assert calls["size"] == 1
    assert catalog.get_table_size("prod_db", "sales", load_size, no_cache=True) == 4096
    assert calls["size"] == 2

    assert catalog.get_table_row_count("PROD_DB", "SALES", load_rows) == 100
    assert catalog.get_table_row_count("prod_db", "sales", load_rows) == 100
    assert calls["rows"] == 1

    assert catalog.get_native_handle("PROD_DB", "SALES", load_handle) == {"sdk_table": "PROD_DB.SALES"}
    assert catalog.get_native_handle("prod_db", "sales", load_handle) == {"sdk_table": "PROD_DB.SALES"}
    assert calls["handle"] == 1

    catalog.on_load_table("PROD_DB", "SALES")
    assert catalog.get_columns("PROD_DB", "SALES", load_cols) == sample_cols
    assert catalog.get_partition_columns("PROD_DB", "SALES", load_part_cols) == sample_part_cols
    assert calls["columns"] == 1
    assert calls["part_cols"] == 1
    assert catalog.get_table_size("PROD_DB", "SALES", load_size) == 4096
    assert catalog.get_table_row_count("PROD_DB", "SALES", load_rows) == 100
    assert catalog.get_native_handle("PROD_DB", "SALES", load_handle) == {"sdk_table": "PROD_DB.SALES"}
    assert calls["size"] == 3
    assert calls["rows"] == 2
    assert calls["handle"] == 2

    catalog.on_alter_table("PROD_DB", "SALES")
    assert catalog.get_columns("PROD_DB", "SALES", load_cols) == sample_cols
    assert calls["columns"] == 2

    catalog.on_drop_table("PROD_DB", "SALES")
    assert catalog.table_exists("PROD_DB", "SALES", load_exists) is True
    assert calls["exists"] == 2

    catalog.on_create_table("PROD_DB", "SALES", columns=sample_cols, partition_columns=sample_part_cols)
    assert catalog.table_exists("PROD_DB", "SALES", load_exists) is True
    assert catalog.get_columns("PROD_DB", "SALES", load_cols) == sample_cols
    assert catalog.get_partition_columns("PROD_DB", "SALES", load_part_cols) == sample_part_cols
    assert catalog.get_table_size("PROD_DB", "SALES", load_size) == 0
    assert catalog.get_table_row_count("PROD_DB", "SALES", load_rows) == 0
    assert calls["exists"] == 2
    assert calls["columns"] == 2
    assert calls["part_cols"] == 1
    assert calls["size"] == 3
    assert calls["rows"] == 2


def test_cached_catalog_no_caching_and_ttl_expiry() -> None:
    """Verify no_caching bypasses storage and TTL expiration forces re-fetching."""
    now = [100.0]
    calls = {"exists": 0}

    def loader(db: str, tbl: str) -> bool:
        calls["exists"] += 1
        return True

    ttl_catalog = CachedBackendCatalog(ttl_seconds=10.0, clock=lambda: now[0])
    assert ttl_catalog.table_exists("DB", "TBL", loader) is True
    assert ttl_catalog.table_exists("DB", "TBL", loader) is True
    assert calls["exists"] == 1

    now[0] = 115.0
    assert ttl_catalog.table_exists("DB", "TBL", loader) is True
    assert calls["exists"] == 2

    disabled_catalog = CachedBackendCatalog(no_caching=True)
    assert disabled_catalog.no_caching is True
    assert disabled_catalog.table_exists("DB", "TBL", loader) is True
    assert disabled_catalog.table_exists("DB", "TBL", loader) is True
    assert calls["exists"] == 4


def test_cached_catalog_warm_schema_and_session_isolation() -> None:
    """Verify warm_schema pre-populates multiple tables and separate catalogs remain isolated."""
    cols = (ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64),)
    snapshots = [
        BackendTableSnapshot(
            db_name="PROD_DB",
            table_name="T1",
            exists=True,
            columns=cols,
            size_bytes=1024,
            size_calculated=True,
            fetched_at=50.0,
        ),
        BackendTableSnapshot(
            db_name="PROD_DB",
            table_name="T2",
            exists=True,
            columns=cols,
            size_bytes=2048,
            size_calculated=True,
            fetched_at=50.0,
        ),
        BackendTableSnapshot(
            db_name="OTHER_DB",
            table_name="T3",
            exists=True,
            columns=cols,
            fetched_at=50.0,
        ),
    ]
    catalog_a = CachedBackendCatalog(clock=lambda: 55.0)
    catalog_b = CachedBackendCatalog(clock=lambda: 55.0)

    warmed = catalog_a.warm_schema("prod_db", snapshots)
    assert warmed == 2

    def fail_loader(*_args: object) -> list[ColumnSpec]:
        raise AssertionError("Loader should not be called for warmed table")

    assert catalog_a.table_exists("PROD_DB", "T1", lambda _d, _t: False) is True
    assert catalog_a.get_columns("PROD_DB", "T1", fail_loader) == list(cols)
    assert catalog_a.get_table_size("PROD_DB", "T2", lambda _d, _t: 0) == 2048

    assert catalog_b.get_snapshot("PROD_DB", "T1") is None
    evicted = catalog_a.invalidate_schema("PROD_DB")
    assert evicted == 2
    assert catalog_a.get_snapshot("PROD_DB", "T1") is None
