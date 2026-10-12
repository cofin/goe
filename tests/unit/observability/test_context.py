# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for goe.observability.context."""

from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import TracerProvider
from sqlspec.utils.correlation import CorrelationContext

from goe.observability.context import (
    ATTR_COMMAND_TYPE,
    ATTR_EXECUTION_ID,
    ATTR_STEP_ID,
    bind_execution_context,
    bind_step_context,
    build_subprocess_trace_env,
    current_execution_attributes,
    extract_carrier,
    extract_env_context,
    format_w3c_traceparent,
    get_current_trace_context,
    inject_carrier,
)
from goe.orchestration.execution_id import ExecutionId


def test_bind_execution_context_sets_all_channels() -> None:
    execution_id = ExecutionId()
    with bind_execution_context(execution_id, command_type="OFFLOAD", source_owner="SH", source_table="SALES"):
        snapshot = get_current_trace_context()
        assert snapshot.execution_id == str(execution_id)
        assert snapshot.command_type == "OFFLOAD"
        assert baggage.get_baggage(ATTR_EXECUTION_ID) == str(execution_id)
        assert CorrelationContext.get() == str(execution_id)
        with bind_step_context("stage_data"):
            assert current_execution_attributes()[ATTR_STEP_ID] == "stage_data"
            assert baggage.get_baggage(ATTR_STEP_ID) == "stage_data"
        assert ATTR_STEP_ID not in current_execution_attributes()
    assert get_current_trace_context().execution_id is None
    assert CorrelationContext.get() is None


def test_traceparent_is_formatted_from_active_span() -> None:
    assert format_w3c_traceparent() is None
    with _tracer().start_as_current_span("parent") as span:
        ctx = span.get_span_context()
        traceparent = format_w3c_traceparent()
        assert traceparent == f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{int(ctx.trace_flags):02x}"


def test_dict_carrier_round_trip_preserves_parent() -> None:
    tracer = _tracer()
    with bind_execution_context("2f1b7c1e-0000-4000-8000-000000000001", command_type="OFFLOAD"):
        with tracer.start_as_current_span("producer") as producer:
            carrier = inject_carrier()
    assert "traceparent" in carrier
    assert "goe.execution.id" in carrier["baggage"]
    parent_ctx = extract_carrier(carrier)
    with tracer.start_as_current_span("consumer", context=parent_ctx) as consumer:
        assert consumer.get_span_context().trace_id == producer.get_span_context().trace_id
        assert consumer.parent.span_id == producer.get_span_context().span_id
        assert baggage.get_baggage(ATTR_COMMAND_TYPE, parent_ctx) == "OFFLOAD"


def test_subprocess_env_is_none_without_context() -> None:
    assert build_subprocess_trace_env({"PATH": "/bin"}) is None


def test_subprocess_env_round_trip() -> None:
    tracer = _tracer()
    with bind_execution_context("2f1b7c1e-0000-4000-8000-000000000002"):
        with tracer.start_as_current_span("cmd") as span:
            env = build_subprocess_trace_env({"PATH": "/bin"})
    assert env is not None
    assert env["PATH"] == "/bin"
    assert env["GOE_EXECUTION_ID"] == "2f1b7c1e-0000-4000-8000-000000000002"
    restored = trace.get_current_span(extract_env_context(env)).get_span_context()
    assert restored.trace_id == span.get_span_context().trace_id


def _tracer() -> trace.Tracer:
    """Return a recording tracer that is not installed globally."""
    return TracerProvider(shutdown_on_exit=False).get_tracer("test")
