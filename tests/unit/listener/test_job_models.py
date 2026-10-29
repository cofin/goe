# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for GOE Listener durable job queue models and SQL definitions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import msgspec
import pytest
from sqlspec.loader import SQLFileLoader

from goe.listener.jobs.models import (
    JobRecord,
    JobState,
    NodeHeartbeat,
    normalize_table_key,
)
from goe.serializers import decode_json, encode_json

JOB_QUEUE_SQL_PATH = Path(__file__).resolve().parents[3] / "src" / "goe" / "listener" / "jobs" / "sql" / "job_queue.sql"


def test_job_state_membership_and_helpers() -> None:
    """Verify JobState enum values, active states, and terminal states."""
    expected = {
        "PENDING",
        "CLAIMED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "DEAD_LETTER",
    }
    assert {state.value for state in JobState} == expected

    for active in (JobState.PENDING, JobState.CLAIMED, JobState.RUNNING):
        assert active.is_active() is True
        assert active.is_terminal() is False

    for terminal in (
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.DEAD_LETTER,
    ):
        assert terminal.is_active() is False
        assert terminal.is_terminal() is True


def test_normalize_table_key() -> None:
    """Verify canonical uppercase OWNER.TABLE normalization and validation."""
    assert normalize_table_key(" sh.sales ") == "SH.SALES"
    assert normalize_table_key("OE.ORDERS") == "OE.ORDERS"

    with pytest.raises(ValueError, match=r"OWNER\.TABLE"):
        normalize_table_key("INVALID_KEY")

    with pytest.raises(ValueError, match="non-empty"):
        normalize_table_key("SH.")

    with pytest.raises(ValueError, match="non-empty"):
        normalize_table_key(".SALES")


def test_job_record_immutability_lease_and_serialization() -> None:
    """Verify JobRecord immutability, lease expiration logic, and JSON round-trip."""
    now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    record = JobRecord.create_pending(
        job_id="job-1",
        execution_id="exec-1",
        owner_table="sh.sales",
        payload={"table": "sh.sales", "execute": True},
        now=now,
    )
    assert record.table_key == "SH.SALES"
    assert record.status is JobState.PENDING
    assert record.attempt == 0
    assert record.max_attempts == 3
    assert record.decode_payload() == {"table": "sh.sales", "execute": True}
    assert record.is_lease_expired(now) is False

    with pytest.raises(AttributeError):
        record.status = JobState.RUNNING  # type: ignore[misc]

    claimed = msgspec.structs.replace(
        record,
        status=JobState.RUNNING,
        worker_id="worker-1",
        claimed_at=now,
        lease_expires_at=now + timedelta(seconds=120),
    )
    assert claimed.is_lease_expired(now + timedelta(seconds=119)) is False
    assert claimed.is_lease_expired(now + timedelta(seconds=120)) is True

    raw = encode_json(claimed)
    decoded = decode_json(raw, target_type=JobRecord)
    assert decoded == claimed


def test_node_heartbeat_immutability_and_expiration() -> None:
    """Verify NodeHeartbeat immutability and expiration checks."""
    now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    hb = NodeHeartbeat(
        endpoint_id="node-1",
        listener_group_id="group-a",
        host_url="http://127.0.0.1:8000",
        worker_role="all",
        updated_at=now,
        expires_at=now + timedelta(seconds=90),
    )
    assert hb.is_expired(now + timedelta(seconds=89)) is False
    assert hb.is_expired(now + timedelta(seconds=90)) is True

    with pytest.raises(AttributeError):
        hb.worker_role = "http"  # type: ignore[misc]


def test_job_queue_sql_loader_and_sqlite_unique_index() -> None:
    """Verify SQLFileLoader parses job_queue.sql and SQLite partial unique index enforces exclusivity."""
    loader = SQLFileLoader()
    loader.load_sql(JOB_QUEUE_SQL_PATH)

    required_queries = {
        "oracle_probe_tables",
        "oracle_insert_job",
        "oracle_claim_pending_jobs",
        "oracle_mark_claimed",
        "oracle_mark_running",
        "oracle_renew_lease",
        "oracle_mark_terminal",
        "oracle_reap_expired_to_pending",
        "oracle_reap_expired_to_dead_letter",
        "oracle_get_job",
        "oracle_get_active_job_for_table",
        "oracle_list_jobs",
        "oracle_upsert_heartbeat",
        "oracle_list_active_heartbeats",
        "oracle_ddl_jobs_table",
        "oracle_ddl_active_table_uq",
        "oracle_ddl_status_idx",
        "oracle_ddl_endpoints_table",
        "sqlite_ddl_jobs_table",
        "sqlite_ddl_active_table_uq",
        "sqlite_ddl_status_idx",
        "sqlite_ddl_endpoints_table",
    }
    available_queries = set(loader.list_queries())
    assert required_queries.issubset(available_queries)

    oracle_claim_sql = loader.get_sql("oracle_claim_pending_jobs").raw_sql.upper()
    assert "FOR UPDATE SKIP LOCKED" in oracle_claim_sql
    assert "FETCH FIRST" not in oracle_claim_sql

    oracle_uq_sql = loader.get_sql("oracle_ddl_active_table_uq").raw_sql.upper()
    assert "CASE WHEN STATUS IN ('PENDING', 'CLAIMED', 'RUNNING') THEN TABLE_KEY END" in oracle_uq_sql

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(loader.get_sql("sqlite_ddl_jobs_table").raw_sql)
        conn.execute(loader.get_sql("sqlite_ddl_active_table_uq").raw_sql)
        conn.execute(loader.get_sql("sqlite_ddl_status_idx").raw_sql)
        conn.execute(loader.get_sql("sqlite_ddl_endpoints_table").raw_sql)

        insert_sql = loader.get_sql("sqlite_insert_job").raw_sql
        now_iso = "2026-10-24T12:00:00+00:00"
        conn.execute(
            insert_sql,
            {
                "job_id": "job-1",
                "execution_id": "exec-1",
                "table_key": "SH.SALES",
                "status": "PENDING",
                "payload_json": "{}",
                "attempt": 0,
                "max_attempts": 3,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                insert_sql,
                {
                    "job_id": "job-2",
                    "execution_id": "exec-2",
                    "table_key": "SH.SALES",
                    "status": "RUNNING",
                    "payload_json": "{}",
                    "attempt": 1,
                    "max_attempts": 3,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
            )

        conn.execute("UPDATE goe_listener_jobs SET status = 'SUCCEEDED' WHERE job_id = 'job-1'")
        conn.execute(
            insert_sql,
            {
                "job_id": "job-3",
                "execution_id": "exec-3",
                "table_key": "SH.SALES",
                "status": "SUCCEEDED",
                "payload_json": "{}",
                "attempt": 1,
                "max_attempts": 3,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
        conn.execute(
            insert_sql,
            {
                "job_id": "job-4",
                "execution_id": "exec-4",
                "table_key": "SH.SALES",
                "status": "PENDING",
                "payload_json": "{}",
                "attempt": 0,
                "max_attempts": 3,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
    finally:
        conn.close()
