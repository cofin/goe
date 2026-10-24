# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Bridge between GOE ExecutionId, W3C trace context, OpenTelemetry baggage, and SQLSpec correlation.

This module depends only on ``opentelemetry-api`` and ``sqlspec`` so it is safe to import when the optional SDK
is not installed. ContextVars hold the authoritative in-process values; baggage carries them across process and
queue boundaries; ``CorrelationContext`` tags SQLSpec statement spans and logs with the execution id.
"""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Any

from opentelemetry import baggage, context, propagate, trace
from opentelemetry.context import Context
from sqlspec.utils.correlation import CorrelationContext

from goe.typing import FrozenBaseStruct

__all__ = (
    "ATTR_COMMAND_TYPE",
    "ATTR_EXECUTION_ID",
    "ATTR_SOURCE_OWNER",
    "ATTR_SOURCE_TABLE",
    "ATTR_STEP_ID",
    "ExecutionTraceContext",
    "bind_execution_context",
    "bind_step_context",
    "build_subprocess_trace_env",
    "current_execution_attributes",
    "extract_carrier",
    "extract_env_context",
    "format_w3c_traceparent",
    "get_current_trace_context",
    "inject_carrier",
)

ATTR_EXECUTION_ID = "goe.execution.id"
ATTR_COMMAND_TYPE = "goe.command.type"
ATTR_STEP_ID = "goe.step.id"
ATTR_SOURCE_OWNER = "goe.source.owner"
ATTR_SOURCE_TABLE = "goe.source.table"

_EXECUTION_ID: ContextVar[str | None] = ContextVar("goe_execution_id", default=None)
_COMMAND_TYPE: ContextVar[str | None] = ContextVar("goe_command_type", default=None)
_STEP_ID: ContextVar[str | None] = ContextVar("goe_step_id", default=None)
_SOURCE_OWNER: ContextVar[str | None] = ContextVar("goe_source_owner", default=None)
_SOURCE_TABLE: ContextVar[str | None] = ContextVar("goe_source_table", default=None)

_ENV_TO_HEADER: dict[str, str] = {"TRACEPARENT": "traceparent", "TRACESTATE": "tracestate", "BAGGAGE": "baggage"}


class ExecutionTraceContext(FrozenBaseStruct, frozen=True, kw_only=True):
    """Snapshot of the bound GOE execution metadata and the current W3C span identity."""

    execution_id: str | None = None
    command_type: str | None = None
    step_id: str | None = None
    source_owner: str | None = None
    source_table: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    traceparent: str | None = None
    tracestate: str | None = None


@contextmanager
def bind_execution_context(
    execution_id: Any | None,
    command_type: str | None = None,
    source_owner: str | None = None,
    source_table: str | None = None,
) -> Iterator[ExecutionTraceContext]:
    """Bind command-level execution metadata for the duration of the block.

    ``execution_id`` accepts an ``ExecutionId``, a UUID string, or None (keep the currently bound id).
    """
    exec_str = str(execution_id) if execution_id is not None else _EXECUTION_ID.get()
    tokens = (
        _EXECUTION_ID.set(exec_str),
        _COMMAND_TYPE.set(command_type or _COMMAND_TYPE.get()),
        _SOURCE_OWNER.set(source_owner or _SOURCE_OWNER.get()),
        _SOURCE_TABLE.set(source_table or _SOURCE_TABLE.get()),
    )
    otel_ctx = context.get_current()
    if exec_str:
        otel_ctx = baggage.set_baggage(ATTR_EXECUTION_ID, exec_str, context=otel_ctx)
    if command_type:
        otel_ctx = baggage.set_baggage(ATTR_COMMAND_TYPE, command_type, context=otel_ctx)
    otel_token = context.attach(otel_ctx)
    correlation = CorrelationContext.context(exec_str) if exec_str else nullcontext()
    try:
        with correlation:
            yield get_current_trace_context()
    finally:
        context.detach(otel_token)
        _SOURCE_TABLE.reset(tokens[3])
        _SOURCE_OWNER.reset(tokens[2])
        _COMMAND_TYPE.reset(tokens[1])
        _EXECUTION_ID.reset(tokens[0])


@contextmanager
def bind_step_context(step_id: str) -> Iterator[ExecutionTraceContext]:
    """Bind the active orchestration step id for the duration of the block."""
    step_token = _STEP_ID.set(step_id)
    otel_token = context.attach(baggage.set_baggage(ATTR_STEP_ID, step_id, context=context.get_current()))
    try:
        yield get_current_trace_context()
    finally:
        context.detach(otel_token)
        _STEP_ID.reset(step_token)


def current_execution_attributes() -> dict[str, str]:
    """Return the bound execution metadata as span attributes, omitting unset values."""
    values = {
        ATTR_EXECUTION_ID: _EXECUTION_ID.get() or _baggage_str(ATTR_EXECUTION_ID),
        ATTR_COMMAND_TYPE: _COMMAND_TYPE.get() or _baggage_str(ATTR_COMMAND_TYPE),
        ATTR_STEP_ID: _STEP_ID.get() or _baggage_str(ATTR_STEP_ID),
        ATTR_SOURCE_OWNER: _SOURCE_OWNER.get(),
        ATTR_SOURCE_TABLE: _SOURCE_TABLE.get(),
    }
    return {key: value for key, value in values.items() if value}


def get_current_trace_context() -> ExecutionTraceContext:
    """Return a snapshot of the bound execution metadata and the current valid span, if any."""
    span_ctx = trace.get_current_span().get_span_context()
    trace_id = span_id = traceparent = tracestate = None
    if span_ctx.is_valid:
        trace_id = format(span_ctx.trace_id, "032x")
        span_id = format(span_ctx.span_id, "016x")
        traceparent = f"00-{trace_id}-{span_id}-{int(span_ctx.trace_flags):02x}"
        tracestate = span_ctx.trace_state.to_header() or None
    attributes = current_execution_attributes()
    return ExecutionTraceContext(
        execution_id=attributes.get(ATTR_EXECUTION_ID),
        command_type=attributes.get(ATTR_COMMAND_TYPE),
        step_id=attributes.get(ATTR_STEP_ID),
        source_owner=attributes.get(ATTR_SOURCE_OWNER),
        source_table=attributes.get(ATTR_SOURCE_TABLE),
        trace_id=trace_id,
        span_id=span_id,
        traceparent=traceparent,
        tracestate=tracestate,
    )


def format_w3c_traceparent() -> str | None:
    """Return the current W3C ``traceparent`` header value, or None when no valid span is active."""
    return get_current_trace_context().traceparent


def inject_carrier(carrier: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``carrier`` with the current context injected by the global propagator."""
    target: dict[str, str] = dict(carrier) if carrier is not None else {}
    propagate.inject(target)
    return target


def extract_carrier(carrier: Mapping[str, Any] | None) -> Context:
    """Extract an OpenTelemetry Context from a header-style carrier; return the current context when empty."""
    if not carrier:
        return context.get_current()
    return propagate.extract({str(key).lower(): str(value) for key, value in carrier.items() if value is not None})


def build_subprocess_trace_env(base_env: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """Return ``base_env`` (default ``os.environ``) plus TRACEPARENT/TRACESTATE/BAGGAGE/GOE_EXECUTION_ID.

    Returns None when there is no valid span and no bound execution id so callers can keep ``env=None``.
    """
    headers = inject_carrier()
    execution_id = _EXECUTION_ID.get()
    if "traceparent" not in headers and not execution_id:
        return None
    env = dict(base_env) if base_env is not None else dict(os.environ)
    for env_name, header_name in _ENV_TO_HEADER.items():
        if header_name in headers:
            env[env_name] = headers[header_name]
    if execution_id:
        env["GOE_EXECUTION_ID"] = execution_id
    return env


def extract_env_context(env: Mapping[str, str] | None = None) -> Context:
    """Extract an OpenTelemetry Context from TRACEPARENT/TRACESTATE/BAGGAGE environment variables."""
    source = env if env is not None else os.environ
    return extract_carrier({header: source[name] for name, header in _ENV_TO_HEADER.items() if name in source})


def _baggage_str(key: str) -> str | None:
    """Return a baggage entry from the current context as a string."""
    value = baggage.get_baggage(key)
    return str(value) if value is not None else None
