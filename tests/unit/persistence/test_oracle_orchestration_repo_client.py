# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Characterization tests for OracleOrchestrationRepoClient repository queries and OUT binds."""

import datetime
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import goe.persistence
from goe.offload.factory.frontend_api_factory import frontend_api_factory
from goe.offload.offload_constants import DBTYPE_ORACLE
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.oracle.oracle_orchestration_repo_client import OracleOrchestrationRepoClient
from goe.persistence.oracle_gateway import OracleGateway, load_sql_file
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options

ORACLE_REPO_SQL = Path(goe.persistence.__file__).resolve().parent / "sql" / "oracle_repo.sql"
EXEC_ID = ExecutionId()
STARTED = datetime.datetime(2026, 1, 1, 12, 0, 0)
LEGACY_USER_CLAUSE = re.compile(r"owner not in \(upper\('a'\),upper\('a'\),upper\('a'\)\)")
BIND_USER_CLAUSE = "owner not in (upper(:adm_user), upper(:app_user), upper(:repo_user))"
SCHEMA_TABLE_SLOTS = {
    "unsupported_col_name": "unsupported_col_name_2",
    "unsupported_col_name_count": "unsupported_col_name_2_count",
}

EXECUTION_COLUMNS = [
    "EXECUTION_ID",
    "COMMAND_TYPE_CODE",
    "COMMAND_TYPE",
    "STATUS_CODE",
    "STATUS",
    "STARTED_AT",
    "COMPLETED_AT",
    "COMMAND_LOG_PATH",
    "COMMAND_INPUT",
    "COMMAND_PARAMETERS",
    "GOE_VERSION",
    "GOE_BUILD",
]
EXECUTION_ROW = (
    EXEC_ID.as_bytes(),
    "OFFLOAD",
    "Offload",
    "SUCCESS",
    "Success",
    STARTED,
    None,
    "/tmp/offload.log",
    "offload -t SH.SALES",
    '{"owner_table": "SH.SALES"}',
    "1.0.0",
    "abc123",
)
STEP_COLUMNS = [
    "EXECUTION_ID",
    "STEP_ID",
    "STEP_CODE",
    "STEP_TITLE",
    "STEP_STATUS_CODE",
    "STEP_STATUS",
    "STARTED_AT",
    "COMPLETED_AT",
    "STEP_DETAILS",
]
STEP_ROW = (EXEC_ID.as_bytes(), 7, "VERIFY", "Verify exported data", "SUCCESS", "Success", STARTED, None, None)
SCHEMA_TABLE_COLUMNS = [
    "TABLE_NAME",
    "TABLE_SIZE_IN_BYTES",
    "TABLE_OFFLOADED_SIZE_IN_BYTES",
    "TABLE_RECLAIMED_SIZE_IN_BYTES",
    "ESTIMATED_ROW_COUNT",
    "STATISTICS_LAST_GATHERED_ON",
    "PARTITIONING_TYPE",
    "SUBPARTITIONING_TYPE",
    "TABLE_COMPRESSION",
    "TABLE_COMPRESS_FOR",
    "IS_OFFLOADED",
    "IS_PARTITIONED",
    "IS_SUBPARTITIONED",
    "IS_COMPRESSED",
    "IS_OFFLOADABLE",
    "REASON_NOT_OFFLOADABLE",
]
SCHEMA_TABLE_ROW = (
    "SALES",
    65536,
    None,
    None,
    1000,
    STARTED,
    "RANGE",
    None,
    "DISABLED",
    None,
    "False",
    "True",
    "False",
    "False",
    "True",
    None,
)


CASES = [
    (
        "get_offloadable_schemas",
        lambda c: c.get_offloadable_schemas(),
        ["SCHEMA_NAME", "HYBRID_SCHEMA_EXISTS", "TABLE_COUNT", "SCHEMA_SIZE_IN_BYTES"],
        [("SH", "False", 12, 1048576)],
        [{"schema_name": "SH", "hybrid_schema_exists": "False", "table_count": 12, "schema_size_in_bytes": 1048576}],
        None,
    ),
    (
        "get_schema_tables",
        lambda c: c.get_schema_tables("SH"),
        SCHEMA_TABLE_COLUMNS,
        [SCHEMA_TABLE_ROW],
        [dict(zip([n.lower() for n in SCHEMA_TABLE_COLUMNS], SCHEMA_TABLE_ROW))],
        SCHEMA_TABLE_SLOTS,
    ),
    (
        "get_command_step_codes",
        lambda c: c.get_command_step_codes(),
        ["CODE"],
        [("OFFLOAD",), ("VERIFY",)],
        ["OFFLOAD", "VERIFY"],
        None,
    ),
    (
        "get_command_executions",
        lambda c: c.get_command_executions(),
        EXECUTION_COLUMNS,
        [EXECUTION_ROW],
        [dict(zip([n.lower() for n in EXECUTION_COLUMNS], EXECUTION_ROW))],
        None,
    ),
    (
        "get_command_execution",
        lambda c: c.get_command_execution(EXEC_ID),
        EXECUTION_COLUMNS,
        [EXECUTION_ROW],
        dict(zip([n.lower() for n in EXECUTION_COLUMNS], EXECUTION_ROW)),
        None,
    ),
    (
        "get_command_execution_steps_all",
        lambda c: c.get_command_execution_steps(None),
        STEP_COLUMNS,
        [STEP_ROW],
        [dict(zip([n.lower() for n in STEP_COLUMNS], STEP_ROW))],
        None,
    ),
    (
        "get_command_execution_steps_by_id",
        lambda c: c.get_command_execution_steps(EXEC_ID),
        STEP_COLUMNS,
        [STEP_ROW],
        [dict(zip([n.lower() for n in STEP_COLUMNS], STEP_ROW))],
        None,
    ),
]


@pytest.mark.parametrize(("name", "call", "columns", "rows", "expected", "slots"), CASES, ids=[c[0] for c in CASES])
def test_repository_query_results_and_sql(name, call, columns, rows, expected, slots) -> None:
    client, cursor = _client(columns, rows)
    assert call(client) == expected
    sent_sql = LEGACY_USER_CLAUSE.sub(BIND_USER_CLAUSE, _normalized(cursor.execute.call_args.args[0]))
    assert sent_sql == _normalized(_file_statement(name, slots))


@pytest.mark.parametrize("name", ["get_command_execution", "get_command_execution_steps_by_id"])
def test_execution_id_is_bound_as_raw_bytes(name) -> None:
    client, cursor = _client(EXECUTION_COLUMNS if name == "get_command_execution" else STEP_COLUMNS, [])
    if name == "get_command_execution":
        assert client.get_command_execution(EXEC_ID) is None
    else:
        assert client.get_command_execution_steps(EXEC_ID) == []
    assert cursor.execute.call_args.args[1] == {"execution_id": EXEC_ID.as_bytes()}


def test_get_schema_tables_binds_schema_name() -> None:
    client, cursor = _client(SCHEMA_TABLE_COLUMNS, [])
    assert client.get_schema_tables("SH") == []
    assert cursor.execute.call_args.args[1] == {"schema_name": "SH"}


def test_start_command_allocates_int_out_bind_and_returns_value() -> None:
    client, cursor = _client([], [])
    out_var = MagicMock()
    out_var.getvalue.return_value = 42
    cursor.var.return_value = out_var
    client._frontend_client.execute_function = MagicMock()
    client._messages.get_log_fh_name = MagicMock(return_value="/tmp/offload.log")
    assert client.start_command(EXEC_ID, "OFFLOAD", {"owner_table": "SH.SALES"}, {"a": 1}) == 42
    cursor.var.assert_called_with(int)
    arg_list = client._frontend_client.execute_function.call_args.kwargs["arg_list"]
    assert arg_list[0] == EXEC_ID.as_bytes()
    assert arg_list[-1] is out_var


def test_get_offloadable_schemas_binds_user_names() -> None:
    client, cursor = _client(["SCHEMA_NAME", "HYBRID_SCHEMA_EXISTS", "TABLE_COUNT", "SCHEMA_SIZE_IN_BYTES"], [])
    assert client.get_offloadable_schemas() == []
    assert cursor.execute.call_args.args[1] == {"adm_user": "a", "app_user": "a", "repo_user": "a"}
    assert "upper('a')" not in _normalized(cursor.execute.call_args.args[0])


def _normalized(sql: str) -> str:
    return " ".join(sql.split()).lower()


def _cursor(columns: list[str], rows: list[tuple]) -> MagicMock:
    cursor = MagicMock()
    cursor.description = [(name, None, None, None, None, None, None) for name in columns]
    cursor.rowfactory = None

    def fetchall() -> list:
        return [cursor.rowfactory(*row) for row in rows] if cursor.rowfactory else list(rows)

    cursor.fetchall.side_effect = fetchall
    cursor.fetchone.side_effect = lambda: (fetchall() or [None])[0]
    return cursor


def _client(columns: list[str], rows: list[tuple]) -> tuple[OracleOrchestrationRepoClient, MagicMock]:
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    api = frontend_api_factory(DBTYPE_ORACLE, config, messages, dry_run=True, do_not_connect=True)
    cursor = _cursor(columns, rows)
    api._db_conn = MagicMock()
    api._db_conn.cursor.return_value = cursor
    client = OracleOrchestrationRepoClient(config, messages, dry_run=True)
    client._frontend_client = api
    return client, cursor


def _file_statement(name: str, slots: dict[str, str] | None = None) -> str:
    gateway = OracleGateway(lambda: None, load_sql_file(ORACLE_REPO_SQL), slots={"repo_user": "a"})
    return gateway.statement_text(name, slots)
