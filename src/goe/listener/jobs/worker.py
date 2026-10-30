# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Lease-renewing durable job worker, expired-lease reaper, and node heartbeat publisher."""

from __future__ import annotations

import asyncio
import inspect
import logging
import socket
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from goe.listener.jobs.models import JobCancelledError, JobRecord, JobState, NodeHeartbeat
from goe.listener.jobs.store import JobStoreProtocol
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.orchestration_runner import OrchestrationRunner
from goe.orchestration.sinks import ExecutionEvent, ExecutionSink

__all__ = (
    "DurableJobWorker",
    "_CooperativeCancelSink",
)

logger = logging.getLogger(__name__)


class DurableJobWorker:
    """Background worker that claims durable offload jobs, renews leases, and publishes node heartbeats."""

    def __init__(
        self,
        *,
        store: JobStoreProtocol,
        executor: Callable[..., Awaitable[Any] | Any] | None = None,
        worker_id: str | None = None,
        endpoint_id: str | None = None,
        listener_group_id: str = "default",
        host_url: str = "http://127.0.0.1:8000",
        worker_role: str = "all",
        version: str = "1.0.0",
        lease_seconds: int = 120,
        heartbeat_interval_seconds: float = 30.0,
        poll_interval_seconds: float = 1.0,
        max_concurrency: int = 2,
        sinks_factory: Callable[[JobRecord], tuple[Any, ...]] | None = None,
    ) -> None:
        hostname = socket.gethostname()
        default_id = f"{hostname}-{uuid4().hex[:8]}"
        self._store = store
        self._executor = executor or self._default_execute_job
        self._worker_id = worker_id or default_id
        self._endpoint_id = endpoint_id or self._worker_id
        self._listener_group_id = listener_group_id
        self._host_url = host_url
        self._worker_role = worker_role
        self._version = version
        self._lease_seconds = max(1, int(lease_seconds))
        self._heartbeat_interval_seconds = max(0.01, float(heartbeat_interval_seconds))
        self._poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._max_concurrency = max(1, int(max_concurrency))
        self._sinks_factory = sinks_factory
        self._stop_event = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def worker_id(self) -> str:
        """Return the unique identifier for this worker instance."""
        return self._worker_id

    @property
    def store(self) -> JobStoreProtocol:
        """Return the underlying durable job store."""
        return self._store

    async def process_once(self, *, now: datetime | None = None) -> list[JobRecord]:
        """Claim up to max_concurrency pending jobs and execute them with active lease renewal."""
        claimed = await asyncio.to_thread(
            self._store.claim_batch,
            worker_id=self._worker_id,
            limit=self._max_concurrency,
            lease_seconds=self._lease_seconds,
            now=now,
        )
        if not claimed:
            return []
        await asyncio.gather(*(self._run_claimed_job(record) for record in claimed))
        return claimed

    def reap_expired_leases(self, *, now: datetime | None = None) -> int:
        """Requeue expired leases with remaining attempts and dead-letter exhausted ones."""
        return self._store.reap_expired_leases(now=now)

    def publish_node_heartbeat(self, *, now: datetime | None = None) -> NodeHeartbeat:
        """Write or refresh this worker node's heartbeat row in the durable store."""
        ts = now if now is not None else datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ttl_seconds = max(float(self._lease_seconds), self._heartbeat_interval_seconds * 3.0)
        heartbeat = NodeHeartbeat(
            endpoint_id=self._endpoint_id,
            listener_group_id=self._listener_group_id,
            host_url=self._host_url,
            worker_role=self._worker_role,
            updated_at=ts,
            expires_at=ts + timedelta(seconds=ttl_seconds),
            version=self._version,
        )
        self._store.upsert_heartbeat(heartbeat)
        return heartbeat

    def start(self) -> None:
        """Start the background worker loop inside the current running event loop."""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        """Signal the worker loop to stop and wait for any in-flight tasks to finish."""
        self._stop_event.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None

    async def run_forever(self) -> None:
        """Run node heartbeats, expired-lease reaping, and job polling until stopped."""
        self._stop_event.clear()
        heartbeat_task = asyncio.create_task(self._periodic_maintenance_loop())
        try:
            while not self._stop_event.is_set():
                await self.process_once()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _run_claimed_job(self, record: JobRecord) -> None:
        """Transition record to RUNNING, maintain its lease during execution, and record terminal status."""
        await asyncio.to_thread(
            self._store.mark_running,
            job_id=record.job_id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        done_event = asyncio.Event()
        cancel_event = threading.Event()
        renewal_task = asyncio.create_task(
            self._lease_renewal_loop(record.job_id, record.execution_id, done_event, cancel_event)
        )
        try:
            outcome = self._invoke_executor(record, cancel_event)
            if inspect.isawaitable(outcome):
                await outcome
            if cancel_event.is_set():
                await asyncio.to_thread(
                    self._store.mark_cancelled,
                    job_id=record.job_id,
                    worker_id=self._worker_id,
                    reason="Cancelled by operator",
                )
            else:
                await asyncio.to_thread(
                    self._store.mark_succeeded,
                    job_id=record.job_id,
                    worker_id=self._worker_id,
                )
        except (JobCancelledError, asyncio.CancelledError) as exc:
            await asyncio.to_thread(
                self._store.mark_cancelled,
                job_id=record.job_id,
                worker_id=self._worker_id,
                reason=str(exc) or "Cancelled by operator",
            )
        except Exception as exc:
            if cancel_event.is_set():
                await asyncio.to_thread(
                    self._store.mark_cancelled,
                    job_id=record.job_id,
                    worker_id=self._worker_id,
                    reason=str(exc) or "Cancelled by operator",
                )
            else:
                logger.exception("Durable offload job %s (%s) failed", record.job_id, record.execution_id)
                dead_letter = record.attempt >= record.max_attempts
                await asyncio.to_thread(
                    self._store.mark_failed,
                    job_id=record.job_id,
                    worker_id=self._worker_id,
                    error_message=str(exc),
                    dead_letter=dead_letter,
                )
        finally:
            done_event.set()
            renewal_task.cancel()
            with suppress(asyncio.CancelledError):
                await renewal_task

    def _invoke_executor(self, record: JobRecord, cancel_event: threading.Event) -> Any:
        """Invoke self._executor with (record, cancel_event) when supported, or (record,) for 1-arg callables."""
        try:
            sig = inspect.signature(self._executor)
            pos_params = [
                p
                for p in sig.parameters.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
            if has_varargs or len(pos_params) >= 2:
                return self._executor(record, cancel_event)
        except (TypeError, ValueError):
            pass
        return self._executor(record)

    async def _lease_renewal_loop(
        self,
        job_id: str,
        execution_id: str,
        done_event: asyncio.Event,
        cancel_event: threading.Event,
    ) -> None:
        """Periodically extend the lease of an active job and check for cooperative cancellation."""
        while not done_event.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(done_event.wait(), timeout=self._heartbeat_interval_seconds)
            if done_event.is_set():
                return
            current = await asyncio.to_thread(self._store.get_job_by_execution_id, execution_id)
            if current is not None and (current.cancel_requested or current.status is JobState.CANCELLED):
                cancel_event.set()
                return
            await asyncio.to_thread(
                self._store.renew_lease,
                job_id=job_id,
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            )

    async def _periodic_maintenance_loop(self) -> None:
        """Publish node heartbeats and reap expired leases on heartbeat_interval_seconds."""
        while not self._stop_event.is_set():
            with suppress(Exception):
                await asyncio.to_thread(self.publish_node_heartbeat)
                await asyncio.to_thread(self.reap_expired_leases)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._heartbeat_interval_seconds)

    async def _default_execute_job(
        self,
        record: JobRecord,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Execute an offload or present job payload via OrchestrationRunner in a worker thread."""
        payload = record.decode_payload()
        command_type = str(payload.get("command_type", "offload")).lower()
        params = dict(payload.get("params", payload))
        base_sinks = list(self._sinks_factory(record)) if self._sinks_factory is not None else []
        if cancel_event is not None:
            base_sinks.append(_CooperativeCancelSink(cancel_event))
        sinks = tuple(base_sinks)
        execution_id_obj = ExecutionId.from_str(record.execution_id)

        def _invoke() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise JobCancelledError("Durable job cancelled before execution start")
            runner = OrchestrationRunner(sinks=sinks)
            present_fn = getattr(runner, "present", None)
            if command_type == "present" and callable(present_fn):
                present_fn(params, execution_id=execution_id_obj)
            else:
                runner.offload(params, execution_id=execution_id_obj)

        await asyncio.to_thread(_invoke)


class _CooperativeCancelSink(ExecutionSink):
    """ExecutionSink that checks a threading.Event on each event and raises JobCancelledError inside the worker."""

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event

    def emit(self, event: ExecutionEvent) -> None:
        """Raise JobCancelledError when cancellation has been requested."""
        if self._cancel_event.is_set():
            raise JobCancelledError("Durable job cancelled by operator")

    def close(self) -> None:
        """No-op close for stateless cooperative cancel sink."""
