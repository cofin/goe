# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OffloadMessages console formatting, log routing, and step instrumentation."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from goe.config import orchestration_defaults
from goe.offload.offload_messages import (
    NORMAL,
    QUIET,
    SUPPRESS_STDOUT,
    VERBOSE,
    VVERBOSE,
    OffloadMessages,
    OffloadMessagesForcedException,
    ansi_wrap,
)
from goe.orchestration import command_steps, orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.util.goe_log_fh import GOELogFileHandle


class FakeOpts:
    """Test helper replicating orchestration option flags for OffloadMessages.from_options."""

    def __init__(self, option_modifiers: dict[str, Any] | None = None) -> None:
        if option_modifiers:
            assert isinstance(option_modifiers, dict)

        self.quiet = orchestration_defaults.quiet_default()
        self.verbose = orchestration_defaults.verbose_default()
        self.vverbose = orchestration_defaults.vverbose_default()
        self.ansi = orchestration_defaults.ansi_default()
        self.suppress_stdout = orchestration_defaults.suppress_stdout_default()

        if option_modifiers:
            for k, v in option_modifiers.items():
                setattr(self, k, v)

    def as_dict(self) -> dict[str, Any]:
        """Return a dictionary view of option attributes."""
        return vars(self)


def test_from_options(tmp_path: Path) -> None:
    """Verify OffloadMessages.from_options exercises standard message actions without error."""
    log_file = str(tmp_path / "test_from_options.tmp")
    with GOELogFileHandle(log_file) as fh:
        messages = OffloadMessages.from_options(FakeOpts(), log_fh=fh)
        _std_messages_actions(messages)


def test_from_options_dict(tmp_path: Path) -> None:
    """Verify OffloadMessages.from_options_dict exercises standard message actions without error."""
    log_file = str(tmp_path / "test_from_options_dict.tmp")
    with GOELogFileHandle(log_file) as fh:
        messages = OffloadMessages.from_options_dict(FakeOpts().as_dict(), log_fh=fh)
        _std_messages_actions(messages)


def test_step_delta(tmp_path: Path) -> None:
    """Verify step_delta and log_step_deltas accumulate and format step timings."""
    log_file = str(tmp_path / "test_step_delta.tmp")
    with GOELogFileHandle(log_file) as fh:
        messages = OffloadMessages.from_options(FakeOpts(), log_fh=fh)
        messages.step_delta("Normal Stuff", timedelta(0, 160, 615919))
        messages.log("Honk honk", ansi_code="red")
        messages.step_delta("Bad Stuff", timedelta(0, 130, 651717))
        messages.warning("Honk honk", ansi_code="red")
        messages.step_delta("Bad Stuff", timedelta(0, 9101, 651717))
        messages.log_step_deltas()


def test_offload_step() -> None:
    """Verify offload_step execution, skipping, forced before/after errors, and exception propagation."""

    def do_nothing() -> None:
        pass

    def do_divzero() -> float:
        return 1 / 0

    with open("/dev/null", "a", encoding="utf-8") as fh:
        messages = OffloadMessages.from_options(FakeOpts(), log_fh=fh)
        messages.offload_step(
            command_steps.STEP_MESSAGES,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        messages.offload_step(
            command_steps.STEP_UNITTEST_SKIP,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        messages.offload_step(
            command_steps.STEP_UNITTEST_ERROR_BEFORE,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        messages.offload_step(
            command_steps.STEP_UNITTEST_ERROR_AFTER,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        messages_title = command_steps.step_title(command_steps.STEP_MESSAGES)
        skip_title = command_steps.step_title(command_steps.STEP_UNITTEST_SKIP)
        error_before_title = command_steps.step_title(command_steps.STEP_UNITTEST_ERROR_BEFORE)
        error_after_title = command_steps.step_title(command_steps.STEP_UNITTEST_ERROR_AFTER)
        messages = OffloadMessages.from_options(FakeOpts(), log_fh=fh)
        messages.setup_offload_step(
            skip=[skip_title.replace(" ", "_").lower()],
            error_before_step=error_before_title.replace(" ", "_").lower(),
            error_after_step=error_after_title.replace(" ", "_").lower(),
        )
        messages.offload_step(
            command_steps.STEP_MESSAGES,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        assert messages_title in messages.steps
        messages.offload_step(
            command_steps.STEP_UNITTEST_SKIP,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        assert skip_title not in messages.steps
        with pytest.raises(OffloadMessagesForcedException):
            messages.offload_step(
                command_steps.STEP_UNITTEST_ERROR_BEFORE,
                do_nothing,
                command_type=orchestration_constants.COMMAND_TEST,
            )
        assert error_before_title not in messages.steps
        with pytest.raises(OffloadMessagesForcedException):
            messages.offload_step(
                command_steps.STEP_UNITTEST_ERROR_AFTER,
                do_nothing,
                command_type=orchestration_constants.COMMAND_TEST,
            )
        assert error_after_title in messages.steps
        with pytest.raises(ZeroDivisionError):
            messages.offload_step(
                command_steps.STEP_MESSAGES,
                do_divzero,
                command_type=orchestration_constants.COMMAND_TEST,
            )


def test_ansi_wrap_colors() -> None:
    """Verify ANSI escape sequences wrap single and sequence color codes."""
    assert ansi_wrap("hello", "green") == "\033[92mhello\033[0m"
    assert ansi_wrap("warn", ["bold", "yellow"]) == "\033[1m\033[93mwarn\033[0m"
    assert ansi_wrap("plain", None) == "plain"
    assert OffloadMessages.ansi_wrap("plain", "green", False) == "plain"


@pytest.mark.parametrize(
    ("verbosity", "detail", "expected_stdout", "expected_file"),
    [
        (SUPPRESS_STDOUT, NORMAL, False, True),
        (NORMAL, NORMAL, True, True),
        (NORMAL, VERBOSE, False, True),
        (NORMAL, VVERBOSE, False, True),
        (VERBOSE, VERBOSE, True, True),
        (VERBOSE, VVERBOSE, False, True),
        (VVERBOSE, VVERBOSE, True, True),
    ],
)
def test_offload_messages_log_verbosity_matrix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    verbosity: int,
    detail: int,
    expected_stdout: bool,
    expected_file: bool,
) -> None:
    """Verify console and file output routing across all verbosity and detail combinations."""
    log_path = tmp_path / "matrix.log"
    fh = GOELogFileHandle(str(log_path), mode="w")
    try:
        msgs = OffloadMessages(detail=verbosity, ansi=False, log_fh=fh)
        msgs.log("payload-line", detail=detail)
    finally:
        fh.close()

    captured = capsys.readouterr().out
    file_text = log_path.read_text(encoding="utf-8")
    assert ("payload-line\n" in captured) is expected_stdout
    assert ("payload-line\n" in file_text) is expected_file


def test_offload_messages_quiet_emits_dots_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify QUIET verbosity writes progress dots to stdout."""
    msgs = OffloadMessages(detail=QUIET, ansi=False)
    msgs.log("step-one", detail=NORMAL)
    assert capsys.readouterr().out == ".\n"


def test_offload_messages_notice_warning_debug_routing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify notices, warnings, and debug messages route to buffers, console, and log files."""
    log_path = tmp_path / "routing.log"
    fh = GOELogFileHandle(str(log_path), mode="w")
    try:
        msgs = OffloadMessages(detail=VERBOSE, ansi=False, log_fh=fh)
        msgs.notice("notice-one")
        msgs.warning("warn-one", ansi_code="red")
        msgs.debug("dbg-one")
    finally:
        fh.close()

    out = capsys.readouterr().out
    file_text = log_path.read_text(encoding="utf-8")
    assert msgs.get_notices() == ["notice-one"]
    assert msgs.get_warnings() == ["warn-one"]
    assert "notice-one\n" in out
    assert "WARNING:warn-one\n" in out
    assert "dbg-one" not in out
    assert "WARNING:warn-one\n" in file_text


def test_offload_messages_offload_step_console_and_log_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify offload_step formats titles, timestamps, Done markers, and repository step calls."""
    log_path = tmp_path / "steps.log"
    repo_client = MagicMock()
    repo_client.start_command_step.return_value = 42
    exec_id = ExecutionId()
    fh = GOELogFileHandle(str(log_path), mode="w")
    try:
        msgs = OffloadMessages(
            detail=VERBOSE,
            ansi=False,
            log_fh=fh,
            execution_id=exec_id,
            repo_client=repo_client,
            command_type=orchestration_constants.COMMAND_OFFLOAD,
        )
        result = msgs.offload_step(
            command_steps.STEP_VERIFY_EXPORTED_DATA,
            lambda: "step-result",
            execute=True,
        )
    finally:
        fh.close()

    assert result == "step-result"
    out = capsys.readouterr().out
    assert "Verify exported data\n" in out
    assert "Step time:" in out
    assert "Done\n" in out
    repo_client.start_command_step.assert_called_once_with(
        exec_id,
        orchestration_constants.COMMAND_OFFLOAD,
        command_steps.STEP_VERIFY_EXPORTED_DATA,
    )
    repo_client.end_command_step.assert_called_once_with(
        42,
        orchestration_constants.COMMAND_SUCCESS,
    )


def _std_messages_actions(messages: OffloadMessages) -> None:
    """Exercise standard OffloadMessages log, info, debug, notice, warning, and event calls."""
    messages.log("msg")
    messages.log("vmsg", detail=VERBOSE)
    messages.log("vvmsg", detail=VVERBOSE)
    messages.info("info", detail=VVERBOSE)
    messages.info("vinfo", detail=VERBOSE)
    messages.info("vvinfo", detail=VVERBOSE)
    messages.debug("debug", detail=VVERBOSE)
    messages.debug("vdebug", detail=VERBOSE)
    messages.debug("vvdebug", detail=VVERBOSE)
    messages.notice("a-notice")
    assert "a-notice" in messages.get_notices()
    assert "a-notice" in messages.get_messages()
    messages.warning("a-warning")
    assert "a-warning" in messages.get_warnings()
    assert "a-warning" in messages.get_messages()
    messages.warning("Honk honk", ansi_code="red")
    messages.event("an-event")
    assert "an-event" in messages.get_events()
