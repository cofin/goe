# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for OffloadMessages step telemetry and OrchestrationRunner command metadata."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.spans import traced_command
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration import command_steps, orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.orchestration_runner import OrchestrationRunner

EXEC_ID = "2f1b7c1e-0000-4000-8000-000000000020"


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime for one test."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_step_span_and_repo_trace_ids(memory_runtime: runtime.ObservabilityRuntime) -> None:
    repo_client = MagicMock()
    messages = _messages(repo_client)
    with traced_command(orchestration_constants.COMMAND_OFFLOAD, EXEC_ID):
        assert messages.offload_step(command_steps.STEP_STAGING_TRANSPORT, lambda: 42) == 42
    spans = {span.name: span for span in memory_runtime.get_finished_spans()}
    step_name = next(name for name in spans if name.startswith("goe.step."))
    assert spans[step_name].parent.span_id == spans["goe.command.offload"].get_span_context().span_id
    step_details = repo_client.end_command_step.call_args.kwargs["step_details"]
    assert step_details["_trace_id"] == format(spans[step_name].get_span_context().trace_id, "032x")


def test_optional_failure_marks_step_error(memory_runtime: runtime.ObservabilityRuntime) -> None:
    messages = _messages(MagicMock())
    messages.offload_step(command_steps.STEP_STAGING_TRANSPORT, _fail, optional=True)
    step = next(span for span in memory_runtime.get_finished_spans() if span.name.startswith("goe.step."))
    assert step.attributes["goe.step.status"] == "error"
    assert any(event.name == "log.warning" for event in step.events)


def test_skipped_step_span(memory_runtime: runtime.ObservabilityRuntime) -> None:
    step_id = "transport_data_to_staging"
    messages = _messages(MagicMock(), skip=[step_id])
    assert messages.offload_step(command_steps.STEP_STAGING_TRANSPORT, lambda: 1) is None
    step = next(span for span in memory_runtime.get_finished_spans() if span.name.startswith("goe.step."))
    assert step.attributes["goe.step.status"] == "skipped"


def test_disabled_runtime_keeps_repo_call_unchanged() -> None:
    runtime.shutdown_observability()
    repo_client = MagicMock()
    _messages(repo_client).offload_step(command_steps.STEP_STAGING_TRANSPORT, lambda: None)
    repo_client.end_command_step.assert_called_once_with(
        repo_client.start_command_step.return_value, orchestration_constants.COMMAND_SUCCESS
    )


def test_runner_command_begin_enriches_trace_ids(memory_runtime: runtime.ObservabilityRuntime) -> None:
    runner = OrchestrationRunner.__new__(OrchestrationRunner)
    runner._execution_id = ExecutionId.from_str(EXEC_ID)
    runner._messages = None
    repo_client = MagicMock()
    repo_client.start_command.return_value = 99
    with traced_command(orchestration_constants.COMMAND_OFFLOAD, EXEC_ID):
        assert (
            runner._command_begin(
                orchestration_constants.COMMAND_OFFLOAD,
                {"owner_table": "SH.SALES"},
                repo_client,
                {"owner_table": "SH.SALES"},
            )
            == 99
        )
    passed_dict = repo_client.start_command.call_args.args[3]
    assert "_trace_id" in passed_dict
    assert "_span_id" in passed_dict


def _messages(repo_client: MagicMock, skip: list[str] | None = None) -> OffloadMessages:
    """Build OffloadMessages with a mocked repo client."""
    return OffloadMessages(
        repo_client=repo_client,
        command_type=orchestration_constants.COMMAND_OFFLOAD,
        execution_id=EXEC_ID,
        skip=skip,
    )


def _fail() -> None:
    """Raise a RuntimeError for optional step testing."""
    raise RuntimeError("optional boom")
