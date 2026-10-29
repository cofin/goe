# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Oracle and SQLite durable job stores for the GOE Listener."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from sqlspec.loader import SQLFileLoader

from goe.exceptions import GOEError
from goe.listener.jobs.models import (
    JobRecord,
    JobState,
    NodeHeartbeat,
    normalize_table_key,
)

__all__ = (
    "DuplicateActiveTableJobError",
    "JobStoreProtocol",
    "OracleJobStore",
    "SqliteJobStore",
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
    """Protocol implemented by OracleJobStore and SqliteJobStore."""

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

    def reap_expired_leases(self, *, now: datetime | None = None) -> int:
        """Requeue expired leases with remaining attempts and dead-letter exhausted ones."""

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


class SqliteJobStore:
    """Single-host SQLite WAL durable job store at $OFFLOAD_HOME/run/listener_jobs.sqlite3."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            offload_home = Path(os.environ.get("OFFLOAD_HOME", "/tmp/goe"))
            resolved_path: Path | str = offload_home / "run" / "listener_jobs.sqlite3"
        elif str(db_path) == ":memory:":
            resolved_path = ":memory:"
        else:
            resolved_path = Path(db_path)

        self._db_path = resolved_path
        self._lock = threading.RLock()
        self._loader = _get_sql_loader()
        self._persistent_conn: sqlite3.Connection | None = None
        if isinstance(self._db_path, Path):
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._initialize_schema()

    @property
    def db_path(self) -> Path | str:
        """Return the configured SQLite database file path or ':memory:'."""
        return self._db_path

    def journal_mode(self) -> str:
        """Return the active SQLite journal_mode pragma string."""
        with self._connect() as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]) if row else ""

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
        ts = _ensure_utc(now)
        record = JobRecord.create_pending(
            job_id=uuid4().hex,
            execution_id=execution_id,
            owner_table=owner_table,
            payload=payload,
            now=ts,
            max_attempts=max_attempts,
        )
        sql = self._sql("sqlite_insert_job")
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    sql,
                    {
                        "job_id": record.job_id,
                        "execution_id": record.execution_id,
                        "table_key": record.table_key,
                        "status": record.status.value,
                        "payload_json": record.payload_json,
                        "attempt": record.attempt,
                        "max_attempts": record.max_attempts,
                        "created_at": record.created_at.isoformat(),
                        "updated_at": record.updated_at.isoformat(),
                    },
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                existing = self.get_active_job_for_table(record.table_key)
                existing_exec_id = existing.execution_id if existing else None
                raise DuplicateActiveTableJobError(record.table_key, existing_exec_id) from exc
        return record

    def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int = 1,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> list[JobRecord]:
        """Atomically claim up to limit PENDING jobs for worker_id."""
        if limit <= 0:
            return []
        ts = _ensure_utc(now)
        lease_until = ts + timedelta(seconds=lease_seconds)
        select_sql = self._sql("sqlite_claim_pending_jobs")
        update_sql = self._sql("sqlite_mark_claimed")
        claimed: list[JobRecord] = []
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(select_sql, {"limit": limit}).fetchall()
                for row in rows:
                    pending = _row_to_job_record(row)
                    cursor = conn.execute(
                        update_sql,
                        {
                            "job_id": pending.job_id,
                            "worker_id": worker_id,
                            "claimed_at": ts.isoformat(),
                            "lease_expires_at": lease_until.isoformat(),
                            "updated_at": ts.isoformat(),
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
                            )
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
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
        sql = self._sql("sqlite_mark_running")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                sql,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "started_at": ts.isoformat(),
                    "lease_expires_at": lease_until.isoformat(),
                    "updated_at": ts.isoformat(),
                },
            )
            conn.commit()
            return cursor.rowcount == 1

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
        sql = self._sql("sqlite_renew_lease")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                sql,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "lease_expires_at": lease_until.isoformat(),
                    "updated_at": ts.isoformat(),
                },
            )
            conn.commit()
            return cursor.rowcount == 1

    def mark_succeeded(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime | None = None,
    ) -> bool:
        """Transition a running job to SUCCEEDED and clear its lease."""
        ts = _ensure_utc(now)
        sql = self._sql("sqlite_mark_terminal")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                sql,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "status": JobState.SUCCEEDED.value,
                    "finished_at": ts.isoformat(),
                    "error_message": None,
                    "updated_at": ts.isoformat(),
                },
            )
            conn.commit()
            return cursor.rowcount == 1

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
        sql = self._sql("sqlite_mark_terminal")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                sql,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "status": target_status.value,
                    "finished_at": ts.isoformat(),
                    "error_message": error_message,
                    "updated_at": ts.isoformat(),
                },
            )
            conn.commit()
            return cursor.rowcount == 1

    def reap_expired_leases(self, *, now: datetime | None = None) -> int:
        """Requeue expired leases with remaining attempts and dead-letter exhausted ones."""
        ts = _ensure_utc(now)
        now_iso = ts.isoformat()
        to_pending_sql = self._sql("sqlite_reap_expired_to_pending")
        to_dead_sql = self._sql("sqlite_reap_expired_to_dead_letter")
        with self._lock, self._connect() as conn:
            c1 = conn.execute(to_pending_sql, {"now": now_iso})
            c2 = conn.execute(to_dead_sql, {"now": now_iso})
            conn.commit()
            return int(max(0, c1.rowcount)) + int(max(0, c2.rowcount))

    def get_job_by_execution_id(self, execution_id: str) -> JobRecord | None:
        """Return the JobRecord for execution_id, or None when absent."""
        sql = self._sql("sqlite_get_job")
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, {"execution_id": execution_id}).fetchone()
            return _row_to_job_record(row) if row else None

    def get_active_job_for_table(self, owner_table: str) -> JobRecord | None:
        """Return the active JobRecord for owner_table, or None when unlocked."""
        table_key = normalize_table_key(owner_table)
        sql = self._sql("sqlite_get_active_job_for_table")
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, {"table_key": table_key}).fetchone()
            return _row_to_job_record(row) if row else None

    def list_jobs(self, *, limit: int = 100, status: JobState | None = None) -> list[JobRecord]:
        """List recent jobs ordered by created_at descending."""
        sql = self._sql("sqlite_list_jobs")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                sql,
                {"status": status.value if status else None, "limit": limit},
            ).fetchall()
            return [_row_to_job_record(row) for row in rows]

    def upsert_heartbeat(self, heartbeat: NodeHeartbeat) -> None:
        """Insert or update a Listener/worker node heartbeat row."""
        sql = self._sql("sqlite_upsert_heartbeat")
        with self._lock, self._connect() as conn:
            conn.execute(
                sql,
                {
                    "endpoint_id": heartbeat.endpoint_id,
                    "listener_group_id": heartbeat.listener_group_id,
                    "host_url": heartbeat.host_url,
                    "worker_role": heartbeat.worker_role,
                    "version": heartbeat.version,
                    "updated_at": heartbeat.updated_at.isoformat(),
                    "expires_at": heartbeat.expires_at.isoformat(),
                },
            )
            conn.commit()

    def list_active_heartbeats(self, *, now: datetime | None = None) -> list[NodeHeartbeat]:
        """Return non-expired node heartbeat rows."""
        ts = _ensure_utc(now)
        sql = self._sql("sqlite_list_active_heartbeats")
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, {"now": ts.isoformat()}).fetchall()
            return [_row_to_heartbeat(row) for row in rows]

    def _initialize_schema(self) -> None:
        """Configure WAL pragmas and create SQLite tables and indexes."""
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(self._sql("sqlite_ddl_jobs_table"))
            conn.execute(self._sql("sqlite_ddl_active_table_uq"))
            conn.execute(self._sql("sqlite_ddl_status_idx"))
            conn.execute(self._sql("sqlite_ddl_endpoints_table"))
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a SQLite connection configured with busy_timeout."""
        if self._persistent_conn is not None:
            yield self._persistent_conn
            return
        conn = sqlite3.connect(str(self._db_path), timeout=5.0, check_same_thread=False)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
        finally:
            conn.close()

    def _sql(self, query_name: str) -> str:
        """Return raw SQL text for query_name without trailing semicolon."""
        return self._loader.get_sql(query_name).raw_sql.strip().removesuffix(";").rstrip()


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
            logger.debug("Oracle GOE_LISTENER_JOBS probe failed; falling back to SQLite", exc_info=True)
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

    def reap_expired_leases(self, *, now: datetime | None = None) -> int:
        """Requeue expired leases with remaining attempts and dead-letter exhausted ones."""
        ts = _ensure_utc(now)
        to_pending_sql = self._sql("oracle_reap_expired_to_pending")
        to_dead_sql = self._sql("oracle_reap_expired_to_dead_letter")
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(to_pending_sql, {"now": ts})
                requeued = int(max(0, cursor.rowcount))
                cursor.execute(to_dead_sql, {"now": ts})
                dead = int(max(0, cursor.rowcount))
                conn.commit()
                return requeued + dead
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
    sqlite_path: Path | str | None = None,
    offload_home: Path | str | None = None,
) -> JobStoreProtocol:
    """Auto-detect OracleJobStore when GOE_LISTENER_JOBS is installed, else fallback to SqliteJobStore."""
    if registry is not None or connection_factory is not None:
        oracle_store = OracleJobStore(
            connection_factory=connection_factory,
            registry=registry,
            repo_user=repo_user,
        )
        if oracle_store.probe_tables():
            return oracle_store

    if sqlite_path is not None:
        resolved_sqlite: Path | str = sqlite_path
    else:
        base_home = Path(offload_home) if offload_home is not None else Path(os.environ.get("OFFLOAD_HOME", "/tmp/goe"))
        resolved_sqlite = base_home / "run" / "listener_jobs.sqlite3"
    return SqliteJobStore(db_path=resolved_sqlite)


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
    """Convert an ISO string or datetime value from SQLite/Oracle into a UTC datetime."""
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
    """Hydrate a JobRecord from a 15-column SELECT row."""
    created_at = _parse_ts(row[13])
    updated_at = _parse_ts(row[14])
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
