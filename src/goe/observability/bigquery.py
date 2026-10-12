# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""BigQuery job spans, trace-derived job labels, and job statistics metrics."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import SpanKind

from goe.observability.context import get_current_trace_context
from goe.observability.runtime import get_observability_runtime, get_tracer
from goe.observability.spans import TracedOperation

__all__ = (
    "bigquery_trace_labels",
    "merge_trace_labels",
    "record_bigquery_job_metadata",
    "traced_bigquery_job",
)

_JOB_ATTRIBUTES: tuple[str, ...] = (
    "job_id",
    "location",
    "project",
    "statement_type",
    "total_bytes_processed",
    "total_bytes_billed",
    "slot_millis",
    "num_dml_affected_rows",
    "output_rows",
    "output_bytes",
)


def bigquery_trace_labels() -> dict[str, str]:
    """Return raw ``goe_execution_id``/``goe_step``/``goe_trace_id`` values from the bound context."""
    snapshot = get_current_trace_context()
    values = {
        "goe_execution_id": snapshot.execution_id,
        "goe_step": snapshot.step_id,
        "goe_trace_id": snapshot.trace_id,
    }
    return {key: value for key, value in values.items() if value}


def merge_trace_labels(labels: Mapping[str, str], sanitize: Callable[[object], str]) -> dict[str, str]:
    """Return ``labels`` plus sanitized trace labels; keys already present in ``labels`` are kept."""
    merged = dict(labels)
    for key, value in bigquery_trace_labels().items():
        merged.setdefault(key, sanitize(value))
    return merged


@contextmanager
def traced_bigquery_job(operation: str, project: str | None) -> Iterator[TracedOperation]:
    """Run the block in a ``goe.backend.bigquery.<operation>`` CLIENT span."""
    attributes: dict[str, str] = {"db.system": "bigquery", "goe.bigquery.operation": operation}
    if project:
        attributes["goe.bigquery.project"] = project
    with get_tracer().start_as_current_span(
        f"goe.backend.bigquery.{operation}",
        kind=SpanKind.CLIENT,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        traced = TracedOperation(span)
        try:
            yield traced
        except BaseException as exc:
            traced.fail(exc)
            raise


def record_bigquery_job_metadata(traced: TracedOperation, job: Any, operation: str) -> None:
    """Copy job statistics from a QueryJob, LoadJob, or RowIterator onto the span and record BigQuery metrics."""
    if job is None:
        return
    values = {name: getattr(job, name, None) for name in _JOB_ATTRIBUTES}
    if traced.span.is_recording():
        for name, value in values.items():
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, str)):
                traced.span.set_attribute(f"goe.bigquery.{name}", value)
    bytes_billed = values["total_bytes_billed"]
    slot_millis = values["slot_millis"]
    get_observability_runtime().metrics.record_bigquery_job(
        operation,
        str(values["project"]) if isinstance(values["project"], str) else "unknown",
        bytes_billed if isinstance(bytes_billed, int) else None,
        slot_millis if isinstance(slot_millis, int) else None,
    )
