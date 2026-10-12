# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for goe.observability.spans."""

from collections.abc import Iterator

import pytest
from opentelemetry.trace import StatusCode

from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.spans import (
    add_span_log_event,
    current_trace_ids,
    record_skipped_step,
    traced_command,
    traced_step,
)

EXEC_ID = "2f1b7c1e-0000-4000-8000-000000000010"


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime for one test."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_command_and_step_hierarchy(memory_runtime: runtime.ObservabilityRuntime) -> None:
    with traced_command("OFFLOAD", EXEC_ID, backend="bigquery", source_owner="SH", source_table="SALES"):
        with traced_step("stage_data", "STAGE_DATA", "Stage data", command_type="OFFLOAD", mandatory=True):
            assert set(current_trace_ids()) == {"_trace_id", "_span_id"}
            add_span_log_event("WARNING", "sample warning")
    spans = _by_name(memory_runtime)
    command = spans["goe.command.offload"]
    step = spans["goe.step.stage_data"]
    assert step.parent.span_id == command.get_span_context().span_id
    assert step.attributes["goe.execution.id"] == EXEC_ID
    assert step.attributes["goe.step.status"] == "success"
    assert command.attributes["goe.source.table"] == "SALES"
    assert step.events[0].name == "log.warning"


def test_failed_step_marks_error_once(memory_runtime: runtime.ObservabilityRuntime) -> None:
    with pytest.raises(ValueError):
        with traced_command("OFFLOAD", EXEC_ID):
            with traced_step("stage_data", "STAGE_DATA", "Stage data") as step_op:
                exc = ValueError("boom")
                step_op.fail(exc)
                raise exc
    spans = _by_name(memory_runtime)
    step = spans["goe.step.stage_data"]
    assert step.status.status_code == StatusCode.ERROR
    assert step.attributes["goe.step.status"] == "error"
    assert [event.name for event in step.events].count("exception") == 1
    assert spans["goe.command.offload"].status.status_code == StatusCode.ERROR


def test_swallowed_failure_still_marks_error(memory_runtime: runtime.ObservabilityRuntime) -> None:
    with traced_step("verify", "VERIFY", "Verify") as step_op:
        step_op.fail(RuntimeError("optional failure"))
    assert _by_name(memory_runtime)["goe.step.verify"].attributes["goe.step.status"] == "error"


def test_skipped_step(memory_runtime: runtime.ObservabilityRuntime) -> None:
    record_skipped_step("stage_data", "STAGE_DATA", "Stage data", command_type="OFFLOAD")
    assert _by_name(memory_runtime)["goe.step.stage_data"].attributes["goe.step.status"] == "skipped"


def test_disabled_runtime_is_silent() -> None:
    runtime.shutdown_observability()
    with traced_command("OFFLOAD", EXEC_ID):
        with traced_step("stage_data", "STAGE_DATA", "Stage data"):
            assert current_trace_ids() == {}


def _by_name(active: runtime.ObservabilityRuntime) -> dict:
    """Return finished spans keyed by name."""
    return {span.name: span for span in active.get_finished_spans()}
