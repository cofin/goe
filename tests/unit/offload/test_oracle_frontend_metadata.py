# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Characterization and behavior tests for OracleFrontendApi data-dictionary queries and pooled lease lifecycle."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import oracledb
import pytest

import goe.offload.oracle
import goe.persistence.registry as registry_module
from goe.offload.offload_constants import DBTYPE_ORACLE
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_frontend_api
from goe.persistence.registry import OracleConnectionSettings, OracleDatabaseRegistry
from goe.persistence.statements import NamedStatements
from tests.unit.test_functions import FAKE_ORACLE_ENV, build_mock_options

FRONTEND_METADATA_SQL = Path(goe.offload.oracle.__file__).resolve().parent / "sql" / "frontend_metadata.sql"
_STATEMENTS = NamedStatements(FRONTEND_METADATA_SQL)
EXPECTED_SQL: dict[str, str] = {name: _STATEMENTS.text(name) for name in _STATEMENTS.names()}

OWNER_TABLE = {"owner": "SH", "table_name": "SALES"}

CASES = [
    (
        "get_partition_column_names",
        lambda api: api.get_partition_column_names("SH", "SALES"),
        ["UPPER(PK.COLUMN_NAME)"],
        [("TIME_ID",)],
        ["TIME_ID"],
        OWNER_TABLE,
    ),
    (
        "get_subpartition_column_names",
        lambda api: api.get_subpartition_column_names("SH", "SALES"),
        ["UPPER(PK.COLUMN_NAME)"],
        [("CHANNEL_ID",)],
        ["CHANNEL_ID"],
        OWNER_TABLE,
    ),
    (
        "get_session_events",
        lambda api: api._instrumentation_snap({"db file sequential read": 1.0}),
        ["EVENT", "ROUND(TIME_WAITED_MICRO/1E6,2)"],
        [("db file sequential read", 3.5)],
        None,
        None,
    ),
    (
        "get_iot_type",
        lambda api: api._is_iot("SH", "SALES"),
        ["IOT_TYPE"],
        [("IOT",)],
        True,
        OWNER_TABLE,
    ),
    (
        "agg_validate_sample_column_names",
        lambda api: api.agg_validate_sample_column_names("SH", "SALES", num_required=5),
        ["COLUMN_NAME"],
        [("PROD_ID",), ("AMOUNT",)],
        ["PROD_ID", "AMOUNT"],
        {**OWNER_TABLE, "required_no": 5},
    ),
    ("get_current_scn", lambda api: api.get_current_scn(), ["CURRENT_SCN"], [(123456,)], 123456, None),
    (
        "get_db_unique_name",
        lambda api: api.get_db_unique_name(),
        ["DB_UNIQUE_NAME"],
        [("ORCL_PDB1",)],
        "ORCL_PDB1",
        None,
    ),
    (
        "get_primary_key_column_names",
        lambda api: api.get_primary_key_column_names("SH", "SALES"),
        ["COLUMN_NAME"],
        [("ID",)],
        ["ID"],
        OWNER_TABLE,
    ),
    ("get_session_user", lambda api: api.get_session_user(), ["SESSION_USER"], [("GOE_ADM",)], "GOE_ADM", None),
    (
        "get_table_default_parallelism",
        lambda api: api.get_table_default_parallelism("SH", "SALES"),
        ["DEGREE"],
        [("4",)],
        "4",
        OWNER_TABLE,
    ),
    ("schema_exists", lambda api: api.schema_exists("SH"), ["ONE"], [(1,)], True, {"schema": "SH"}),
    ("table_exists", lambda api: api.table_exists("SH", "SALES"), ["TABLE_NAME"], [("SALES",)], True, OWNER_TABLE),
    (
        "view_exists",
        lambda api: api.view_exists("SH", "V_SALES"),
        ["ONE"],
        [],
        False,
        {"owner": "SH", "view_name": "V_SALES"},
    ),
]


class FakePool:
    """In-memory stand-in for an oracledb synchronous connection pool."""

    def __init__(self, column_names: list[str] | None = None, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.column_names = column_names or []
        self.rows = rows or []
        self.acquired: list[MagicMock] = []
        self.released: list[MagicMock] = []
        self.dropped: list[MagicMock] = []

    def acquire(self) -> MagicMock:
        """Acquire a mock connection configured with ``column_names`` and ``rows``."""
        conn, _ = _build_connection(self.column_names, self.rows)
        self.acquired.append(conn)
        return conn

    def release(self, conn: MagicMock) -> None:
        """Release a mock connection."""
        self.released.append(conn)

    def drop(self, conn: MagicMock) -> None:
        """Drop a mock connection."""
        self.dropped.append(conn)

    def close(self, *args: Any, **kwargs: Any) -> None:
        """No-op pool close."""
        del args, kwargs


@pytest.fixture(autouse=True)
def clear_registries() -> Iterator[None]:
    """Ensure registry cache is cleared around each test."""
    OracleDatabaseRegistry.close_all()
    yield
    OracleDatabaseRegistry.close_all()


@pytest.fixture
def api():
    """Return a non-connecting OracleFrontendApi instance."""
    return create_frontend_api(
        DBTYPE_ORACLE,
        build_mock_options(FAKE_ORACLE_ENV),
        OffloadMessages(),
        dry_run=True,
        do_not_connect=True,
        trace_action="TestOracleFrontendMetadata",
    )


@pytest.mark.parametrize(("name", "call", "columns", "rows", "expected", "binds"), CASES, ids=[c[0] for c in CASES])
def test_dictionary_query_results_sql_and_binds(api, name, call, columns, rows, expected, binds) -> None:
    """Every data-dictionary statement emits the expected SQL and binds."""
    cursor = _attach_connection(api, columns, rows)
    result = call(api)
    if expected is not None:
        assert result == expected
    sent = cursor.execute.call_args.args
    assert _normalized(sent[0]) == _normalized(EXPECTED_SQL[name])
    sent_binds = {k.lower(): v for k, v in (sent[1] if len(sent) > 1 else {}).items()}
    assert sent_binds == (binds or {})


def test_get_columns_builds_oracle_columns(api) -> None:
    """get_columns hydrates OracleColumn instances from the query projection."""
    cursor = _attach_connection(
        api,
        [
            "UPPER(COLUMN_NAME)",
            "COLUMN_ID",
            "NULLABLE",
            "DATA_TYPE",
            "DATA_PRECISION",
            "DATA_SCALE",
            "BYTE_LENGTH",
            "DATA_DEFAULT",
            "HIDDEN_COLUMN",
            "CHAR_USED",
            "CHAR_LENGTH",
        ],
        [("ID", 1, "N", "NUMBER", 10, 0, 22, None, "NO", "B", 0)],
    )
    columns = api.get_columns("SH", "SALES")
    assert [(c.name, c.data_type, c.nullable, c.data_precision) for c in columns] == [("ID", "NUMBER", False, 10)]
    assert _normalized(cursor.execute.call_args.args[0]) == _normalized(EXPECTED_SQL["get_columns"])


@pytest.mark.parametrize(("iot_rows", "size_name"), [([("IOT",)], "get_iot_table_size"), ([(None,)], "get_table_size")])
def test_get_table_size_selects_iot_or_heap_statement(api, iot_rows, size_name) -> None:
    """get_table_size dispatches to the IOT or heap segment size statement."""
    cursor = _attach_connection(api, ["IOT_TYPE"], iot_rows)
    cursor.fetchall.side_effect = [iot_rows, [(65536,)]]
    cursor.fetchone.side_effect = [iot_rows[0], (65536,)]
    assert api.get_table_size("SH", "SALES") == 65536
    assert _normalized(cursor.execute.call_args.args[0]) == _normalized(EXPECTED_SQL[size_name])


def test_proxy_override_connects_with_admin_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy schema overrides authenticate as adm_user[schema] with the admin password."""
    recorded: list[dict[str, Any]] = []

    def fake_connect(**kwargs: Any) -> MagicMock:
        recorded.append(kwargs)
        return MagicMock()

    monkeypatch.setattr(registry_module.oracledb, "connect", fake_connect)
    config = build_mock_options({**FAKE_ORACLE_ENV, "ORA_ADM_PASS": "adm-secret", "ORA_APP_PASS": "app-secret"})
    proxy_api = create_frontend_api(
        DBTYPE_ORACLE,
        config,
        OffloadMessages(),
        conn_user_override="SH_H",
        dry_run=True,
    )
    try:
        assert len(recorded) == 1
        assert recorded[0]["user"] == "a[SH_H]"
        assert recorded[0]["password"] == "adm-secret"
    finally:
        proxy_api.close()


def test_distinct_values_encloses_partition_name(api) -> None:
    """get_distinct_column_values encloses the partition name in double quotes."""
    cursor = _attach_connection(api, ["TIME_ID"], [])
    api.get_distinct_column_values("SH", "SALES", "TIME_ID", partition_name="P_2011 Q1")
    assert 'PARTITION ("P_2011 Q1")' in cursor.execute.call_args.args[0]


def test_close_releases_lease(api) -> None:
    """close() releases the leased pooled connection and clears _db_conn."""
    pool = FakePool()
    api._registry = OracleDatabaseRegistry(OracleConnectionSettings.from_options(build_mock_options(FAKE_ORACLE_ENV)))
    api._registry.adm_config.connection_instance = pool
    api._connect()
    leased_conn = pool.acquired[0]
    api.close()
    assert pool.released == [leased_conn]
    assert api._db_conn is None


def test_application_override_leases_application_pool() -> None:
    """Passing the application user as conn_user_override leases from the application pool."""
    config = build_mock_options({**FAKE_ORACLE_ENV, "ORA_APP_USER": "GOE_APP"})
    app_api = create_frontend_api(
        DBTYPE_ORACLE,
        config,
        OffloadMessages(),
        conn_user_override="GOE_APP",
        dry_run=True,
        do_not_connect=True,
    )
    adm_pool = FakePool()
    app_pool = FakePool()
    app_api._registry = OracleDatabaseRegistry(OracleConnectionSettings.from_options(config))
    app_api._registry.adm_config.connection_instance = adm_pool
    app_api._registry.app_config.connection_instance = app_pool
    app_api._connect()
    assert len(app_pool.acquired) == 1
    assert adm_pool.acquired == []
    assert app_api._lease_role == "app"
    app_api.close()


def test_named_statement_issues_no_alter_session(api) -> None:
    """Executing a named statement does not emit per-cursor ALTER SESSION commands."""
    cursor = _attach_connection(api, ["CURRENT_SCN"], [(123456,)])
    assert api.get_current_scn() == 123456
    for call in cursor.execute.call_args_list:
        assert not str(call.args[0]).lstrip().upper().startswith("ALTER SESSION")


def test_idle_lease_is_pinged_and_renewed(api) -> None:
    """An idle lease whose ping fails with a lost-session error is dropped and renewed."""
    pool = FakePool(["CURRENT_SCN"], [(999,)])
    api._registry = OracleDatabaseRegistry(OracleConnectionSettings.from_options(build_mock_options(FAKE_ORACLE_ENV)))
    api._registry.adm_config.connection_instance = pool
    api._connect()
    first_conn = pool.acquired[0]
    first_conn.ping.side_effect = oracledb.DatabaseError("ORA-02396: exceeded maximum idle time")
    api._last_used = 0.0
    assert api.get_current_scn() == 999
    assert pool.dropped == [first_conn]
    assert len(pool.acquired) == 2


def test_named_statement_retries_after_lost_session(api) -> None:
    """A named statement that fails with a lost-session error drops the lease and retries once."""
    pool = FakePool(["SESSION_USER"], [("GOE_ADM",)])
    api._registry = OracleDatabaseRegistry(OracleConnectionSettings.from_options(build_mock_options(FAKE_ORACLE_ENV)))
    api._registry.adm_config.connection_instance = pool
    api._connect()
    first_conn = pool.acquired[0]
    first_conn.cursor.return_value.execute.side_effect = oracledb.DatabaseError(
        "ORA-03113: end-of-file on communication channel"
    )
    assert api.get_session_user() == "GOE_ADM"
    assert pool.dropped == [first_conn]
    assert len(pool.acquired) == 2


def _normalized(sql: str) -> str:
    return " ".join(sql.split()).lower()


def _build_connection(column_names: list[str], rows: list[tuple[Any, ...]]) -> tuple[MagicMock, MagicMock]:
    cursor = MagicMock()
    cursor.description = [(name, None, None, None, None, None, None) for name in column_names]
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = rows[0] if rows else None
    connection = MagicMock()
    connection.cursor.return_value = cursor
    return connection, cursor


def _attach_connection(api, column_names: list[str], rows: list[tuple[Any, ...]]) -> MagicMock:
    connection, cursor = _build_connection(column_names, rows)
    api._registry = OracleDatabaseRegistry(OracleConnectionSettings.from_options(build_mock_options(FAKE_ORACLE_ENV)))
    api._lease_role = None
    api._db_conn = connection
    return cursor
