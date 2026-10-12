# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Characterization tests for OracleFrontendApi data-dictionary queries and reconnect handling."""

from pathlib import Path
from unittest.mock import MagicMock

import oracledb as cxo
import pytest

import goe.offload.oracle
from goe.offload.factory.frontend_api_factory import frontend_api_factory
from goe.offload.offload_constants import DBTYPE_ORACLE
from goe.offload.offload_messages import OffloadMessages
from goe.persistence.oracle_gateway import OracleGateway, load_sql_file
from tests.unit.test_functions import FAKE_ORACLE_ENV, build_mock_options

FRONTEND_METADATA_SQL = Path(goe.offload.oracle.__file__).resolve().parent / "sql" / "frontend_metadata.sql"
_STATEMENT_GATEWAY = OracleGateway(lambda: None, load_sql_file(FRONTEND_METADATA_SQL))
EXPECTED_SQL: dict[str, str] = {
    name: _STATEMENT_GATEWAY.statement_text(name) for name in load_sql_file(FRONTEND_METADATA_SQL).list_queries()
}

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


@pytest.fixture
def api():
    return frontend_api_factory(
        DBTYPE_ORACLE,
        build_mock_options(FAKE_ORACLE_ENV),
        OffloadMessages(),
        dry_run=True,
        do_not_connect=True,
        trace_action="TestOracleFrontendMetadata",
    )


@pytest.mark.parametrize(("name", "call", "columns", "rows", "expected", "binds"), CASES, ids=[c[0] for c in CASES])
def test_dictionary_query_results_sql_and_binds(api, name, call, columns, rows, expected, binds) -> None:
    cursor = _attach_connection(api, columns, rows)
    result = call(api)
    if expected is not None:
        assert result == expected
    sent = cursor.execute.call_args.args
    assert _normalized(sent[0]) == _normalized(EXPECTED_SQL[name])
    sent_binds = {k.lower(): v for k, v in (sent[1] if len(sent) > 1 else {}).items()}
    assert sent_binds == (binds or {})


def test_get_columns_builds_oracle_columns(api) -> None:
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
    cursor = _attach_connection(api, ["IOT_TYPE"], iot_rows)
    cursor.fetchall.side_effect = [iot_rows, [(65536,)]]
    cursor.fetchone.side_effect = [iot_rows[0], (65536,)]
    assert api.get_table_size("SH", "SALES") == 65536
    assert _normalized(cursor.execute.call_args.args[0]) == _normalized(EXPECTED_SQL[size_name])


def test_open_cursor_reconnects_on_sniped_session(api) -> None:
    dead = MagicMock()
    dead.cursor.return_value.execute.side_effect = cxo.DatabaseError("DPI-1080: connection was closed by ORA-2396")
    live = MagicMock()
    api._db_conn = dead
    api._disconnect = MagicMock()
    api._connect = MagicMock(side_effect=lambda: setattr(api, "_db_conn", live))
    api._open_cursor()
    api._disconnect.assert_called_once_with(force=True)
    api._connect.assert_called_once_with()
    assert api._db_curs is live.cursor.return_value


def test_open_cursor_reraises_other_database_errors(api) -> None:
    broken = MagicMock()
    broken.cursor.return_value.execute.side_effect = cxo.DatabaseError("ORA-00942: table or view does not exist")
    api._db_conn = broken
    with pytest.raises(cxo.DatabaseError, match="ORA-00942"):
        api._open_cursor()


def test_failed_reconnect_is_not_chained(api) -> None:
    dead = MagicMock()
    dead.cursor.return_value.execute.side_effect = cxo.DatabaseError("ORA-03113: end-of-file on communication channel")
    api._db_conn = dead
    api._disconnect = MagicMock()
    api._connect = MagicMock(side_effect=RuntimeError("listener down"))
    with pytest.raises(RuntimeError, match="listener down") as excinfo:
        api._open_cursor()
    assert excinfo.value.__context__ is None


def test_get_validated_oracle_connection_tags_session(api) -> None:
    cursor = _attach_connection(api, [], [])
    assert api.get_validated_oracle_connection() is api._db_conn
    cursor.execute.assert_called_once_with('ALTER SESSION SET TRACEFILE_IDENTIFIER="GOE"')
    cursor.close.assert_called_once_with()


def test_get_validated_oracle_connection_without_connection(api) -> None:
    assert api.get_validated_oracle_connection() is None


def _normalized(sql: str) -> str:
    return " ".join(sql.split()).lower()


def _attach_connection(api, column_names: list[str], rows: list[tuple]) -> MagicMock:
    cursor = MagicMock()
    cursor.description = [(name, None, None, None, None, None, None) for name in column_names]
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = rows[0] if rows else None
    connection = MagicMock()
    connection.cursor.return_value = cursor
    api._db_conn = connection
    return cursor
