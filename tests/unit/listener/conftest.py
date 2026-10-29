# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared unit test doubles for the GOE Listener Oracle durable job store."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

import goe.listener.app as listener_app
from goe.listener.jobs.store import OracleJobStore

__all__ = (
    "FakeOracleConnection",
    "FakeOracleCursor",
    "make_fake_oracle_job_store",
    "make_fake_oracle_state",
)


class FakeOracleCursor:
    """In-memory stateful fake Oracle cursor implementing the job_queue.sql queries."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state
        self.rowcount = 0
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        """Execute a named Oracle job_queue.sql statement against the in-memory state."""
        lock: threading.RLock = self._state["lock"]
        with lock:
            self._state["executed"].append((sql, params))
            upper_sql = " ".join(sql.upper().split())
            self.rowcount = 0
            self._rows = []

            if "FROM ALL_TABLES" in upper_sql:
                self._rows = [(1 if self._state.get("tables_exist", True) else 0,)]
                return

            if "INSERT INTO GOE_LISTENER_JOBS" in upper_sql:
                assert params is not None
                table_key = params["table_key"]
                for existing in self._state["jobs"].values():
                    if existing["table_key"] == table_key and existing["status"] in ("PENDING", "CLAIMED", "RUNNING"):
                        raise RuntimeError(
                            "ORA-00001: unique constraint (GOE_REPO.GOE_LISTENER_JOBS_ACTIVE_TBL_UQ) violated"
                        )
                if table_key in self._state["active_tables"]:
                    raise RuntimeError(
                        "ORA-00001: unique constraint (GOE_REPO.GOE_LISTENER_JOBS_ACTIVE_TBL_UQ) violated"
                    )
                self._state["active_tables"][table_key] = params["execution_id"]
                self._state["jobs"][params["job_id"]] = {
                    "job_id": params["job_id"],
                    "execution_id": params["execution_id"],
                    "table_key": table_key,
                    "status": params["status"],
                    "payload_json": params["payload_json"],
                    "attempt": int(params["attempt"]),
                    "max_attempts": int(params["max_attempts"]),
                    "worker_id": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "started_at": None,
                    "finished_at": None,
                    "error_message": None,
                    "cancel_requested": 0,
                    "created_at": params["created_at"],
                    "updated_at": params["updated_at"],
                }
                self.rowcount = 1
                return

            if "FOR UPDATE SKIP LOCKED" in upper_sql:
                if self._state.get("pending_rows"):
                    self._rows = list(self._state["pending_rows"])
                    return
                pending = [
                    row
                    for row in self._state["jobs"].values()
                    if row["status"] == "PENDING" and int(row["cancel_requested"]) == 0
                ]
                pending.sort(key=lambda r: r["created_at"])
                self._rows = [_job_dict_to_row(r) for r in pending]
                return

            if "SET STATUS = 'CLAIMED'" in upper_sql:
                assert params is not None
                job = self._state["jobs"].get(params["job_id"])
                if job is not None and job["status"] == "PENDING":
                    job["status"] = "CLAIMED"
                    job["attempt"] = int(job["attempt"]) + 1
                    job["worker_id"] = params["worker_id"]
                    job["claimed_at"] = params["claimed_at"]
                    job["lease_expires_at"] = params["lease_expires_at"]
                    job["updated_at"] = params["updated_at"]
                    self.rowcount = 1
                elif self._state.get("pending_rows"):
                    self.rowcount = 1
                return

            if "SET STATUS = 'RUNNING'" in upper_sql:
                assert params is not None
                job = self._state["jobs"].get(params["job_id"])
                if (
                    job is not None
                    and job["worker_id"] == params["worker_id"]
                    and job["status"] in ("CLAIMED", "RUNNING")
                ):
                    job["status"] = "RUNNING"
                    if job["started_at"] is None:
                        job["started_at"] = params["started_at"]
                    job["lease_expires_at"] = params["lease_expires_at"]
                    job["updated_at"] = params["updated_at"]
                    self.rowcount = 1
                return

            if "SET LEASE_EXPIRES_AT = :LEASE_EXPIRES_AT" in upper_sql and "SET STATUS" not in upper_sql:
                assert params is not None
                job = self._state["jobs"].get(params["job_id"])
                if (
                    job is not None
                    and job["worker_id"] == params["worker_id"]
                    and job["status"] in ("CLAIMED", "RUNNING")
                ):
                    job["lease_expires_at"] = params["lease_expires_at"]
                    job["updated_at"] = params["updated_at"]
                    self.rowcount = 1
                return

            if "SET STATUS = :STATUS" in upper_sql:
                assert params is not None
                job = self._state["jobs"].get(params["job_id"])
                if (
                    job is not None
                    and job["worker_id"] == params["worker_id"]
                    and job["status"] in ("CLAIMED", "RUNNING")
                ):
                    job["status"] = params["status"]
                    job["lease_expires_at"] = None
                    job["finished_at"] = params["finished_at"]
                    job["error_message"] = params["error_message"]
                    job["updated_at"] = params["updated_at"]
                    self._state["active_tables"].pop(job["table_key"], None)
                    self.rowcount = 1
                return

            if "WHERE EXECUTION_ID = :EXECUTION_ID AND STATUS IN ('PENDING', 'CLAIMED')" in upper_sql:
                assert params is not None
                for job in self._state["jobs"].values():
                    if job["execution_id"] == params["execution_id"] and job["status"] in ("PENDING", "CLAIMED"):
                        job["status"] = "CANCELLED"
                        job["cancel_requested"] = 1
                        job["lease_expires_at"] = None
                        job["finished_at"] = params["now"]
                        job["error_message"] = (
                            params["error_message"] or job["error_message"] or "Cancelled by operator"
                        )
                        job["updated_at"] = params["now"]
                        self._state["active_tables"].pop(job["table_key"], None)
                        self.rowcount += 1
                return

            if "SET CANCEL_REQUESTED = 1" in upper_sql and "WHERE EXECUTION_ID = :EXECUTION_ID" in upper_sql:
                assert params is not None
                for job in self._state["jobs"].values():
                    if job["execution_id"] == params["execution_id"] and job["status"] == "RUNNING":
                        job["cancel_requested"] = 1
                        if params["error_message"] is not None:
                            job["error_message"] = params["error_message"]
                        job["updated_at"] = params["now"]
                        self.rowcount += 1
                return

            if "SET STATUS = 'CANCELLED', CANCEL_REQUESTED = 1" in upper_sql and "WHERE JOB_ID = :JOB_ID" in upper_sql:
                assert params is not None
                job = self._state["jobs"].get(params["job_id"])
                if (
                    job is not None
                    and job["worker_id"] == params["worker_id"]
                    and job["status"] in ("CLAIMED", "RUNNING")
                ):
                    job["status"] = "CANCELLED"
                    job["cancel_requested"] = 1
                    job["lease_expires_at"] = None
                    job["finished_at"] = params["finished_at"]
                    job["error_message"] = params["error_message"] or job["error_message"] or "Cancelled by operator"
                    job["updated_at"] = params["updated_at"]
                    self._state["active_tables"].pop(job["table_key"], None)
                    self.rowcount = 1
                return

            if "SET STATUS = 'CANCELLED'" in upper_sql and "AND CANCEL_REQUESTED = 1" in upper_sql:
                assert params is not None
                now: datetime = params["now"]
                for job in self._state["jobs"].values():
                    if (
                        job["status"] in ("CLAIMED", "RUNNING")
                        and int(job["cancel_requested"]) == 1
                        and job["lease_expires_at"] is not None
                        and job["lease_expires_at"] <= now
                    ):
                        job["status"] = "CANCELLED"
                        job["lease_expires_at"] = None
                        job["finished_at"] = now
                        job["error_message"] = job["error_message"] or "Job cancelled after lease expiration"
                        job["updated_at"] = now
                        self._state["active_tables"].pop(job["table_key"], None)
                        self.rowcount += 1
                return

            if "SET STATUS = 'PENDING'" in upper_sql and "AND ATTEMPT < MAX_ATTEMPTS" in upper_sql:
                assert params is not None
                now = params["now"]
                for job in self._state["jobs"].values():
                    if (
                        job["status"] in ("CLAIMED", "RUNNING")
                        and int(job["cancel_requested"]) == 0
                        and job["lease_expires_at"] is not None
                        and job["lease_expires_at"] <= now
                        and int(job["attempt"]) < int(job["max_attempts"])
                    ):
                        job["status"] = "PENDING"
                        job["worker_id"] = None
                        job["claimed_at"] = None
                        job["lease_expires_at"] = None
                        job["updated_at"] = now
                        self.rowcount += 1
                return

            if "SET STATUS = 'DEAD_LETTER'" in upper_sql and "AND ATTEMPT >= MAX_ATTEMPTS" in upper_sql:
                assert params is not None
                now = params["now"]
                for job in self._state["jobs"].values():
                    if (
                        job["status"] in ("CLAIMED", "RUNNING")
                        and int(job["cancel_requested"]) == 0
                        and job["lease_expires_at"] is not None
                        and job["lease_expires_at"] <= now
                        and int(job["attempt"]) >= int(job["max_attempts"])
                    ):
                        job["status"] = "DEAD_LETTER"
                        job["lease_expires_at"] = None
                        job["finished_at"] = now
                        job["error_message"] = job["error_message"] or "Job lease expired and max_attempts exhausted"
                        job["updated_at"] = now
                        self._state["active_tables"].pop(job["table_key"], None)
                        self.rowcount += 1
                return

            if "FROM GOE_LISTENER_JOBS WHERE EXECUTION_ID = :EXECUTION_ID" in upper_sql:
                assert params is not None
                matches = [
                    _job_dict_to_row(r)
                    for r in self._state["jobs"].values()
                    if r["execution_id"] == params["execution_id"]
                ]
                self._rows = matches
                return

            if "FROM GOE_LISTENER_JOBS WHERE TABLE_KEY = :TABLE_KEY" in upper_sql:
                assert params is not None
                matches = [
                    _job_dict_to_row(r)
                    for r in self._state["jobs"].values()
                    if r["table_key"] == params["table_key"] and r["status"] in ("PENDING", "CLAIMED", "RUNNING")
                ]
                self._rows = matches
                return

            if "FROM GOE_LISTENER_JOBS WHERE (:STATUS IS NULL OR STATUS = :STATUS)" in upper_sql:
                assert params is not None
                status_filter = params.get("status")
                matches_dicts = [
                    r for r in self._state["jobs"].values() if status_filter is None or r["status"] == status_filter
                ]
                matches_dicts.sort(key=lambda r: r["created_at"], reverse=True)
                self._rows = [_job_dict_to_row(r) for r in matches_dicts]
                return

            if "MERGE INTO GOE_LISTENER_ENDPOINTS" in upper_sql:
                assert params is not None
                self._state["heartbeats"][params["endpoint_id"]] = (
                    params["endpoint_id"],
                    params["listener_group_id"],
                    params["host_url"],
                    params["worker_role"],
                    params["updated_at"],
                    params["expires_at"],
                    params["version"],
                )
                self.rowcount = 1
                return

            if "FROM GOE_LISTENER_ENDPOINTS WHERE EXPIRES_AT > :NOW" in upper_sql:
                assert params is not None
                now = params["now"]
                hb_rows = [row for row in self._state["heartbeats"].values() if row[5] > now]
                hb_rows.sort(key=lambda row: str(row[0]))
                self._rows = hb_rows
                return

    def fetchmany(self, size: int = 1) -> list[tuple[Any, ...]]:
        """Return at most size rows and record the requested limit."""
        self._state["fetchmany_Grouping_limits"].append(size)
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def fetchone(self) -> tuple[Any, ...] | None:
        """Return the first row if available."""
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Return all remaining rows."""
        rows = list(self._rows)
        self._rows = []
        return rows

    def close(self) -> None:
        """No-op cursor close."""


class FakeOracleConnection:
    """In-memory fake Oracle connection."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state
        self.current_schema: str | None = None

    def cursor(self) -> FakeOracleCursor:
        """Return a fake cursor."""
        return FakeOracleCursor(self._state)

    def commit(self) -> None:
        """Record commit."""
        self._state["commits"] += 1

    def rollback(self) -> None:
        """Record rollback."""
        self._state["rollbacks"] += 1

    def close(self) -> None:
        """No-op connection close."""


def make_fake_oracle_state(*, pending_rows: list[tuple[Any, ...]] | None = None) -> dict[str, Any]:
    """Create a thread-safe in-memory state dictionary for FakeOracleConnection."""
    return {
        "lock": threading.RLock(),
        "executed": [],
        "fetchmany_Grouping_limits": [],
        "pending_rows": list(pending_rows) if pending_rows else [],
        "active_tables": {},
        "jobs": {},
        "heartbeats": {},
        "commits": 0,
        "rollbacks": 0,
        "tables_exist": True,
    }


def make_fake_oracle_job_store(state: dict[str, Any] | None = None) -> OracleJobStore:
    """Return an OracleJobStore wired to an in-memory FakeOracleConnection."""
    resolved_state = state if state is not None else make_fake_oracle_state()
    return OracleJobStore(
        connection_factory=lambda: FakeOracleConnection(resolved_state),
        repo_user="GOE_REPO",
    )


@pytest.fixture(autouse=True)
def _default_fake_oracle_job_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[OracleJobStore]:
    """Bind goe.listener.app._default_job_store to an in-memory OracleJobStore for unit tests."""
    store = make_fake_oracle_job_store()
    monkeypatch.setattr(listener_app, "_default_job_store", store)
    yield store


def _job_dict_to_row(job: dict[str, Any]) -> tuple[Any, ...]:
    return (
        job["job_id"],
        job["execution_id"],
        job["table_key"],
        job["status"],
        job["payload_json"],
        job["attempt"],
        job["max_attempts"],
        job["worker_id"],
        job["claimed_at"],
        job["lease_expires_at"],
        job["started_at"],
        job["finished_at"],
        job["error_message"],
        job["cancel_requested"],
        job["created_at"],
        job["updated_at"],
    )
