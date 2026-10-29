# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OracleJobStore and DurableJobWorker."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest
from litestar.di import Provide
from litestar.testing import TestClient

from goe.listener.app import create_app
from goe.listener.jobs.models import JobRecord, JobState
from goe.listener.jobs.store import (
    DuplicateActiveTableJobError,
    OracleJobStore,
    create_job_store,
)
from goe.listener.jobs.worker import DurableJobWorker, _CooperativeCancelSink
from goe.orchestration.sinks import LogEvent
from tests.unit.listener.conftest import (
    FakeOracleConnection,
    make_fake_oracle_job_store,
    make_fake_oracle_state,
)


def test_oracle_job_store_table_exclusivity_and_lifecycle() -> None:
    """Verify OracleJobStore enforces table exclusivity across active states and allows re-enqueue after completion."""
    store = make_fake_oracle_job_store()
    assert store.backend_name == "oracle"

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
            0,
            now,
            now,
        )
        for idx in range(1, 5)
    ]
    state = make_fake_oracle_state(pending_rows=pending_rows)
    store = OracleJobStore(
        connection_factory=lambda: FakeOracleConnection(state),
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


def test_create_job_store_returns_oracle_job_store() -> None:
    """Verify create_job_store always constructs an OracleJobStore."""
    ora_state = make_fake_oracle_state()
    oracle_store = create_job_store(
        connection_factory=lambda: FakeOracleConnection(ora_state),
        repo_user="GOE_REPO",
    )
    assert isinstance(oracle_store, OracleJobStore)
    assert oracle_store.probe_tables() is True

    default_store = create_job_store()
    assert isinstance(default_store, OracleJobStore)


@pytest.mark.anyio
async def test_durable_job_worker_renews_lease_during_slow_execution() -> None:
    """Verify DurableJobWorker renews the lease periodically while a slow job coroutine executes."""
    store = make_fake_oracle_job_store()
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


def test_reap_expired_leases_and_node_heartbeats() -> None:
    """Verify expired leases transition to PENDING or DEAD_LETTER and node heartbeats filter expired rows."""
    store = make_fake_oracle_job_store()
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


def test_oracle_cancel_job_state_machine_and_reaping() -> None:
    """Verify pending, claimed, running, and terminal cancellation and expired lease reaping on OracleJobStore."""
    store = make_fake_oracle_job_store()
    t0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)

    pending_job = store.enqueue(
        execution_id="00000000-0000-0000-0000-000000000021",
        owner_table="sh.sales",
        payload={"owner_table": "sh.sales"},
        now=t0,
    )
    cancelled_pending = store.cancel_job(
        execution_id=pending_job.execution_id,
        reason="Cancelled by operator",
        now=t0 + timedelta(seconds=5),
    )
    assert cancelled_pending is not None
    assert cancelled_pending.status is JobState.CANCELLED
    assert cancelled_pending.cancel_requested is True
    assert cancelled_pending.finished_at is not None
    assert cancelled_pending.lease_expires_at is None
    assert store.get_active_job_for_table("sh.sales") is None
    assert store.claim_batch(worker_id="w1", limit=5, now=t0 + timedelta(seconds=6)) == []

    idempotent = store.cancel_job(execution_id=pending_job.execution_id, now=t0 + timedelta(seconds=10))
    assert idempotent is not None
    assert idempotent.status is JobState.CANCELLED
    assert store.cancel_job(execution_id="00000000-0000-0000-0000-000000000099") is None

    running_job = store.enqueue(
        execution_id="00000000-0000-0000-0000-000000000022",
        owner_table="sh.sales",
        payload={"owner_table": "sh.sales"},
        now=t0 + timedelta(seconds=15),
    )
    store.claim_batch(worker_id="w1", limit=1, lease_seconds=30, now=t0 + timedelta(seconds=15))
    store.mark_running(job_id=running_job.job_id, worker_id="w1", lease_seconds=30, now=t0 + timedelta(seconds=15))

    flagged_running = store.cancel_job(
        execution_id=running_job.execution_id,
        reason="Abort long offload",
        now=t0 + timedelta(seconds=20),
    )
    assert flagged_running is not None
    assert flagged_running.status is JobState.RUNNING
    assert flagged_running.cancel_requested is True

    reaped = store.reap_expired_leases(now=t0 + timedelta(seconds=60))
    assert reaped == 1
    after_reap = store.get_job_by_execution_id(running_job.execution_id)
    assert after_reap is not None
    assert after_reap.status is JobState.CANCELLED
    assert after_reap.lease_expires_at is None


@pytest.mark.anyio
async def test_cooperative_cancel_sink_unwinds_worker_thread_before_mark_cancelled() -> None:
    """Verify RUNNING job cancellation trips _CooperativeCancelSink and unwinds thread lock before mark_cancelled."""
    store = make_fake_oracle_job_store()
    exec_id = "00000000-0000-0000-0000-000000000031"
    store.enqueue(
        execution_id=exec_id,
        owner_table="sh.sales",
        payload={"owner_table": "sh.sales"},
    )
    events_log: list[str] = []

    async def thread_backed_executor(record: JobRecord, cancel_event: threading.Event) -> None:
        sink = _CooperativeCancelSink(cancel_event)

        def _sync_work() -> None:
            events_log.append("lock_acquired")
            try:
                while True:
                    sink.emit(LogEvent(line="step tick"))
                    threading.Event().wait(0.01)
            finally:
                events_log.append("lock_released")

        await asyncio.to_thread(_sync_work)

    worker = DurableJobWorker(
        store=store,
        executor=thread_backed_executor,
        worker_id="worker-coop",
        lease_seconds=120,
        heartbeat_interval_seconds=0.02,
        poll_interval_seconds=0.01,
    )

    async def _trigger_cancel() -> None:
        await asyncio.sleep(0.03)
        store.cancel_job(execution_id=exec_id, reason="Operator requested cancel")

    cancel_task = asyncio.create_task(_trigger_cancel())
    await worker.process_once()
    await cancel_task

    final = store.get_job_by_execution_id(exec_id)
    assert final is not None
    assert final.status is JobState.CANCELLED
    assert final.cancel_requested is True
    assert events_log == ["lock_acquired", "lock_released"]


def test_cancel_offload_job_endpoint_rest_and_mcp() -> None:
    """Verify POST /api/orchestration/executions/{execution_id}/cancel/ over REST and MCP."""
    store = make_fake_oracle_job_store()
    exec_id = "00000000-0000-0000-0000-000000000041"
    store.enqueue(execution_id=exec_id, owner_table="SH.SALES", payload={"owner_table": "SH.SALES"})

    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
    base_meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    with TestClient(app=app) as client:
        resp = client.post(f"/api/orchestration/executions/{exec_id}/cancel/")
        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["status"] == "CANCELLED"
        assert body["cancel_requested"] is True

        exec_id_2 = "00000000-0000-0000-0000-000000000042"
        store.enqueue(execution_id=exec_id_2, owner_table="SH.COSTS", payload={"owner_table": "SH.COSTS"})
        mcp_resp = client.post(
            "/mcp",
            headers={
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "cancel_offload_job",
            },
            json={
                "jsonrpc": "2.0",
                "id": 50,
                "method": "tools/call",
                "params": {
                    "name": "cancel_offload_job",
                    "arguments": {"execution_id": exec_id_2},
                    "_meta": base_meta,
                },
            },
        )
        assert mcp_resp.status_code == 200
        assert mcp_resp.json()["result"]["isError"] is False

        missing = client.post("/api/orchestration/executions/00000000-0000-0000-0000-000000000099/cancel/")
        assert missing.status_code == 404
