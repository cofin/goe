# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Azure Synapse backend API, SQLSpec MssqlPythonConfig, catalog cache, and table operations."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from goe.offload.backend_capabilities import BackendCapabilities
from goe.offload.microsoft import synapse_backend_api
from goe.offload.microsoft.synapse_backend_api import (
    SYNAPSE_CAPABILITIES,
    build_synapse_mssql_config,
)
from goe.offload.microsoft.synapse_constants import (
    SYNAPSE_AUTH_MECHANISM_AD_MSI,
    SYNAPSE_AUTH_MECHANISM_AD_SERVICE_PRINCIPAL,
    SYNAPSE_AUTH_MECHANISM_SQL_PASSWORD,
)
from goe.offload.offload_constants import DBTYPE_SYNAPSE, OFFLOAD_STATS_METHOD_NATIVE
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_backend_api, create_backend_table
from goe.offload.schema.column_spec import (
    GOE_TYPE_DECIMAL,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_VARIABLE_STRING,
    SYNAPSE_TYPE_BIGINT,
    SYNAPSE_TYPE_NUMERIC,
    SYNAPSE_TYPE_VARCHAR,
    ColumnDialect,
    ColumnSpec,
)
from goe.util.module_loader import import_optional
from tests.unit.test_functions import FAKE_ORACLE_SYNAPSE_ENV, build_mock_options


def test_synapse_uses_sqlspec_mssql_config_for_auth_modes() -> None:
    fake_adapter = SimpleNamespace(
        MssqlPythonPoolParams=lambda **kwargs: kwargs,
        MssqlPythonConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    ctx = (
        nullcontext()
        if import_optional("mssql_python") is not None
        else patch.object(synapse_backend_api, "ensure_module", return_value=fake_adapter)
    )
    with ctx:
        sql_opts = build_mock_options(FAKE_ORACLE_SYNAPSE_ENV)
        sql_opts.synapse_database = "SYNAPSE_DB"
        sql_opts.synapse_server = "synapse.sql.azuresynapse.net"
        sql_opts.synapse_port = 1433
        sql_opts.synapse_auth_mechanism = SYNAPSE_AUTH_MECHANISM_SQL_PASSWORD
        sql_opts.synapse_user = "sql_admin"
        sql_opts.synapse_pass = "secret_pw"

        cfg_sql = build_synapse_mssql_config(sql_opts, password_decryptor=lambda p: f"dec:{p}")
        assert cfg_sql.connection_config["server"] == "synapse.sql.azuresynapse.net"
        assert cfg_sql.connection_config["database"] == "SYNAPSE_DB"
        assert cfg_sql.connection_config["user"] == "sql_admin"
        assert cfg_sql.connection_config["password"] == "dec:secret_pw"
        assert cfg_sql.connection_config["authentication"] == SYNAPSE_AUTH_MECHANISM_SQL_PASSWORD

        sp_opts = build_mock_options(FAKE_ORACLE_SYNAPSE_ENV)
        sp_opts.synapse_database = "SYNAPSE_DB"
        sp_opts.synapse_server = "synapse.sql.azuresynapse.net"
        sp_opts.synapse_port = 1433
        sp_opts.synapse_auth_mechanism = SYNAPSE_AUTH_MECHANISM_AD_SERVICE_PRINCIPAL
        sp_opts.synapse_service_principal_id = "app-client-id"
        sp_opts.synapse_service_principal_secret = "app-client-secret"

        cfg_sp = build_synapse_mssql_config(sp_opts)
        assert cfg_sp.connection_config["user"] == "app-client-id"
        assert cfg_sp.connection_config["password"] == "app-client-secret"
        assert cfg_sp.connection_config["authentication"] == SYNAPSE_AUTH_MECHANISM_AD_SERVICE_PRINCIPAL

        msi_opts = build_mock_options(FAKE_ORACLE_SYNAPSE_ENV)
        msi_opts.synapse_database = "SYNAPSE_DB"
        msi_opts.synapse_server = "synapse.sql.azuresynapse.net"
        msi_opts.synapse_port = 1433
        msi_opts.synapse_auth_mechanism = SYNAPSE_AUTH_MECHANISM_AD_MSI
        msi_opts.synapse_msi_client_id = "msi-client-id"

        cfg_msi = build_synapse_mssql_config(msi_opts)
        assert cfg_msi.connection_config["user"] == "msi-client-id"
        assert cfg_msi.connection_config["password"] is None
        assert cfg_msi.connection_config["authentication"] == SYNAPSE_AUTH_MECHANISM_AD_MSI


def test_synapse_capabilities_and_type_mapping_roundtrip() -> None:
    api = _make_synapse_api()
    assert isinstance(api.capabilities, BackendCapabilities)
    assert api.capabilities == SYNAPSE_CAPABILITIES
    assert api.max_decimal_precision() == 38
    assert api.max_decimal_scale() == 38
    assert api.max_table_name_length() == 128

    canonical_dec = ColumnSpec(
        ColumnDialect.CANONICAL,
        "PRICE",
        GOE_TYPE_DECIMAL,
        data_precision=18,
        data_scale=4,
    )
    syn_col = api.from_canonical_column(canonical_dec)
    assert syn_col.dialect is ColumnDialect.SYNAPSE
    assert syn_col.data_type == SYNAPSE_TYPE_NUMERIC
    assert syn_col.data_precision == 18
    assert syn_col.data_scale == 4

    round_trip = api.to_canonical_column(syn_col)
    assert round_trip.dialect is ColumnDialect.CANONICAL
    assert round_trip.data_type == GOE_TYPE_DECIMAL
    assert round_trip.data_precision == 18
    assert round_trip.data_scale == 4


def test_synapse_catalog_cache_and_write_through_invalidation() -> None:
    api = _make_synapse_api(dry_run=False)
    col = ColumnSpec(ColumnDialect.SYNAPSE, "ID", SYNAPSE_TYPE_BIGINT)
    api.execute_ddl = MagicMock(return_value=["DDL"])
    api._fetch_table_exists = MagicMock(return_value=True)
    api._fetch_columns = MagicMock(return_value=[col])
    api._fetch_table_size_and_row_count = MagicMock(return_value=(16384, 500))

    assert api.table_exists("dbo", "SALES") is True
    assert api.table_exists("dbo", "SALES") is True
    assert api._fetch_table_exists.call_count == 1

    assert api.get_columns("dbo", "SALES") == [col]
    assert api.get_columns("dbo", "SALES") == [col]
    assert api._fetch_columns.call_count == 1

    assert api.get_table_size("dbo", "SALES") == 16384
    assert api.get_table_row_count_from_metadata("dbo", "SALES") == 500
    assert api._fetch_table_size_and_row_count.call_count == 1

    api.add_columns("dbo", "SALES", [("EXTRA", "VARCHAR(50)")])
    assert api.get_columns("dbo", "SALES") == [col]
    assert api._fetch_columns.call_count == 2

    api._fetch_table_exists.return_value = False
    api.drop_table("dbo", "SALES", if_exists=False)
    assert api.table_exists("dbo", "SALES") is False
    assert api._fetch_table_exists.call_count == 2


def test_synapse_warm_schema_two_queries() -> None:
    api = _make_synapse_api(dry_run=False)
    queries: list[tuple[str, list]] = []

    def _fake_fetch_all(sql: str, log_level=None, query_params=None, **kwargs):
        queries.append((sql, list(query_params or [])))
        if "information_schema.tables" in sql.lower():
            return [
                ("SALES", "BASE TABLE"),
                ("SALES_V", "VIEW"),
            ]
        return [
            ("SALES", "ID", "bigint", "NO", None, None, 19, 0, None, None),
            ("SALES", "NAME", "varchar", "YES", 100, 100, None, None, None, "SQL_Latin1_General_CP1_CI_AS"),
        ]

    api.execute_query_fetch_all = _fake_fetch_all
    api._fetch_table_exists = MagicMock(side_effect=AssertionError("Should hit warmed cache"))
    api._fetch_columns = MagicMock(side_effect=AssertionError("Should hit warmed cache"))

    warmed = api.warm_schema("dbo")
    assert warmed == 2
    assert len(queries) == 2
    assert api.table_exists("dbo", "SALES") is True
    assert api.table_exists("dbo", "SALES_V") is False
    cols = api.get_columns("dbo", "SALES")
    assert [c.name for c in cols] == ["ID", "NAME"]


def test_synapse_table_create_distribution_and_staged_ingest() -> None:
    table = _make_synapse_table()
    cols = [
        ColumnSpec(ColumnDialect.SYNAPSE, "CUST_ID", SYNAPSE_TYPE_BIGINT),
        ColumnSpec(ColumnDialect.SYNAPSE, "NAME", SYNAPSE_TYPE_VARCHAR, data_length=100, char_length=100),
    ]
    table.set_columns(cols)
    table._bucket_hash_col = "CUST_ID"
    table._sort_columns = ["CUST_ID"]
    table._offload_stats_method = OFFLOAD_STATS_METHOD_NATIVE

    ddl_cmds = table.create_backend_table()
    assert any("DISTRIBUTION=HASH([CUST_ID])" in cmd for cmd in ddl_cmds)
    assert any("CLUSTERED COLUMNSTORE INDEX ORDER ([CUST_ID])" in cmd for cmd in ddl_cmds)

    rdbms_cols = [
        ColumnSpec(ColumnDialect.CANONICAL, "CUST_ID", GOE_TYPE_INTEGER_8),
        ColumnSpec(ColumnDialect.CANONICAL, "NAME", GOE_TYPE_VARIABLE_STRING, data_length=100),
    ]
    staging_cols = [
        ColumnSpec(ColumnDialect.SYNAPSE, "CUST_ID", SYNAPSE_TYPE_BIGINT),
        ColumnSpec(ColumnDialect.SYNAPSE, "NAME", SYNAPSE_TYPE_VARCHAR, data_length=100),
    ]
    table.set_final_table_casts(rdbms_cols, staging_cols)
    executed_dml: list = []
    table._execute_dml = lambda sqls, **kwargs: executed_dml.extend(sqls) or sqls
    table.load_final_table()
    assert len(executed_dml) == 1
    assert "INSERT INTO [d].[dbo].[SALES]" in executed_dml[0]


def _make_synapse_api(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_SYNAPSE_ENV)
    if config.synapse_database is None:
        config.synapse_database = "SYNAPSE_DB"
    return create_backend_api(
        DBTYPE_SYNAPSE,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )


def _make_synapse_table(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_SYNAPSE_ENV)
    if config.synapse_database is None:
        config.synapse_database = "SYNAPSE_DB"
    return create_backend_table(
        "dbo",
        "SALES",
        DBTYPE_SYNAPSE,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )
