# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Snowflake backend API, catalog caching, schema warm-up, and table operations."""

from __future__ import annotations

from unittest.mock import MagicMock

from goe.offload.backend_capabilities import BackendCapabilities
from goe.offload.offload_constants import DBTYPE_SNOWFLAKE
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_backend_api, create_backend_table
from goe.offload.schema.column_spec import (
    GOE_TYPE_DECIMAL,
    GOE_TYPE_VARIABLE_STRING,
    SNOWFLAKE_TYPE_NUMBER,
    SNOWFLAKE_TYPE_TEXT,
    ColumnDialect,
    ColumnSpec,
)
from goe.offload.snowflake.snowflake_backend_api import SNOWFLAKE_CAPABILITIES
from tests.unit.test_functions import FAKE_ORACLE_SNOWFLAKE_ENV, build_mock_options


def test_snowflake_capabilities_and_limits() -> None:
    api = _make_snowflake_api()
    assert isinstance(api.capabilities, BackendCapabilities)
    assert api.capabilities == SNOWFLAKE_CAPABILITIES
    assert api.case_sensitive_identifiers() is True
    assert api.parameterized_queries_supported() is True
    assert api.sorted_table_supported() is True
    assert api.sorted_table_modify_supported() is True
    assert api.partition_by_column_supported() is False
    assert api.max_decimal_precision() == 38
    assert api.max_decimal_scale() == 37
    assert api.max_decimal_integral_magnitude() == 38
    assert api.max_table_name_length() == 255


def test_snowflake_type_registry_round_trips() -> None:
    api = _make_snowflake_api()
    canonical_dec = ColumnSpec(
        ColumnDialect.CANONICAL,
        "AMOUNT",
        GOE_TYPE_DECIMAL,
        data_precision=12,
        data_scale=2,
    )
    sf_col = api.from_canonical_column(canonical_dec)
    assert sf_col.dialect is ColumnDialect.SNOWFLAKE
    assert sf_col.data_type == SNOWFLAKE_TYPE_NUMBER
    assert sf_col.data_precision == 12
    assert sf_col.data_scale == 2

    round_trip = api.to_canonical_column(sf_col)
    assert round_trip.dialect is ColumnDialect.CANONICAL
    assert round_trip.data_type == GOE_TYPE_DECIMAL
    assert round_trip.data_precision == 12
    assert round_trip.data_scale == 2


def test_snowflake_catalog_caching_and_invalidation() -> None:
    api = _make_snowflake_api()
    col = ColumnSpec(ColumnDialect.SNOWFLAKE, "ID", SNOWFLAKE_TYPE_NUMBER, data_precision=38, data_scale=0)
    api._fetch_table_exists = MagicMock(return_value=True)
    api._fetch_columns = MagicMock(return_value=[col])
    api._fetch_table_size_and_row_count = MagicMock(return_value=(4096, 100))

    assert api.table_exists("MY_SCHEMA", "MY_TABLE") is True
    assert api.table_exists("MY_SCHEMA", "MY_TABLE") is True
    assert api._fetch_table_exists.call_count == 1

    assert api.get_columns("MY_SCHEMA", "MY_TABLE") == [col]
    assert api.get_columns("MY_SCHEMA", "MY_TABLE") == [col]
    assert api._fetch_columns.call_count == 1

    assert api.get_table_size("MY_SCHEMA", "MY_TABLE") == 4096
    assert api.get_table_row_count_from_metadata("MY_SCHEMA", "MY_TABLE") == 100
    assert api._fetch_table_size_and_row_count.call_count == 1

    api.add_columns("MY_SCHEMA", "MY_TABLE", [("NEW_COL", "TEXT")])
    assert api.get_columns("MY_SCHEMA", "MY_TABLE") == [col]
    assert api._fetch_columns.call_count == 2

    api._fetch_table_exists.return_value = False
    api.drop_table("MY_SCHEMA", "MY_TABLE")
    assert api.table_exists("MY_SCHEMA", "MY_TABLE") is False
    assert api._fetch_table_exists.call_count == 2


def test_snowflake_warm_schema_two_queries() -> None:
    api = _make_snowflake_api(dry_run=False)
    queries: list[tuple[str, list]] = []

    def _fake_fetch_all(sql: str, log_level=None, query_params=None, **kwargs):
        queries.append((sql, list(query_params or [])))
        if "information_schema.tables" in sql.lower():
            return [
                ("ORDERS", "BASE TABLE", 8192, 250),
                ("ORDERS_V", "VIEW", None, None),
            ]
        return [
            ("ORDERS", "ID", "NUMBER", "NO", None, None, 38, 0, None),
            ("ORDERS", "NAME", "TEXT", "YES", 100, 400, None, None, None),
        ]

    api.execute_query_fetch_all = _fake_fetch_all
    api._fetch_table_exists = MagicMock(side_effect=AssertionError("Should hit warmed cache"))
    api._fetch_columns = MagicMock(side_effect=AssertionError("Should hit warmed cache"))
    api._fetch_table_size_and_row_count = MagicMock(side_effect=AssertionError("Should hit warmed cache"))

    warmed = api.warm_schema("SALES")
    assert warmed == 2
    assert len(queries) == 2

    assert api.table_exists("SALES", "ORDERS") is True
    assert api.table_exists("SALES", "ORDERS_V") is False
    cols = api.get_columns("SALES", "ORDERS")
    assert len(cols) == 2
    assert cols[0].name == "ID"
    assert cols[1].name == "NAME"
    assert api.get_table_size("SALES", "ORDERS") == 8192
    assert api.get_table_row_count_from_metadata("SALES", "ORDERS") == 250


def test_snowflake_table_create_and_load_final_table() -> None:
    table = _make_snowflake_table()
    cols = [
        ColumnSpec(ColumnDialect.SNOWFLAKE, "ID", SNOWFLAKE_TYPE_NUMBER, data_precision=38, data_scale=0),
        ColumnSpec(ColumnDialect.SNOWFLAKE, "NAME", SNOWFLAKE_TYPE_TEXT),
    ]
    table.set_columns(cols)
    table._sort_columns = ["ID"]

    ddl_cmds = table.create_backend_table()
    assert len(ddl_cmds) == 1
    assert "CREATE TABLE" in ddl_cmds[0]
    assert 'CLUSTER BY ("ID")' in ddl_cmds[0]

    rdbms_cols = [
        ColumnSpec(ColumnDialect.CANONICAL, "ID", GOE_TYPE_DECIMAL, data_precision=38, data_scale=0),
        ColumnSpec(ColumnDialect.CANONICAL, "NAME", GOE_TYPE_VARIABLE_STRING, data_length=100),
    ]
    staging_cols = [
        ColumnSpec(ColumnDialect.SNOWFLAKE, "ID", SNOWFLAKE_TYPE_TEXT),
        ColumnSpec(ColumnDialect.SNOWFLAKE, "NAME", SNOWFLAKE_TYPE_TEXT),
    ]
    table.set_final_table_casts(rdbms_cols, staging_cols)
    executed_dml: list = []
    table._execute_dml = lambda sqls, **kwargs: executed_dml.extend(sqls) or sqls
    table.load_final_table()
    assert len(executed_dml) == 1
    assert "COPY INTO" in executed_dml[0]
    assert '$1:"ID"' in executed_dml[0]


def _make_snowflake_api(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_SNOWFLAKE_ENV)
    if config.snowflake_database is None:
        config.snowflake_database = "TEST_DB"
    return create_backend_api(
        DBTYPE_SNOWFLAKE,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )


def _make_snowflake_table(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_SNOWFLAKE_ENV)
    if config.snowflake_database is None:
        config.snowflake_database = "TEST_DB"
    return create_backend_table(
        "MY_SCHEMA",
        "MY_TABLE",
        DBTYPE_SNOWFLAKE,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )
