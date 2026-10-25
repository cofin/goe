# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for MSSQLFrontendApi on MssqlPythonConfig, named SQL, and FrontendCatalogCache."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from sqlspec.loader import SQLFileLoader

from goe.offload.frontend_cache import FrontendCatalogCache
from goe.offload.microsoft.mssql_column import MSSQLColumn
from goe.offload.microsoft.mssql_frontend_api import MSSQLFrontendApi
from goe.offload.offload_constants import DBTYPE_MSSQL


class _FakeDriverSession:
    """Fake MssqlPythonDriver session recording executed SQL and parameters."""

    def __init__(self, responses: dict[str, list[tuple[Any, ...]]] | None = None) -> None:
        self.executed: list[tuple[str, Any]] = []
        self._responses = responses or {}

    def select_value_or_none(self, sql: str, *params: Any) -> Any:
        rows = self._dispatch(sql, params)
        if not rows:
            return None
        return rows[0][0]

    def select_one_or_none(self, sql: str, *params: Any) -> Any:
        rows = self._dispatch(sql, params)
        return rows[0] if rows else None

    def select(self, sql: str, *params: Any) -> list[Any]:
        return self._dispatch(sql, params)

    def _dispatch(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        bind_params = params[0] if len(params) == 1 and isinstance(params[0], (tuple, list)) else params
        self.executed.append((sql, bind_params))
        for key, result in self._responses.items():
            if key in sql:
                return result
        return []


class _FakeMssqlConfig:
    """Fake MssqlPythonConfig yielding a _FakeDriverSession from provide_session."""

    def __init__(self, session: _FakeDriverSession) -> None:
        self._session = session

    @contextmanager
    def provide_session(self) -> Any:
        yield self._session


def test_mssql_catalog_sql_loads_all_named_queries_without_quoted_placeholders() -> None:
    sql_path = (
        Path(__file__).resolve().parents[4] / "src" / "goe" / "offload" / "microsoft" / "sql" / "mssql_catalog.sql"
    )
    assert sql_path.is_file()
    loader = SQLFileLoader()
    loader.load_sql(sql_path)

    expected_queries = (
        "fetch_server_version",
        "check_schema_exists",
        "check_table_exists",
        "check_view_exists",
        "fetch_table_columns",
        "fetch_primary_key_columns",
        "fetch_table_details",
        "fetch_table_size_bytes",
        "fetch_hash_bucket_candidate",
    )
    for query_name in expected_queries:
        assert loader.has_query(query_name)
        sql_text = loader.get_query_text(query_name)
        assert "'%s'" not in sql_text
        assert "%s" not in sql_text
        if query_name != "fetch_server_version":
            assert "?" in sql_text


def test_exists_queries_use_qmark_binds_without_quoted_percent_s() -> None:
    session = _FakeDriverSession(
        responses={
            "information_schema.schemata": [("sales",)],
            "BASE TABLE": [("orders",)],
            "VIEW": [("orders_v",)],
        }
    )
    options = SimpleNamespace(
        rdbms_dsn="server=sqlhost;port=1433;database=salesdb",
        rdbms_app_user="app_user",
        rdbms_app_pass="secret",
    )
    api = MSSQLFrontendApi(
        options,
        DBTYPE_MSSQL,
        MagicMock(),
        do_not_connect=True,
    )
    api._mssql_config = _FakeMssqlConfig(session)

    assert api.schema_exists("sales") is True
    assert api.table_exists("sales", "orders") is True
    assert api.view_exists("sales", "orders_v") is True

    assert len(session.executed) == 3
    schema_sql, schema_params = session.executed[0]
    assert "?" in schema_sql
    assert "'%s'" not in schema_sql
    assert schema_params == ("sales",)

    table_sql, table_params = session.executed[1]
    assert "?" in table_sql
    assert "'%s'" not in table_sql
    assert table_params == ("sales", "orders")

    view_sql, view_params = session.executed[2]
    assert "?" in view_sql
    assert "'%s'" not in view_sql
    assert view_params == ("sales", "orders_v")


def test_get_columns_and_table_size_use_named_catalog_sql_and_cache() -> None:
    session = _FakeDriverSession(
        responses={
            "sys.partitions": [(None, 250, "NO", None)],
            "sys.dm_db_partition_stats": [(65536,)],
            "information_schema.columns": [
                ("order_id", 1, "NO", "bigint", 19, 0, None, None, None, None),
                ("amount", 2, "YES", "decimal", 18, 2, None, None, None, None),
            ],
            "i.is_primary_key = 1": [("order_id",)],
            "sys.dm_db_stats_properties": [("order_id",)],
        }
    )
    options = SimpleNamespace(
        rdbms_dsn="server=sqlhost;port=1433;database=salesdb",
        rdbms_app_user="app_user",
        rdbms_app_pass="secret",
    )
    cache = FrontendCatalogCache(ttl_seconds=60.0)
    api = MSSQLFrontendApi(
        options,
        DBTYPE_MSSQL,
        MagicMock(),
        do_not_connect=True,
        catalog_cache=cache,
    )
    api._mssql_config = _FakeMssqlConfig(session)

    columns = api.get_columns("sales", "orders")
    assert len(columns) == 2
    assert all(isinstance(col, MSSQLColumn) for col in columns)
    assert [col.name for col in columns] == ["order_id", "amount"]

    first_query_count = len(session.executed)
    assert first_query_count > 0

    pk_cols = api.get_primary_key_column_names("sales", "orders")
    assert pk_cols == ["order_id"]

    size_bytes = api.get_table_size("sales", "orders")
    assert size_bytes == 65536

    snapshot = api.get_table_snapshot("sales", "orders")
    assert snapshot.num_rows == 250
    assert snapshot.hash_bucket_candidate == "order_id"
    assert len(session.executed) == first_query_count


def test_format_query_parameter_returns_qmark() -> None:
    options = SimpleNamespace(
        rdbms_dsn="server=sqlhost;port=1433;database=salesdb",
        rdbms_app_user="app_user",
        rdbms_app_pass="secret",
    )
    api = MSSQLFrontendApi(
        options,
        DBTYPE_MSSQL,
        MagicMock(),
        do_not_connect=True,
    )
    assert api.format_query_parameter("p1") == "?"
