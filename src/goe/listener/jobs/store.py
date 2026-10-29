# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Oracle durable job store for the GOE Listener."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from sqlspec.loader import SQLFileLoader

from goe.config.orchestration_config import OrchestrationConfig
from goe.exceptions import GOEError
from goe.listener.jobs.models import (
    JobRecord,
    JobState,
    NodeHeartbeat,
    normalize_table_key,
)
from goe.persistence.registry import OracleConnectionSettings, OracleDatabaseRegistry

__all__ = (
    "DuplicateActiveTableJobError",
    "JobStoreProtocol",
    "OracleJobStore",
    "create_job_store",
)

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parent / "sql"
JOB_QUEUE_SQL_PATH = SQL_DIR / "job_queue.sql"


class DuplicateActiveTableJobError(GOEError):
    """Raised when an active job already exists for the target frontend table."""

    def __init__(self, table_key: str, existing_execution_id: str | None = None) -> None:
        self.table_key = table_key
        self.existing_execution_id = existing_execution_id
        detail = f"Active offload job already exists for table {table_key}"
        if existing_execution_id:
            detail = f"{detail} (execution_id={existing_execution_id})"
        super().__init__(detail)


@runtime_checkable
class JobStoreProtocol(Protocol):
    """Protocol implemented by OracleJobStore."""

    backend_name: str

    def enqueue(
        self,
        *,
        execution_id: str,
        owner_table: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> JobRecord:
        """Insert a new PENDING job or raise DuplicateActiveTableJobError."""

    def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int = 1,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> list[JobRecord]:
        """Atomically claim up to limit PENDING jobs for worker_id."""

    def mark_running(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> bool:
        """Transition a CLAIMED job to RUNNING and extend its lease."""

    def renew_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> bool:
        """Extend lease_expires_at for an active job owned by worker_id."""

    def mark_succeeded(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime | None = None,
    ) -> bool:
        """Transition a running job to SUCCEEDED and clear its lease."""

    def mark_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_message: str,
        dead_letter: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """Transition a running job to FAILED or DEAD_LETTER."""

    def cancel_job(
        self,
        *,
        execution_id: str,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> JobRecord | None:
        """Cancel a PENDING/CLAIMED job immediately or flag a RUNNING job for cooperative cancellation."""

    def mark_cancelled(
        self,
        *,
        job_id: str,
        worker_id: str,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Transition a CLAIMED or RUNNING job to CANCELLED after cooperative worker thread unwind."""

    def reap_expired_leases(self, *, now: datetime | None = None) -> int:
        """Requeue expired leases with remaining attempts, cancel flagged ones, and dead-letter exhausted ones."""

    def get_job_by_execution_id(self, execution_id: str) -> JobRecord | None:
        """Return the JobRecord for execution_id, or None when absent."""

    def get_active_job_for_table(self, owner_table: str) -> JobRecord | None:
        """Return the active JobRecord for owner_table, or None when unlocked."""

    def list_jobs(self, *, limit: int = 100, status: JobState | None = None) -> list[JobRecord]:
        """List recent jobs ordered by created_at descending."""

    def upsert_heartbeat(self, heartbeat: NodeHeartbeat) -> None:
        """Insert or update a Listener/worker node heartbeat row."""

    def list_active_heartbeats(self, *, now: datetime | None = None) -> list[NodeHeartbeat]:
        """Return non-expired node heartbeat rows."""


class OracleJobStore:
    """Multi-host Oracle durable job store using SELECT ... FOR UPDATE SKIP LOCKED + fetchmany(limit)."""

    backend_name = "oracle"

    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any] | None = None,
        registry: Any | None = None,
        repo_user: str | None = None,
    ) -> None:
        if connection_factory is None and registry is None:
            raise ValueError("OracleJobStore requires either connection_factory or registry")
        self._connection_factory = connection_factory
        self._registry = registry
        self._repo_user = (repo_user or "").strip().upper()
        self._loader = _get_sql_loader()

    def probe_tables(self) -> bool:
        """Return True when GOE_LISTENER_JOBS exists in the repository schema."""
        sql = self._sql("oracle_probe_tables")
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(sql, {"repo_user": self._repo_user or "GOE_REPO"})
                    row = cursor.fetchone()
                    return bool(row and int(row[0]) > 0)
                finally:
                    cursor.close()
        except Exception:
            logger.debug("Oracle GOE_LISTENER_JOBS probe failed", exc_info=True)
            return False

    def enqueue(
        self,
        *,
        execution_id: str,
        owner_table: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> JobRecord:
        """Insert a new PENDING job or raise DuplicateActiveTableJobError on ORA-00001."""
        ts = _ensure_utc(now)
        record = JobRecord.create_pending(
            job_id=uuid4().hex,
            execution_id=execution_id,
            owner_table=owner_table,
            payload=payload,
            now=ts,
            max_attempts=max_attempts,
        )
        sql = self._sql("oracle_insert_job")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    sql,
                    {
                        "job_id": record.job_id,
                        "execution_id": record.execution_id,
                        "table_key": record.table_key,
                        "status": record.status.value,
                        "payload_json": record.payload_json,
                        "attempt": record.attempt,
                        "max_attempts": record.max_attempts,
                        "created_at": record.created_at,
                        "updated_at": record.updated_at,
                    },
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                if _is_oracle_unique_violation(exc):
                    existing = self.get_active_job_for_table(record.table_key)
                    existing_exec_id = existing.execution_id if existing else None
                    raise DuplicateActiveTableJobError(record.table_key, existing_exec_id) from exc
                raise
            finally:
                cursor.close()
        return record

    def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int = 1,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> list[JobRecord]:
        """Atomically claim up to limit PENDING jobs via FOR UPDATE SKIP LOCKED and fetchmany(limit)."""
        if limit <= 0:
            return []
        ts = _ensure_utc(now)
        lease_until = ts + timedelta(seconds=lease_seconds)
        select_sql = self._sql("oracle_claim_pending_jobs")
        update_sql = self._sql("oracle_mark_claimed")
        claimed: list[JobRecord] = []
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(select_sql)
                rows = cursor.fetchmany(limit)
                for row in rows:
                    pending = _row_to_job_record(row)
                    cursor.execute(
                        update_sql,
                        {
                            "job_id": pending.job_id,
                            "worker_id": worker_id,
                            "claimed_at": ts,
                            "lease_expires_at": lease_until,
                            "updated_at": ts,
                        },
                    )
                    if cursor.rowcount == 1:
                        claimed.append(
                            JobRecord(
                                job_id=pending.job_id,
                                execution_id=pending.execution_id,
                                table_key=pending.table_key,
                                status=JobState.CLAIMED,
                                payload_json=pending.payload_json,
                                created_at=pending.created_at,
                                updated_at=ts,
                                attempt=pending.attempt + 1,
                                max_attempts=pending.max_attempts,
                                worker_id=worker_id,
                                claimed_at=ts,
                                lease_expires_at=lease_until,
                                started_at=pending.started_at,
                                finished_at=pending.finished_at,
                                error_message=pending.error_message,
                                cancel_requested=pending.cancel_requested,
                            )
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
        return claimed

    def mark_running(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> bool:
        """Transition a CLAIMED job to RUNNING and extend its lease."""
        ts = _ensure_utc(now)
        lease_until = ts + timedelta(seconds=lease_seconds)
        sql = self._sql("oracle_mark_running")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    sql,
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "started_at": ts,
                        "lease_expires_at": lease_until,
                        "updated_at": ts,
                    },
                )
                conn.commit()
                return bool(cursor.rowcount == 1)
            finally:
                cursor.close()

    def renew_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> bool:
        """Extend lease_expires_at for an active job owned by worker_id."""
        ts = _ensure_utc(now)
        lease_until = ts + timedelta(seconds=lease_seconds)
        sql = self._sql("oracle_renew_lease")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    sql,
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "lease_expires_at": lease_until,
                        "updated_at": ts,
                    },
                )
                conn.commit()
                return bool(cursor.rowcount == 1)
            finally:
                cursor.close()

    def mark_succeeded(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime | None = None,
    ) -> bool:
        """Transition a running job to SUCCEEDED and clear its lease."""
        ts = _ensure_utc(now)
        sql = self._sql("oracle_mark_terminal")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    sql,
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "status": JobState.SUCCEEDED.value,
                        "finished_at": ts,
                        "error_message": None,
                        "updated_at": ts,
                    },
                )
                conn.commit()
                return bool(cursor.rowcount == 1)
            finally:
                cursor.close()

    def mark_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_message: str,
        dead_letter: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """Transition a running job to FAILED or DEAD_LETTER."""
        ts = _ensure_utc(now)
        target_status = JobState.DEAD_LETTER if dead_letter else JobState.FAILED
        sql = self._sql("oracle_mark_terminal")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    sql,
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "status": target_status.value,
                        "finished_at": ts,
                        "error_message": error_message,
                        "updated_at": ts,
                    },
                )
                conn.commit()
                return bool(cursor.rowcount == 1)
            finally:
                cursor.close()

    def cancel_job(
        self,
        *,
        execution_id: str,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> JobRecord | None:
        """Cancel a PENDING/CLAIMED job immediately or flag a RUNNING job for cooperative cancellation."""
        ts = _ensure_utc(now)
        existing = self.get_job_by_execution_id(execution_id)
        if existing is None:
            return None
        if existing.status.is_terminal():
            return existing
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                if existing.status in (JobState.PENDING, JobState.CLAIMED):
                    cursor.execute(
                        self._sql("oracle_cancel_pending_or_claimed_job"),
                        {
                            "execution_id": execution_id,
                            "now": ts,
                            "error_message": reason,
                        },
                    )
                elif existing.status is JobState.RUNNING:
                    cursor.execute(
                        self._sql("oracle_request_cancel_running_job"),
                        {
                            "execution_id": execution_id,
                            "now": ts,
                            "error_message": reason,
                        },
                    )
                conn.commit()
            finally:
                cursor.close()
        return self.get_job_by_execution_id(execution_id)

    def mark_cancelled(
        self,
        *,
        job_id: str,
        worker_id: str,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Transition a CLAIMED or RUNNING job to CANCELLED after cooperative worker thread unwind."""
        ts = _ensure_utc(now)
        sql = self._sql("oracle_mark_cancelled")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    sql,
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "finished_at": ts,
                        "error_message": reason,
                        "updated_at": ts,
                    },
                )
                conn.commit()
                return bool(cursor.rowcount == 1)
            finally:
                cursor.close()

    def reap_expired_leases(self, *, now: datetime | None = None) -> int:
        """Requeue expired leases with remaining attempts, cancel flagged ones, and dead-letter exhausted ones."""
        ts = _ensure_utc(now)
        to_cancelled_sql = self._sql("oracle_reap_expired_to_cancelled")
        to_pending_sql = self._sql("oracle_reap_expired_to_pending")
        to_dead_sql = self._sql("oracle_reap_expired_to_dead_letter")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(to_cancelled_sql, {"now": ts})
                cancelled = int(max(0, cursor.rowcount))
                cursor.execute(to_pending_sql, {"now": ts})
                requeued = int(max(0, cursor.rowcount))
                cursor.execute(to_dead_sql, {"now": ts})
                dead = int(max(0, cursor.rowcount))
                conn.commit()
                return cancelled + requeued + dead
            finally:
                cursor.close()

    def get_job_by_execution_id(self, execution_id: str) -> JobRecord | None:
        """Return the JobRecord for execution_id, or None when absent."""
        sql = self._sql("oracle_get_job")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, {"execution_id": execution_id})
                row = cursor.fetchone()
                return _row_to_job_record(row) if row else None
            finally:
                cursor.close()

    def get_active_job_for_table(self, owner_table: str) -> JobRecord | None:
        """Return the active JobRecord for owner_table, or None when unlocked."""
        table_key = normalize_table_key(owner_table)
        sql = self._sql("oracle_get_active_job_for_table")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, {"table_key": table_key})
                row = cursor.fetchone()
                return _row_to_job_record(row) if row else None
            finally:
                cursor.close()

    def list_jobs(self, *, limit: int = 100, status: JobState | None = None) -> list[JobRecord]:
        """List recent jobs ordered by created_at descending."""
        sql = self._sql("oracle_list_jobs")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, {"status": status.value if status else None})
                rows = cursor.fetchmany(limit)
                return [_row_to_job_record(row) for row in rows]
            finally:
                cursor.close()

    def upsert_heartbeat(self, heartbeat: NodeHeartbeat) -> None:
        """Insert or update a Listener/worker node heartbeat row."""
        sql = self._sql("oracle_upsert_heartbeat")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    sql,
                    {
                        "endpoint_id": heartbeat.endpoint_id,
                        "listener_group_id": heartbeat.listener_group_id,
                        "host_url": heartbeat.host_url,
                        "worker_role": heartbeat.worker_role,
                        "version": heartbeat.version,
                        "updated_at": heartbeat.updated_at,
                        "expires_at": heartbeat.expires_at,
                    },
                )
                conn.commit()
            finally:
                cursor.close()

    def list_active_heartbeats(self, *, now: datetime | None = None) -> list[NodeHeartbeat]:
        """Return non-expired node heartbeat rows."""
        ts = _ensure_utc(now)
        sql = self._sql("oracle_list_active_heartbeats")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, {"now": ts})
                rows = cursor.fetchall()
                return [_row_to_heartbeat(row) for row in rows]
            finally:
                cursor.close()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        """Acquire and release an Oracle connection from connection_factory or registry."""
        if self._connection_factory is not None:
            conn = self._connection_factory()
            try:
                if self._repo_user and hasattr(conn, "current_schema"):
                    conn.current_schema = self._repo_user
                yield conn
            finally:
                if hasattr(conn, "close"):
                    conn.close()
            return

        assert self._registry is not None
        conn = self._registry.lease("adm", action="OracleJobStore")
        try:
            if self._repo_user and hasattr(conn, "current_schema"):
                conn.current_schema = self._repo_user
            yield conn
        finally:
            self._registry.release("adm", conn)

    def _sql(self, query_name: str) -> str:
        """Return raw SQL text for query_name without trailing semicolon."""
        return self._loader.get_sql(query_name).raw_sql.strip().removesuffix(";").rstrip()


def create_job_store(
    *,
    registry: Any | None = None,
    connection_factory: Callable[[], Any] | None = None,
    repo_user: str | None = None,
    config: Any | None = None,
) -> OracleJobStore:
    """Create an OracleJobStore backed by the GOE Oracle repository."""
    resolved_registry = registry
    resolved_repo_user = repo_user
    if resolved_registry is None and connection_factory is None:
        resolved_config = config
        if resolved_config is None:
            try:
                resolved_config = OrchestrationConfig.as_defaults(do_not_connect=True)
            except Exception:
                resolved_config = None
        if resolved_config is not None:
            resolved_registry = OracleDatabaseRegistry.for_options(resolved_config)
            if resolved_repo_user is None:
                resolved_repo_user = getattr(resolved_config, "ora_repo_user", None)
        else:
            dsn = os.environ.get("ORA_ADM_DSN") or os.environ.get("ORACLE_DSN") or os.environ.get("RDBMS_DSN") or ""
            transport_dsn = os.environ.get("OFFLOAD_TRANSPORT_DSN") or dsn
            resolved_registry = OracleDatabaseRegistry(
                OracleConnectionSettings(
                    dsn=dsn,
                    transport_dsn=transport_dsn,
                    adm_user=os.environ.get("ORA_ADM_USER"),
                    adm_password=os.environ.get("ORA_ADM_PASS"),
                    app_user=os.environ.get("ORA_APP_USER") or os.environ.get("RDBMS_APP_USER"),
                    app_password=os.environ.get("ORA_APP_PASS") or os.environ.get("RDBMS_APP_PASS"),
                    use_wallet=os.environ.get("USE_ORACLE_WALLET", "").lower() in {"1", "true", "yes"},
                    thick_mode=os.environ.get("ORACLEDB_THICK_MODE", "").lower() in {"1", "true", "yes"},
                )
            )
            if resolved_repo_user is None:
                resolved_repo_user = os.environ.get("ORA_REPO_USER", "GOE_REPO")
    return OracleJobStore(
        connection_factory=connection_factory,
        registry=resolved_registry,
        repo_user=resolved_repo_user,
    )


@cache
def _get_sql_loader() -> SQLFileLoader:
    """Load and cache the SQLFileLoader for job_queue.sql."""
    loader = SQLFileLoader()
    loader.load_sql(JOB_QUEUE_SQL_PATH)
    return loader


def _ensure_utc(value: datetime | None) -> datetime:
    """Return value in UTC or the current UTC timestamp when None."""
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_ts(value: Any) -> datetime | None:
    """Convert an ISO string or datetime value from Oracle into a UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    parsed = datetime.fromisoformat(str(value))
    return _ensure_utc(parsed)


def _read_lob_or_str(value: Any) -> str | None:
    """Read an Oracle LOB or string column into a Python str."""
    if value is None:
        return None
    if hasattr(value, "read") and callable(value.read):
        return str(value.read())
    return str(value)


def _row_to_job_record(row: tuple[Any, ...]) -> JobRecord:
    """Hydrate a JobRecord from a 16-column SELECT row."""
    created_at = _parse_ts(row[14])
    updated_at = _parse_ts(row[15])
    assert created_at is not None
    assert updated_at is not None
    return JobRecord(
        job_id=str(row[0]),
        execution_id=str(row[1]),
        table_key=str(row[2]),
        status=JobState(str(row[3])),
        payload_json=_read_lob_or_str(row[4]) or "{}",
        attempt=int(row[5]),
        max_attempts=int(row[6]),
        worker_id=str(row[7]) if row[7] is not None else None,
        claimed_at=_parse_ts(row[8]),
        lease_expires_at=_parse_ts(row[9]),
        started_at=_parse_ts(row[10]),
        finished_at=_parse_ts(row[11]),
        error_message=_read_lob_or_str(row[12]),
        cancel_requested=bool(int(row[13])) if row[13] is not None else False,
        created_at=created_at,
        updated_at=updated_at,
    )


def _row_to_heartbeat(row: tuple[Any, ...]) -> NodeHeartbeat:
    """Hydrate a NodeHeartbeat from a 7-column SELECT row."""
    updated_at = _parse_ts(row[4])
    expires_at = _parse_ts(row[5])
    assert updated_at is not None
    assert expires_at is not None
    return NodeHeartbeat(
        endpoint_id=str(row[0]),
        listener_group_id=str(row[1]),
        host_url=str(row[2]),
        worker_role=str(row[3]),
        updated_at=updated_at,
        expires_at=expires_at,
        version=str(row[6]),
    )


def _is_oracle_unique_violation(exc: Exception) -> bool:
    """Return True when exc represents an Oracle unique constraint violation (ORA-00001)."""
    text = str(exc).upper()
    return "ORA-00001" in text or "GOE_LISTENER_JOBS_ACTIVE_TBL_UQ" in text
