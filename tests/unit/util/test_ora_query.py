# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Characterization tests for OracleQuery row projection."""

from unittest.mock import MagicMock

from goe.util.ora_query import OracleQuery


def test_execute_as_dict_preserves_column_name_case() -> None:
    cursor = _cursor()
    rows = OracleQuery.fromcursor(cursor).execute(
        "SELECT offloaded_owner, offloaded_table FROM t WHERE x = :x",
        binds={"x": 1},
        cursor_fn=lambda c: c.fetchall(),
        as_dict=True,
    )
    assert rows == [
        {"OFFLOADED_OWNER": "SH", "offloaded_table": "SALES"},
        {"OFFLOADED_OWNER": "SH", "offloaded_table": "COSTS"},
    ]
    cursor.execute.assert_called_once_with("SELECT offloaded_owner, offloaded_table FROM t WHERE x = :x", {"x": 1})


def test_execute_passthrough_returns_cursor_fn_result() -> None:
    cursor = _cursor()
    rows = OracleQuery.fromcursor(cursor).execute("SELECT 1 FROM dual", cursor_fn=lambda c: c.fetchall())
    assert rows == [("SH", "SALES"), ("SH", "COSTS")]


def _cursor() -> MagicMock:
    cursor = MagicMock()
    cursor.description = [
        ("OFFLOADED_OWNER", None, None, None, None, None, None),
        ("offloaded_table", None, None, None, None, None, None),
    ]
    cursor.fetchall.return_value = [("SH", "SALES"), ("SH", "COSTS")]
    return cursor
