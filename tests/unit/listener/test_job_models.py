# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for GOE Listener durable job queue models and Oracle SQL definitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import msgspec
import pytest
from sqlspec.loader import SQLFileLoader

from goe.listener.jobs.models import (
    JobCancelledError,
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
    assert record.cancel_requested is False
    assert issubclass(JobCancelledError, Exception)
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


def test_job_queue_sql_loader_and_oracle_exclusivity_ddl() -> None:
    """Verify SQLFileLoader parses job_queue.sql with only Oracle named queries and function-based unique index."""
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
        "oracle_reap_expired_to_cancelled",
        "oracle_cancel_pending_or_claimed_job",
        "oracle_request_cancel_running_job",
        "oracle_mark_cancelled",
        "oracle_get_job",
        "oracle_get_active_job_for_table",
        "oracle_list_jobs",
        "oracle_upsert_heartbeat",
        "oracle_list_active_heartbeats",
        "oracle_ddl_jobs_table",
        "oracle_ddl_active_table_uq",
        "oracle_ddl_status_idx",
        "oracle_ddl_endpoints_table",
    }
    available_queries = set(loader.list_queries())
    assert available_queries == required_queries
    assert not any(name.startswith("sqlite_") for name in available_queries)

    oracle_ddl = loader.get_sql("oracle_ddl_jobs_table").raw_sql.upper()
    assert "CANCEL_REQUESTED" in oracle_ddl

    oracle_claim_sql = loader.get_sql("oracle_claim_pending_jobs").raw_sql.upper()
    assert "FOR UPDATE SKIP LOCKED" in oracle_claim_sql
    assert "AND CANCEL_REQUESTED = 0" in oracle_claim_sql
    assert "FETCH FIRST" not in oracle_claim_sql

    oracle_uq_sql = loader.get_sql("oracle_ddl_active_table_uq").raw_sql.upper()
    assert "CASE WHEN STATUS IN ('PENDING', 'CLAIMED', 'RUNNING') THEN TABLE_KEY END" in oracle_uq_sql
