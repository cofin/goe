# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for MSSQLSourceTable, ColumnSpec, OffloadTransportMSSQLApi, and mssql-python extras."""

import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from goe.offload.microsoft.mssql_frontend_api import (
    MssqlTableCatalogSnapshot,
    mssql_column_from_dictionary_row,
)
from goe.offload.microsoft.mssql_offload_source_table import MSSQLSourceTable
from goe.offload.microsoft.mssql_offload_transport_rdbms_api import OffloadTransportMSSQLApi
from goe.offload.offload_constants import DBTYPE_MSSQL
from goe.offload.schema.column_spec import (
    GOE_TYPE_BINARY,
    GOE_TYPE_BOOLEAN,
    GOE_TYPE_DATE,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_DOUBLE,
    GOE_TYPE_FIXED_STRING,
    GOE_TYPE_FLOAT,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_TIME,
    GOE_TYPE_TIMESTAMP,
    GOE_TYPE_TIMESTAMP_TZ,
    GOE_TYPE_VARIABLE_STRING,
    MSSQL_TYPE_BIGINT,
    MSSQL_TYPE_BIT,
    MSSQL_TYPE_CHAR,
    MSSQL_TYPE_DATE,
    MSSQL_TYPE_DATETIME2,
    MSSQL_TYPE_DATETIMEOFFSET,
    MSSQL_TYPE_DECIMAL,
    MSSQL_TYPE_FLOAT,
    MSSQL_TYPE_MONEY,
    MSSQL_TYPE_NVARCHAR,
    MSSQL_TYPE_REAL,
    MSSQL_TYPE_TIME,
    MSSQL_TYPE_UNIQUEIDENTIFIER,
    MSSQL_TYPE_VARBINARY,
    MSSQL_TYPE_VARCHAR,
    ColumnDialect,
    ColumnSpec,
)


def test_mssql_column_from_mssql_and_type_predicates() -> None:
    dec_col = mssql_column_from_dictionary_row(("amount", 1, "YES", "decimal", 18, 2, None, "0.00", None, None))
    assert dec_col.name == "amount"
    assert dec_col.format_data_type() == "decimal(18,2)"
    assert dec_col.is_number_based() is True
    assert dec_col.is_date_based() is False
    assert dec_col.is_string_based() is False
    assert dec_col.valid_for_offload_predicate() is True

    str_col = mssql_column_from_dictionary_row(("code", 2, "NO", "varchar", None, None, 64, None, None, 64))
    assert str_col.format_data_type() == "varchar(64)"
    assert str_col.is_string_based() is True
    assert str_col.valid_for_offload_predicate() is True

    tz_col = mssql_column_from_dictionary_row(
        ("created_at", 3, "NO", "datetimeoffset", 7, None, None, None, None, None)
    )
    assert tz_col.is_date_based() is True
    assert tz_col.is_time_zone_based() is True
    assert tz_col.valid_for_offload_predicate() is False


def test_mssql_source_table_canonical_column_round_trip() -> None:
    options = SimpleNamespace(
        db_type=DBTYPE_MSSQL,
        rdbms_dsn="server=sqlhost;port=1433;database=salesdb",
        rdbms_app_user="app_user",
        rdbms_app_pass="secret",
    )
    table = MSSQLSourceTable(
        "sales",
        "orders",
        options,
        MagicMock(),
        dry_run=True,
        do_not_connect=True,
    )

    cases = [
        (ColumnSpec(ColumnDialect.MSSQL, "c_bigint", MSSQL_TYPE_BIGINT), GOE_TYPE_INTEGER_8),
        (ColumnSpec(ColumnDialect.MSSQL, "c_bit", MSSQL_TYPE_BIT), GOE_TYPE_BOOLEAN),
        (
            ColumnSpec(ColumnDialect.MSSQL, "c_dec_int", MSSQL_TYPE_DECIMAL, data_precision=10, data_scale=0),
            GOE_TYPE_INTEGER_8,
        ),
        (
            ColumnSpec(ColumnDialect.MSSQL, "c_dec", MSSQL_TYPE_DECIMAL, data_precision=18, data_scale=4),
            GOE_TYPE_DECIMAL,
        ),
        (
            ColumnSpec(ColumnDialect.MSSQL, "c_money", MSSQL_TYPE_MONEY, data_precision=19, data_scale=4),
            GOE_TYPE_DECIMAL,
        ),
        (ColumnSpec(ColumnDialect.MSSQL, "c_float", MSSQL_TYPE_FLOAT), GOE_TYPE_DOUBLE),
        (ColumnSpec(ColumnDialect.MSSQL, "c_real", MSSQL_TYPE_REAL), GOE_TYPE_FLOAT),
        (ColumnSpec(ColumnDialect.MSSQL, "c_date", MSSQL_TYPE_DATE), GOE_TYPE_DATE),
        (ColumnSpec(ColumnDialect.MSSQL, "c_dt2", MSSQL_TYPE_DATETIME2), GOE_TYPE_TIMESTAMP),
        (ColumnSpec(ColumnDialect.MSSQL, "c_dto", MSSQL_TYPE_DATETIMEOFFSET), GOE_TYPE_TIMESTAMP_TZ),
        (ColumnSpec(ColumnDialect.MSSQL, "c_time", MSSQL_TYPE_TIME), GOE_TYPE_TIME),
        (ColumnSpec(ColumnDialect.MSSQL, "c_varchar", MSSQL_TYPE_VARCHAR, data_length=100), GOE_TYPE_VARIABLE_STRING),
        (ColumnSpec(ColumnDialect.MSSQL, "c_nvarchar", MSSQL_TYPE_NVARCHAR, data_length=50), GOE_TYPE_VARIABLE_STRING),
        (ColumnSpec(ColumnDialect.MSSQL, "c_char", MSSQL_TYPE_CHAR, data_length=10), GOE_TYPE_FIXED_STRING),
        (ColumnSpec(ColumnDialect.MSSQL, "c_varbin", MSSQL_TYPE_VARBINARY, data_length=16), GOE_TYPE_BINARY),
        (
            ColumnSpec(ColumnDialect.MSSQL, "c_uuid", MSSQL_TYPE_UNIQUEIDENTIFIER, data_length=36),
            GOE_TYPE_VARIABLE_STRING,
        ),
    ]
    for mssql_col, expected_canonical_type in cases:
        canonical = table.to_canonical_column(mssql_col)
        assert canonical.data_type == expected_canonical_type
        assert table.valid_canonical_override(mssql_col, expected_canonical_type) is True


def test_mssql_source_table_hydrates_from_table_snapshot() -> None:
    col1 = ColumnSpec(ColumnDialect.MSSQL, "order_id", MSSQL_TYPE_BIGINT, nullable=False)
    col2 = ColumnSpec(ColumnDialect.MSSQL, "amount", MSSQL_TYPE_DECIMAL, data_precision=18, data_scale=2, nullable=True)
    snapshot = MssqlTableCatalogSnapshot(
        schema_name="sales",
        table_name="orders",
        table_exists=True,
        num_rows=500,
        partitioned="NO",
        size_bytes=32768,
        columns=(col1, col2),
        primary_key_columns=("order_id",),
        hash_bucket_candidate="order_id",
    )
    fake_db_api = MagicMock()
    fake_db_api.get_table_snapshot.return_value = snapshot
    options = SimpleNamespace(
        db_type=DBTYPE_MSSQL,
        rdbms_dsn="server=sqlhost;port=1433;database=salesdb",
        rdbms_app_user="app_user",
        rdbms_app_pass="secret",
    )
    table = MSSQLSourceTable(
        "sales",
        "orders",
        options,
        MagicMock(),
        dry_run=True,
        do_not_connect=False,
        db_api=fake_db_api,
    )

    assert table.exists() is True
    assert table.stats_num_rows == 500
    assert table.size_in_bytes == 32768
    assert [c.name for c in table.columns] == ["order_id", "amount"]
    assert table.get_primary_key_columns() == ["order_id"]
    assert table.get_hash_bucket_candidate() == "order_id"
    fake_db_api.get_table_snapshot.assert_called_once_with("sales", "orders")


def test_offload_transport_mssql_api_removes_sqoop_methods() -> None:
    for attr in dir(OffloadTransportMSSQLApi):
        assert not attr.startswith("sqoop_rdbms_specific_")

    options = SimpleNamespace(
        db_type=DBTYPE_MSSQL,
        rdbms_dsn="sqlhost:1433;databaseName=salesdb",
        offload_transport_dsn="sqlhost:1433;databaseName=salesdb",
        offload_transport_user="transport_user",
        offload_transport_rdbms_session_parameters=None,
    )
    api = OffloadTransportMSSQLApi("sales", "orders", options, MagicMock(), dry_run=True)
    assert api.get_rdbms_canary_query() == "SELECT 1"
    assert api.jdbc_url() == '"jdbc:sqlserver://sqlhost:1433;databaseName=salesdb"'


def test_pyproject_declares_mssql_python_and_not_pymssql() -> None:
    pyproject_path = Path(__file__).resolve().parents[4] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    opt_deps = data["project"]["optional-dependencies"]

    assert "mssql-python" in opt_deps["sql_server"]
    assert "mssql-python" in opt_deps["mssql"]
    assert "mssql-python" in opt_deps["all"]
    for group_deps in opt_deps.values():
        assert "pymssql" not in group_deps
