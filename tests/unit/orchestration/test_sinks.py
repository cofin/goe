# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe.orchestration.sinks."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from goe.orchestration import orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.sinks import (
    NORMAL,
    QUIET,
    SUPPRESS_STDOUT,
    VERBOSE,
    VVERBOSE,
    ConsoleSink,
    LogEvent,
    LogFileSink,
    RepositoryStepSink,
    StepFinishedEvent,
    StepSkippedEvent,
    TelemetrySink,
    WarningEvent,
)


def test_console_sink_filters_by_detail_and_renders_ansi() -> None:
    """Verify ConsoleSink writes only events matching detail threshold and wraps ANSI codes."""
    buf = io.StringIO()
    sink = ConsoleSink(detail=NORMAL, ansi=True, stream=buf)
    sink.emit(LogEvent(line="ok", detail=NORMAL, ansi_code="green"))
    sink.emit(LogEvent(line="skip-verbose", detail=VERBOSE))
    sink.emit(WarningEvent(line="careful", ansi_code="yellow"))
    sink.close()

    output = buf.getvalue()
    assert "\033[92mok\033[0m\n" in output
    assert "skip-verbose" not in output
    assert "\033[93mWARNING:careful\033[0m\n" in output


def test_console_sink_suppress_stdout_and_quiet() -> None:
    """Verify ConsoleSink suppresses stdout on SUPPRESS_STDOUT and writes dots on QUIET."""
    buf_suppressed = io.StringIO()
    sink_suppressed = ConsoleSink(detail=SUPPRESS_STDOUT, ansi=False, stream=buf_suppressed)
    sink_suppressed.emit(LogEvent(line="hidden", detail=NORMAL))
    sink_suppressed.emit(WarningEvent(line="hidden-warn"))
    assert buf_suppressed.getvalue() == ""

    buf_quiet = io.StringIO()
    sink_quiet = ConsoleSink(detail=QUIET, ansi=False, stream=buf_quiet)
    sink_quiet.emit(LogEvent(line="quiet-line", detail=NORMAL))
    assert buf_quiet.getvalue() == ".\n"


def test_log_file_sink_writes_entries(tmp_path: Path) -> None:
    """Verify LogFileSink records log and warning events into a dedicated file."""
    sink = LogFileSink.open_for_prefix(
        str(tmp_path),
        "SH.TEST",
        detail=NORMAL,
        ansi=False,
        write_all_details=False,
    )
    try:
        sink.emit(LogEvent(line="normal-entry", detail=NORMAL, timestamp_str="2026-10-24 12:00:00"))
        sink.emit(LogEvent(line="verbose-entry", detail=VERBOSE))
        sink.emit(LogEvent(line="vverbose-entry", detail=VVERBOSE))
        sink.emit(WarningEvent(line="file-warn"))
    finally:
        sink.close()

    assert sink.name is not None
    content = Path(sink.name).read_text(encoding="utf-8")
    assert "2026-10-24 12:00:00: normal-entry\n" in content
    assert "verbose-entry\n" in content
    assert "vverbose-entry" not in content
    assert "WARNING:file-warn\n" in content


def test_telemetry_sink_forwards_span_events() -> None:
    """Verify TelemetrySink forwards LogEvent(emit_span_event=True) and StepSkippedEvent."""
    sink = TelemetrySink()
    with (
        patch("goe.orchestration.sinks.add_span_log_event") as mock_add,
        patch("goe.orchestration.sinks.record_skipped_step") as mock_skip,
    ):
        sink.emit(LogEvent(line="milestone", detail=NORMAL, emit_span_event=True, span_event_level="INFO"))
        sink.emit(LogEvent(line="ignored", detail=NORMAL, emit_span_event=False))
        sink.emit(StepSkippedEvent(step_id="s1", step_code="S1", step_title="Step 1", command_type="OFFLOAD"))

    mock_add.assert_called_once_with("INFO", "milestone")
    mock_skip.assert_called_once_with("s1", "S1", "Step 1", command_type="OFFLOAD")


def test_repository_step_sink_records_start_and_finish() -> None:
    """Verify RepositoryStepSink delegates start_command_step and end_command_step to repo_client."""
    repo = MagicMock()
    repo.start_command_step.return_value = 77
    exec_id = ExecutionId()
    sink = RepositoryStepSink(repo, execution_id=exec_id, command_type=orchestration_constants.COMMAND_OFFLOAD)
    step_id = sink.start_step("STAGING_TRANSPORT")
    assert step_id == 77
    sink.emit(
        StepFinishedEvent(
            step_id="staging_transport",
            step_title="Transport data to staging",
            status=orchestration_constants.COMMAND_SUCCESS,
            command_step_id=77,
            step_details={"rows": 5},
        )
    )
    repo.start_command_step.assert_called_once_with(
        exec_id,
        orchestration_constants.COMMAND_OFFLOAD,
        "STAGING_TRANSPORT",
    )
    repo.end_command_step.assert_called_once_with(
        77,
        orchestration_constants.COMMAND_SUCCESS,
        step_details={"rows": 5},
    )
