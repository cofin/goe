# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Span helpers for GOE orchestration commands and steps."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from goe.observability.context import bind_execution_context, bind_step_context, get_current_trace_context
from goe.observability.runtime import get_observability_runtime, get_tracer
from goe.typing import BaseStruct

__all__ = (
    "TracedOperation",
    "add_span_log_event",
    "current_trace_ids",
    "record_skipped_step",
    "traced_command",
    "traced_step",
)


class TracedOperation(BaseStruct):
    """Outcome holder for a traced command or step."""

    span: Span
    status: str = "success"

    def fail(self, exc: BaseException) -> None:
        """Mark the operation failed and record ``exc`` on the span (idempotent)."""
        if self.status == "error":
            return
        self.status = "error"
        if self.span.is_recording():
            self.span.record_exception(exc)
            self.span.set_status(Status(StatusCode.ERROR, str(exc)))


@contextmanager
def traced_command(
    command_type: str,
    execution_id: Any | None,
    backend: str | None = None,
    dry_run: bool = False,
    source_owner: str | None = None,
    source_table: str | None = None,
) -> Iterator[TracedOperation]:
    """Bind execution context, run the block in ``goe.command.<type>``, and record command metrics."""
    started = time.perf_counter()
    with bind_execution_context(execution_id, command_type, source_owner, source_table):
        with get_tracer().start_as_current_span(
            f"goe.command.{(command_type or 'unknown').lower()}",
            kind=SpanKind.INTERNAL,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            operation = TracedOperation(span)
            if span.is_recording():
                span.set_attribute("goe.command.dry_run", dry_run)
                span.set_attribute("goe.backend.target", backend or "unknown")
            try:
                yield operation
            except BaseException as exc:
                operation.fail(exc)
                raise
            finally:
                if operation.status == "success" and span.is_recording():
                    span.set_status(Status(StatusCode.OK))
                get_observability_runtime().metrics.record_command(
                    command_type, operation.status, backend or "unknown", dry_run, time.perf_counter() - started
                )


@contextmanager
def traced_step(
    step_id: str,
    step_code: str,
    step_title: str,
    command_type: str | None = None,
    mandatory: bool = False,
    optional: bool = False,
    execute: bool = True,
) -> Iterator[TracedOperation]:
    """Bind ``step_id``, run the block in ``goe.step.<step_id>``, and record ``goe.steps.duration``."""
    started = time.perf_counter()
    with bind_step_context(step_id):
        with get_tracer().start_as_current_span(
            f"goe.step.{step_id}",
            kind=SpanKind.INTERNAL,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            operation = TracedOperation(span)
            if span.is_recording():
                span.set_attributes(
                    {
                        "goe.step.code": step_code,
                        "goe.step.title": step_title,
                        "goe.step.command_type": command_type or "unknown",
                        "goe.step.mandatory": mandatory,
                        "goe.step.optional": optional,
                        "goe.step.execute": execute,
                    }
                )
            try:
                yield operation
            except BaseException as exc:
                operation.fail(exc)
                raise
            finally:
                if span.is_recording():
                    span.set_attribute("goe.step.status", operation.status)
                    if operation.status == "success":
                        span.set_status(Status(StatusCode.OK))
                get_observability_runtime().metrics.record_step(
                    step_id, command_type or "unknown", operation.status, mandatory, time.perf_counter() - started
                )


def record_skipped_step(step_id: str, step_code: str, step_title: str, command_type: str | None = None) -> None:
    """Emit a zero-work ``goe.step.<step_id>`` span with status ``skipped``."""
    with bind_step_context(step_id):
        with get_tracer().start_as_current_span(f"goe.step.{step_id}", kind=SpanKind.INTERNAL) as span:
            if span.is_recording():
                span.set_attributes(
                    {"goe.step.code": step_code, "goe.step.title": step_title, "goe.step.status": "skipped"}
                )
    get_observability_runtime().metrics.record_step(step_id, command_type or "unknown", "skipped", False, 0.0)


def add_span_log_event(level: str, message: str) -> None:
    """Attach ``log.<level>`` with ``log.severity``/``log.message`` to the current recording span."""
    span = trace.get_current_span()
    if span.is_recording():
        span.add_event(f"log.{level.lower()}", attributes={"log.severity": level.upper(), "log.message": message})


def current_trace_ids() -> dict[str, str]:
    """Return ``{"_trace_id", "_span_id"}`` for the current valid span, or an empty dict."""
    snapshot = get_current_trace_context()
    if snapshot.trace_id is None or snapshot.span_id is None:
        return {}
    return {"_trace_id": snapshot.trace_id, "_span_id": snapshot.span_id}
