# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Span and metric helpers for GOE offload chunks, transport engines, batches, and OS commands."""

import contextvars
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Executor, Future
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from opentelemetry.trace import SpanKind

from goe.observability.context import build_subprocess_trace_env, get_current_trace_context
from goe.observability.runtime import get_observability_runtime, get_tracer
from goe.observability.spans import TracedOperation

__all__ = (
    "finalize_chunk",
    "finalize_transport",
    "inject_spark_trace_properties",
    "record_os_cmd_exit",
    "submit_with_context",
    "traced_offload_chunk",
    "traced_os_cmd",
    "traced_transport",
    "traced_transport_batch",
)


def traced_offload_chunk(chunk_number: int, target_db: str | None, target_table: str | None, dry_run: bool) -> Any:
    """Return a context manager spanning one offload chunk (``goe.chunk``)."""
    return _traced(
        "goe.chunk",
        SpanKind.INTERNAL,
        {
            "goe.chunk.number": chunk_number,
            "goe.target.db": target_db,
            "goe.target.table": target_table,
            "goe.chunk.dry_run": dry_run,
        },
    )


def finalize_chunk(
    operation: TracedOperation,
    backend: str,
    rows_staged: int | None,
    frontend_bytes: int | None,
    transport_bytes: int | None,
    backend_bytes: int | None,
) -> None:
    """Record chunk row/byte counts on the span and add ``goe.offload.bytes_loaded``."""
    if operation.span.is_recording():
        values = {
            "goe.chunk.rows_staged": rows_staged,
            "goe.chunk.frontend_bytes": frontend_bytes,
            "goe.chunk.transport_bytes": transport_bytes,
            "goe.chunk.backend_bytes": backend_bytes,
        }
        operation.span.set_attributes({key: value for key, value in values.items() if value is not None})
    get_observability_runtime().metrics.record_bytes_loaded(backend, backend_bytes)


def traced_transport(transport_method: str, attributes: Mapping[str, Any]) -> Any:
    """Return a context manager spanning one ``OffloadTransport.transport()`` call."""
    return _traced(f"goe.transport.{(transport_method or 'unknown').lower()}", SpanKind.CLIENT, attributes)


def finalize_transport(
    operation: TracedOperation,
    transport_method: str,
    backend: str,
    source_owner: str,
    rows: int | None,
    bytes_staged: int | None,
    staging_format: str | int | None,
    staging_location: str | int | None,
) -> None:
    """Record rows/bytes on the transport span and add transport metrics."""
    if operation.span.is_recording():
        values = {"goe.transport.rows_imported": rows, "goe.transport.bytes_staged": bytes_staged}
        operation.span.set_attributes({key: value for key, value in values.items() if value is not None})
    scheme = urlparse(str(staging_location)).scheme if staging_location else ""
    get_observability_runtime().metrics.record_transport(
        transport_method,
        backend,
        source_owner,
        rows,
        bytes_staged,
        str(staging_format) if staging_format else "unknown",
        scheme or "local",
    )


@contextmanager
def traced_os_cmd(cmd: Sequence[str]) -> Iterator[tuple[TracedOperation, dict[str, str] | None]]:
    """Span an external command and yield the subprocess env (None when telemetry is disabled)."""
    executable = os.path.basename(cmd[0]) if cmd else "unknown"
    with _traced(f"goe.os_cmd.{executable}", SpanKind.CLIENT, {"process.executable.name": executable}) as operation:
        env = build_subprocess_trace_env() if get_observability_runtime().enabled else None
        yield operation, env


def record_os_cmd_exit(operation: TracedOperation, returncode: int) -> None:
    """Record ``process.exit_code`` on an OS command span."""
    if operation.span.is_recording():
        operation.span.set_attribute("process.exit_code", returncode)


def inject_spark_trace_properties(spark_properties: dict[str, Any]) -> dict[str, Any]:
    """Return ``spark_properties`` plus ``spark.executorEnv.TRACEPARENT``/``GOE_EXECUTION_ID`` when enabled."""
    if not get_observability_runtime().enabled:
        return spark_properties
    snapshot = get_current_trace_context()
    enriched = dict(spark_properties)
    if snapshot.traceparent:
        enriched.setdefault("spark.executorEnv.TRACEPARENT", snapshot.traceparent)
    if snapshot.execution_id:
        enriched.setdefault("spark.executorEnv.GOE_EXECUTION_ID", snapshot.execution_id)
    return enriched


def traced_transport_batch(transport_method: str, batch_index: int) -> Any:
    """Return a context manager spanning one parallel transport batch."""
    return _traced(
        f"goe.transport.{(transport_method or 'unknown').lower()}.batch",
        SpanKind.INTERNAL,
        {"goe.transport.batch.index": batch_index},
    )


def submit_with_context[T](executor: Executor, fn: Callable[..., T], *args: Any) -> Future[T]:
    """Submit ``fn`` to ``executor`` inside a copy of the caller's context so spans keep their parent."""
    return executor.submit(contextvars.copy_context().run, fn, *args)


@contextmanager
def _traced(name: str, kind: SpanKind, attributes: Mapping[str, Any]) -> Iterator[TracedOperation]:
    """Run the block in a span named ``name`` and mark it failed if an exception escapes."""
    with get_tracer().start_as_current_span(
        name, kind=kind, record_exception=False, set_status_on_exception=False
    ) as span:
        operation = TracedOperation(span)
        if span.is_recording():
            span.set_attributes({key: value for key, value in attributes.items() if value is not None})
        try:
            yield operation
        except BaseException as exc:
            operation.fail(exc)
            raise
