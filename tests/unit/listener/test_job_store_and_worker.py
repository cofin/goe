# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OracleJobStore, SqliteJobStore, and DurableJobWorker."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from goe.listener.jobs.models import JobRecord, JobState
from goe.listener.jobs.store import (
    DuplicateActiveTableJobError,
    OracleJobStore,
    SqliteJobStore,
    create_job_store,
)
from goe.listener.jobs.worker import DurableJobWorker


class _FakeOracleCursor:
    """In-memory fake Oracle cursor for verifying SKIP LOCKED + fetchmany behavior."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state
        self.rowcount = 0
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        """Record executed SQL and simulate responses."""
        self._state["executed"].append((sql, params))
        upper_sql = sql.upper()
        if "FROM ALL_TABLES" in upper_sql:
            self._rows = [(1 if self._state.get("tables_exist", True) else 0,)]
            return
        if "INSERT INTO GOE_LISTENER_JOBS" in upper_sql:
            assert params is not None
            table_key = params["table_key"]
            if table_key in self._state["active_tables"]:
                raise RuntimeError("ORA-00001: unique constraint (GOE_REPO.GOE_LISTENER_JOBS_ACTIVE_TBL_UQ) violated")
            self._state["active_tables"][table_key] = params["execution_id"]
            self.rowcount = 1
            return
        if "FOR UPDATE SKIP LOCKED" in upper_sql:
            self._rows = list(self._state.get("pending_rows", []))
            return
        if "SET STATUS           = 'CLAIMED'" in upper_sql:
            self.rowcount = 1
            return
        if "FROM GOE_LISTENER_JOBS" in upper_sql and "TABLE_KEY = :TABLE_KEY" in upper_sql:
            assert params is not None
            exec_id = self._state["active_tables"].get(params["table_key"])
            if exec_id:
                now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
                self._rows = [
                    (
                        "job-existing",
                        exec_id,
                        params["table_key"],
                        "RUNNING",
                        "{}",
                        1,
                        3,
                        "worker-1",
                        now,
                        now + timedelta(seconds=120),
                        now,
                        None,
                        None,
                        now,
                        now,
                    )
                ]
            else:
                self._rows = []
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


class _FakeOracleConnection:
    """In-memory fake Oracle connection."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state
        self.current_schema: str | None = None

    def cursor(self) -> _FakeOracleCursor:
        """Return a fake cursor."""
        return _FakeOracleCursor(self._state)

    def commit(self) -> None:
        """Record commit."""
        self._state["commits"] += 1

    def rollback(self) -> None:
        """Record rollback."""
        self._state["rollbacks"] += 1

    def close(self) -> None:
        """No-op connection close."""


def test_sqlite_job_store_wal_and_table_exclusivity(tmp_path: Path) -> None:
    """Verify SqliteJobStore WAL pragma, table exclusivity across active states, and re-enqueue after completion."""
    db_path = tmp_path / "run" / "listener_jobs.sqlite3"
    store = SqliteJobStore(db_path=db_path)
    assert store.backend_name == "sqlite"
    assert store.journal_mode().lower() == "wal"

    now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    first = store.enqueue(
        execution_id="exec-1",
        owner_table="sh.sales",
        payload={"owner_table": "sh.sales", "execute": True},
        now=now,
    )
    assert first.status is JobState.PENDING
    assert first.table_key == "SH.SALES"

    with pytest.raises(DuplicateActiveTableJobError) as exc_info:
        store.enqueue(
            execution_id="exec-2",
            owner_table="SH.SALES",
            payload={"owner_table": "SH.SALES"},
            now=now,
        )
    assert exc_info.value.table_key == "SH.SALES"
    assert exc_info.value.existing_execution_id == "exec-1"

    claimed = store.claim_batch(worker_id="worker-a", limit=2, lease_seconds=120, now=now)
    assert len(claimed) == 1
    assert claimed[0].job_id == first.job_id
    assert claimed[0].status is JobState.CLAIMED
    assert claimed[0].attempt == 1

    with pytest.raises(DuplicateActiveTableJobError):
        store.enqueue(
            execution_id="exec-3",
            owner_table="sh.sales",
            payload={"owner_table": "sh.sales"},
            now=now,
        )

    assert store.mark_running(job_id=first.job_id, worker_id="worker-a", lease_seconds=120, now=now) is True
    with pytest.raises(DuplicateActiveTableJobError):
        store.enqueue(
            execution_id="exec-4",
            owner_table="sh.sales",
            payload={"owner_table": "sh.sales"},
            now=now,
        )

    assert store.mark_succeeded(job_id=first.job_id, worker_id="worker-a", now=now + timedelta(seconds=10)) is True
    completed = store.get_job_by_execution_id("exec-1")
    assert completed is not None
    assert completed.status is JobState.SUCCEEDED
    assert completed.lease_expires_at is None

    second = store.enqueue(
        execution_id="exec-5",
        owner_table="sh.sales",
        payload={"owner_table": "sh.sales"},
        now=now + timedelta(seconds=20),
    )
    assert second.status is JobState.PENDING
    assert second.execution_id == "exec-5"


def test_oracle_job_store_claim_batch_uses_skip_locked_and_fetchmany() -> None:
    """Verify OracleJobStore claims with FOR UPDATE SKIP LOCKED + fetchmany(limit) and translates ORA-00001."""
    now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    pending_rows = [
        (
            f"job-{idx}",
            f"exec-{idx}",
            f"SH.TABLE_{idx}",
            "PENDING",
            '{"table": "SH.SALES"}',
            0,
            3,
            None,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
        )
        for idx in range(1, 5)
    ]
    state: dict[str, Any] = {
        "executed": [],
        "fetchmany_Grouping_limits": [],
        "pending_rows": pending_rows,
        "active_tables": {},
        "commits": 0,
        "rollbacks": 0,
        "tables_exist": True,
    }
    store = OracleJobStore(
        connection_factory=lambda: _FakeOracleConnection(state),
        repo_user="GOE_REPO",
    )

    claimed = store.claim_batch(worker_id="ora-worker-1", limit=2, lease_seconds=120, now=now)
    assert len(claimed) == 2
    assert [job.job_id for job in claimed] == ["job-1", "job-2"]
    assert all(job.status is JobState.CLAIMED for job in claimed)
    assert all(job.attempt == 1 for job in claimed)
    assert state["fetchmany_Grouping_limits"] == [2]
    assert any("FOR UPDATE SKIP LOCKED" in sql.upper() for sql, _ in state["executed"])
    assert not any("FETCH FIRST" in sql.upper() for sql, _ in state["executed"])

    store.enqueue(
        execution_id="exec-dup-1",
        owner_table="sh.sales",
        payload={"owner_table": "sh.sales"},
        now=now,
    )
    with pytest.raises(DuplicateActiveTableJobError) as exc_info:
        store.enqueue(
            execution_id="exec-dup-2",
            owner_table="SH.SALES",
            payload={"owner_table": "SH.SALES"},
            now=now,
        )
    assert exc_info.value.table_key == "SH.SALES"
    assert exc_info.value.existing_execution_id == "exec-dup-1"


def test_create_job_store_auto_detection_and_fallback(tmp_path: Path) -> None:
    """Verify create_job_store selects OracleJobStore when tables exist and falls back to SqliteJobStore otherwise."""
    ora_state: dict[str, Any] = {
        "executed": [],
        "fetchmany_Grouping_limits": [],
        "pending_rows": [],
        "active_tables": {},
        "commits": 0,
        "rollbacks": 0,
        "tables_exist": True,
    }
    oracle_store = create_job_store(
        connection_factory=lambda: _FakeOracleConnection(ora_state),
        repo_user="GOE_REPO",
        offload_home=tmp_path,
    )
    assert isinstance(oracle_store, OracleJobStore)

    ora_state["tables_exist"] = False
    fallback_store = create_job_store(
        connection_factory=lambda: _FakeOracleConnection(ora_state),
        repo_user="GOE_REPO",
        offload_home=tmp_path,
    )
    assert isinstance(fallback_store, SqliteJobStore)
    assert (tmp_path / "run" / "listener_jobs.sqlite3").exists()


@pytest.mark.anyio
async def test_durable_job_worker_renews_lease_during_slow_execution(tmp_path: Path) -> None:
    """Verify DurableJobWorker renews the lease periodically while a slow job coroutine executes."""
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    base_now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    enqueued = store.enqueue(
        execution_id="exec-slow",
        owner_table="sh.sales",
        payload={"owner_table": "sh.sales"},
        now=base_now,
    )

    observed_leases: list[datetime] = []

    async def slow_executor(record: JobRecord) -> None:
        for _ in range(3):
            await asyncio.sleep(0.05)
            current = store.get_job_by_execution_id(record.execution_id)
            assert current is not None
            assert current.status is JobState.RUNNING
            assert current.lease_expires_at is not None
            observed_leases.append(current.lease_expires_at)

    worker = DurableJobWorker(
        store=store,
        executor=slow_executor,
        worker_id="worker-lease-test",
        lease_seconds=120,
        heartbeat_interval_seconds=0.03,
        poll_interval_seconds=0.02,
    )
    processed = await worker.process_once()
    assert len(processed) == 1
    assert processed[0].job_id == enqueued.job_id
    assert len(observed_leases) >= 2
    assert observed_leases[-1] > observed_leases[0]

    final_record = store.get_job_by_execution_id("exec-slow")
    assert final_record is not None
    assert final_record.status is JobState.SUCCEEDED
    assert final_record.lease_expires_at is None


def test_reap_expired_leases_and_node_heartbeats(tmp_path: Path) -> None:
    """Verify expired leases transition to PENDING or DEAD_LETTER and node heartbeats filter expired rows."""
    store = SqliteJobStore(db_path=tmp_path / "reap.sqlite3")
    t0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)

    job = store.enqueue(
        execution_id="exec-reap",
        owner_table="sh.customers",
        payload={"owner_table": "sh.customers"},
        max_attempts=2,
        now=t0,
    )
    claimed = store.claim_batch(worker_id="worker-dead", limit=1, lease_seconds=60, now=t0)
    assert len(claimed) == 1
    assert claimed[0].attempt == 1
    store.mark_running(job_id=job.job_id, worker_id="worker-dead", lease_seconds=60, now=t0)

    worker = DurableJobWorker(
        store=store,
        worker_id="worker-reaper",
        endpoint_id="endpoint-1",
        listener_group_id="group-1",
        host_url="http://127.0.0.1:8000",
        heartbeat_interval_seconds=30,
    )
    reaped_count = worker.reap_expired_leases(now=t0 + timedelta(seconds=61))
    assert reaped_count == 1
    requeued = store.get_job_by_execution_id("exec-reap")
    assert requeued is not None
    assert requeued.status is JobState.PENDING
    assert requeued.attempt == 1

    claimed_again = store.claim_batch(
        worker_id="worker-dead-2", limit=1, lease_seconds=60, now=t0 + timedelta(seconds=62)
    )
    assert len(claimed_again) == 1
    assert claimed_again[0].attempt == 2

    reaped_dead = worker.reap_expired_leases(now=t0 + timedelta(seconds=130))
    assert reaped_dead == 1
    dead_lettered = store.get_job_by_execution_id("exec-reap")
    assert dead_lettered is not None
    assert dead_lettered.status is JobState.DEAD_LETTER

    hb = worker.publish_node_heartbeat(now=t0)
    active = store.list_active_heartbeats(now=t0 + timedelta(seconds=30))
    assert len(active) == 1
    assert active[0].endpoint_id == hb.endpoint_id

    expired = store.list_active_heartbeats(now=hb.expires_at + timedelta(seconds=1))
    assert expired == []
