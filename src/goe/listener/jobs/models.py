# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Immutable domain models for the GOE Listener durable job queue."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from goe.serializers import decode_json, encode_json
from goe.typing import FrozenBaseStruct

__all__ = (
    "JobCancelledError",
    "JobRecord",
    "JobState",
    "NodeHeartbeat",
    "normalize_table_key",
)


class JobCancelledError(Exception):
    """Raised inside a worker thread when cooperative cancellation is requested for an active job."""


class JobState(StrEnum):
    """Lifecycle states for a durable Listener offload job."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"

    def is_active(self) -> bool:
        """Return True when the job holds table exclusivity."""
        return self in (JobState.PENDING, JobState.CLAIMED, JobState.RUNNING)

    def is_terminal(self) -> bool:
        """Return True when the job has reached a final state."""
        return self in (
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.DEAD_LETTER,
        )


def normalize_table_key(owner_table: str) -> str:
    """Normalize an owner.table string into canonical uppercase TABLE_KEY form."""
    cleaned = owner_table.strip().upper()
    if "." not in cleaned:
        raise ValueError(f"Expected OWNER.TABLE format for table_key, got {owner_table!r}")
    owner, table = cleaned.split(".", 1)
    if not owner or not table:
        raise ValueError(f"Expected non-empty owner and table in {owner_table!r}")
    return f"{owner}.{table}"


class JobRecord(FrozenBaseStruct, frozen=True):
    """Immutable snapshot of a durable offload job row."""

    job_id: str
    execution_id: str
    table_key: str
    status: JobState
    payload_json: str
    created_at: datetime
    updated_at: datetime
    attempt: int = 0
    max_attempts: int = 3
    worker_id: str | None = None
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    cancel_requested: bool = False

    @classmethod
    def create_pending(
        cls,
        *,
        job_id: str,
        execution_id: str,
        owner_table: str,
        payload: dict[str, Any],
        now: datetime,
        max_attempts: int = 3,
    ) -> JobRecord:
        """Construct a newly enqueued PENDING JobRecord."""
        return cls(
            job_id=job_id,
            execution_id=execution_id,
            table_key=normalize_table_key(owner_table),
            status=JobState.PENDING,
            payload_json=encode_json(payload),
            created_at=now,
            updated_at=now,
            attempt=0,
            max_attempts=max_attempts,
        )

    def decode_payload(self) -> dict[str, Any]:
        """Decode payload_json into a dictionary."""
        result = decode_json(self.payload_json)
        if not isinstance(result, dict):
            raise TypeError("JobRecord payload_json must decode to a dict")
        return result

    def is_lease_expired(self, now: datetime) -> bool:
        """Return True if the job holds a lease that has expired at now."""
        if self.status not in (JobState.CLAIMED, JobState.RUNNING):
            return False
        if self.lease_expires_at is None:
            return True
        return now >= self.lease_expires_at


class NodeHeartbeat(FrozenBaseStruct, frozen=True):
    """Immutable snapshot of an active Listener or worker node heartbeat row."""

    endpoint_id: str
    listener_group_id: str
    host_url: str
    worker_role: str
    updated_at: datetime
    expires_at: datetime
    version: str = "1.0.0"

    def is_expired(self, now: datetime) -> bool:
        """Return True when the node heartbeat has expired at now."""
        return now >= self.expires_at
