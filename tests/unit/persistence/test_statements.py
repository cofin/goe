# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for NamedStatements, load_sql_file, and validate_oracle_identifier."""

from pathlib import Path

import pytest
from sqlspec.exceptions import SQLSlotError

from goe.persistence.statements import NamedStatements, load_sql_file, validate_oracle_identifier

SQL_TEXT = """-- name: get_step
SELECT CS.CODE AS STEP_CODE,
       CES.START_TIME AS STARTED_AT
FROM   /* slot: repo_user */.COMMAND_STEP CS
WHERE  CS.ID = :step_id;

-- name: get_codes
SELECT code, /* slot: column_slot */ AS col FROM /* slot: repo_user */.command_step ORDER BY 1;

-- name: get_unresolved
SELECT 1 FROM /* slot: missing_slot */.t;
"""


@pytest.fixture
def sql_path(tmp_path: Path) -> Path:
    """Write sample named statements to a temporary SQL file."""
    sql_file = tmp_path / "statements_test.sql"
    sql_file.write_text(SQL_TEXT)
    return sql_file


def test_validate_oracle_identifier_accepts_and_uppercases() -> None:
    """Valid unquoted and double-quoted identifiers are accepted and upper-cased."""
    assert validate_oracle_identifier("goe_repo") == "GOE_REPO"
    assert validate_oracle_identifier("c##goe$adm_1") == "C##GOE$ADM_1"
    assert validate_oracle_identifier('"GOE_REPO"') == "GOE_REPO"


@pytest.mark.parametrize("bad", ["GOE_REPO; DROP TABLE dual", "GOE..REPO", "", "1GOE", "GOE REPO", 'GOE"REPO'])
def test_validate_oracle_identifier_rejects_injection(bad: str) -> None:
    """Invalid identifier characters or leading digits raise ValueError."""
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        validate_oracle_identifier(bad)


def test_text_fills_slots_and_strips_semicolon(sql_path: Path) -> None:
    """text() fills declared slots, preserves binds, and strips the trailing semicolon."""
    loader = load_sql_file(sql_path)
    assert {"get_step", "get_codes", "get_unresolved"} <= set(loader.list_queries())
    statements = NamedStatements(sql_path, slots={"repo_user": "goe_repo"})
    assert {"get_step", "get_codes", "get_unresolved"} <= set(statements.names())
    text = statements.text("get_step")
    assert "GOE_REPO.COMMAND_STEP" in text
    assert ":step_id" in text
    assert not text.endswith(";")


def test_text_rejects_missing_slot(sql_path: Path) -> None:
    """text() raises SQLSlotError when a declared slot has no value."""
    statements = NamedStatements(sql_path, slots={"repo_user": "GOE_REPO"})
    with pytest.raises(SQLSlotError):
        statements.text("get_unresolved")


def test_text_rejects_invalid_slot_value(sql_path: Path) -> None:
    """NamedStatements validates slot values at construction time."""
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        NamedStatements(sql_path, slots={"repo_user": "X; DROP TABLE Y"})


def test_text_accepts_per_call_slots(sql_path: Path) -> None:
    """Per-call slots are validated, upper-cased, and merged with base slots."""
    statements = NamedStatements(sql_path, slots={"repo_user": "goe_repo"})
    text = statements.text("get_codes", {"column_slot": "unsupported_col_name_2"})
    assert "UNSUPPORTED_COL_NAME_2" in text
    assert "GOE_REPO.command_step" in text


def test_text_is_cached(sql_path: Path) -> None:
    """Repeated text() calls with the same slot arguments return the cached string instance."""
    statements = NamedStatements(sql_path, slots={"repo_user": "goe_repo"})
    first = statements.text("get_step")
    second = statements.text("get_step")
    assert first is second
