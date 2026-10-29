# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Oracle lost-session retry policy."""

import sys

import oracledb
import pytest
from sqlspec.exceptions import DatabaseConnectionError, SQLSpecError

from goe.persistence.retry import is_lost_session_error, run_with_session_retry


@pytest.mark.parametrize(
    "message",
    [
        "ORA-00028: your session has been killed",
        "ORA-02396: exceeded maximum idle time",
        "DPI-1080: connection was closed by ORA-2396",
        "ORA-03113: end-of-file on communication channel",
        "ORA-3114: not connected to ORACLE",
        "ORA-03135: connection lost contact",
        "DPY-1001: not connected to database",
        "DPY-4011: the database or network closed the connection",
    ],
)
def test_is_lost_session_error_matches_codes(message: str) -> None:
    """Every killed, sniped, or disconnected Oracle code matches padded and unpadded."""
    assert is_lost_session_error(oracledb.DatabaseError(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "ORA-28000: the account is locked",
        "ORA-00942: table or view does not exist",
        "ORA-31130: unrelated",
        "DPY-10010: unrelated",
    ],
)
def test_is_lost_session_error_rejects_other_codes(message: str) -> None:
    """Non-disconnect Oracle codes and longer prefix codes do not match."""
    assert is_lost_session_error(oracledb.DatabaseError(message)) is False


def test_is_lost_session_error_follows_cause_chain() -> None:
    """SQLSpec wrapper exceptions match either via __cause__ or via embedded message."""
    wrapper = SQLSpecError("Oracle database error")
    wrapper.__cause__ = oracledb.DatabaseError("ORA-02396: exceeded maximum idle time")
    assert is_lost_session_error(wrapper) is True

    mapped = DatabaseConnectionError(
        "Oracle session has been killed [ORA-00028]: ORA-00028: your session has been killed"
    )
    assert is_lost_session_error(mapped) is True


def test_run_with_session_retry_returns_first_result() -> None:
    """Successful operations run once without calling on_retry."""
    calls: list[int] = []
    retries: list[BaseException] = []

    def operation() -> int:
        calls.append(1)
        return 42

    assert run_with_session_retry(operation, on_retry=retries.append) == 42
    assert len(calls) == 1
    assert retries == []


def test_run_with_session_retry_retries_once_outside_except() -> None:
    """Lost-session errors trigger one retry after exiting the except block."""
    attempts = 0
    active_exceptions: list[BaseException | None] = []
    retries: list[BaseException] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        active_exceptions.append(sys.exception())
        if attempts == 1:
            raise oracledb.DatabaseError("ORA-03113: end-of-file on communication channel")
        return "ok"

    result = run_with_session_retry(operation, on_retry=retries.append)
    assert result == "ok"
    assert attempts == 2
    assert active_exceptions == [None, None]
    assert len(retries) == 1
    assert "ORA-03113" in str(retries[0])


def test_run_with_session_retry_reraises_other_errors() -> None:
    """Non-disconnect errors propagate immediately without retry."""
    calls: list[int] = []
    retries: list[BaseException] = []

    def operation() -> None:
        calls.append(1)
        raise oracledb.DatabaseError("ORA-00942: table or view does not exist")

    with pytest.raises(oracledb.DatabaseError, match="ORA-00942"):
        run_with_session_retry(operation, on_retry=retries.append)

    assert len(calls) == 1
    assert retries == []


def test_run_with_session_retry_second_failure_is_not_chained() -> None:
    """A failure on the second attempt propagates without __context__ chaining."""
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise oracledb.DatabaseError(f"ORA-03113: end-of-file attempt {attempts}")

    with pytest.raises(oracledb.DatabaseError, match="attempt 2") as excinfo:
        run_with_session_retry(operation)

    assert excinfo.value.__context__ is None
