# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe.persistence.oracle_gateway."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock

import msgspec
import pytest

from goe.persistence.oracle_gateway import (
    OracleGateway,
    load_sql_file,
    rows_as_dicts,
    validate_oracle_identifier,
)

SQL_TEXT = """-- name: get_step
SELECT CS.CODE AS STEP_CODE,
       CES.START_TIME AS STARTED_AT
FROM   {repo_user}.COMMAND_STEP CS
WHERE  CS.ID = :step_id;

-- name: get_codes
SELECT code FROM {repo_user}.command_step ORDER BY 1;

-- name: get_unresolved
SELECT 1 FROM {missing_slot}.t;
"""


class StepRow(msgspec.Struct, kw_only=True):
    """Row model used to verify struct hydration."""

    step_code: str
    started_at: datetime.datetime | None


@pytest.fixture
def loader(tmp_path: Path):
    sql_file = tmp_path / "gateway_test.sql"
    sql_file.write_text(SQL_TEXT)
    return load_sql_file(sql_file)


def test_validate_oracle_identifier_accepts_and_uppercases() -> None:
    assert validate_oracle_identifier("goe_repo") == "GOE_REPO"
    assert validate_oracle_identifier("c##goe$adm_1") == "C##GOE$ADM_1"
    assert validate_oracle_identifier('"GOE_REPO"') == "GOE_REPO"


@pytest.mark.parametrize("bad", ["GOE_REPO; DROP TABLE dual", "GOE..REPO", "", "1GOE", "GOE REPO", 'GOE"REPO'])
def test_validate_oracle_identifier_rejects_injection(bad: str) -> None:
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        validate_oracle_identifier(bad)


def test_load_sql_file_registers_named_statements(loader) -> None:
    assert {"get_step", "get_codes", "get_unresolved"} <= set(loader.list_queries())


def test_statement_text_substitutes_slots_and_keeps_binds(loader) -> None:
    gateway = OracleGateway(lambda: None, loader, slots={"repo_user": "goe_repo"})
    text = gateway.statement_text("get_step")
    assert "GOE_REPO.COMMAND_STEP" in text
    assert ":step_id" in text
    assert not text.endswith(";")


def test_statement_text_rejects_unresolved_slot(loader) -> None:
    gateway = OracleGateway(lambda: None, loader, slots={"repo_user": "GOE_REPO"})
    with pytest.raises(ValueError, match="Unresolved SQL slots"):
        gateway.statement_text("get_unresolved")


def test_statement_text_rejects_invalid_slot_value(loader) -> None:
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        OracleGateway(lambda: None, loader, slots={"repo_user": "X; DROP TABLE Y"})


def test_select_returns_lowercase_dicts_and_passes_named_binds(loader) -> None:
    connection, cursor = _connection(["STEP_CODE", "STARTED_AT"], [("OFFLOAD", datetime.datetime(2026, 1, 1))])
    gateway = OracleGateway(lambda: connection, loader, slots={"repo_user": "GOE_REPO"})
    rows = gateway.select("get_step", {"step_id": 7})
    assert rows == [{"step_code": "OFFLOAD", "started_at": datetime.datetime(2026, 1, 1)}]
    sent_sql, sent_binds = cursor.execute.call_args.args
    assert _normalized(sent_sql) == _normalized(gateway.statement_text("get_step"))
    assert sent_binds == {"step_id": 7}


def test_select_structs_hydrates_msgspec_rows(loader) -> None:
    connection, _ = _connection(["STEP_CODE", "STARTED_AT"], [("OFFLOAD", None)])
    gateway = OracleGateway(lambda: connection, loader, slots={"repo_user": "GOE_REPO"})
    assert gateway.select_structs("get_step", StepRow, {"step_id": 7}) == [
        StepRow(step_code="OFFLOAD", started_at=None)
    ]


def test_select_tuples_preserves_projection_order(loader) -> None:
    connection, _ = _connection(["CODE"], [("A",), ("B",)])
    gateway = OracleGateway(lambda: connection, loader, slots={"repo_user": "GOE_REPO"})
    assert gateway.select_tuples("get_codes") == [("A",), ("B",)]


def test_select_rejects_positional_binds(loader) -> None:
    connection, _ = _connection(["CODE"], [])
    gateway = OracleGateway(lambda: connection, loader, slots={"repo_user": "GOE_REPO"})
    with pytest.raises(TypeError, match="named binds"):
        gateway.select("get_step", (7,))


def test_select_without_connection_returns_none(loader) -> None:
    gateway = OracleGateway(lambda: None, loader, slots={"repo_user": "GOE_REPO"})
    assert gateway.select("get_codes") is None
    assert gateway.select_tuples("get_codes") is None
    assert gateway.select_structs("get_step", StepRow, {"step_id": 1}) is None


def test_new_out_var_allocates_on_provider_connection(loader) -> None:
    connection, cursor = _connection([], [])
    gateway = OracleGateway(lambda: connection, loader)
    out_var = gateway.new_out_var(int)
    cursor.var.assert_called_once_with(int)
    assert out_var is cursor.var.return_value


def test_rows_as_dicts_preserves_column_case() -> None:
    assert rows_as_dicts(["OFFLOADED_OWNER", "x"], [("SH", 1)]) == [{"OFFLOADED_OWNER": "SH", "x": 1}]


def _connection(column_names: list[str], rows: list[tuple]) -> tuple[MagicMock, MagicMock]:
    cursor = MagicMock()
    cursor.description = [(name, None, None, None, None, None, None) for name in column_names]
    cursor.fetchall.return_value = rows
    connection = MagicMock()
    connection.cursor.return_value = cursor
    return connection, cursor


def _normalized(sql: str) -> str:
    return " ".join(sql.split())
