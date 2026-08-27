# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from datetime import timedelta

import pytest

from goe.config import orchestration_defaults
from goe.offload.offload_messages import (
    VERBOSE,
    VVERBOSE,
    OffloadMessages,
    OffloadMessagesForcedException,
)
from goe.orchestration import command_steps, orchestration_constants
from goe.util.goe_log_fh import GOELogFileHandle


class FakeOpts:
    def __init__(self, option_modifiers=None):
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

    def as_dict(self):
        return vars(self)


def _std_messages_actions(messages):
    """Shake down messages calls.
    It would be better if we actually checked what was written a log file vs stdout but, at the moment,
    all we are doing is ensuring no unexpected exceptions.
    """
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


def test_from_options():
    log_file = "/tmp/test_from_options.tmp"
    with GOELogFileHandle(log_file) as fh:
        messages = OffloadMessages.from_options(FakeOpts(), log_fh=fh)
        _std_messages_actions(messages)


def test_from_options_dict():
    log_file = "/tmp/test_from_options_dict.tmp"
    with GOELogFileHandle(log_file) as fh:
        messages = OffloadMessages.from_options_dict(FakeOpts().as_dict(), log_fh=fh)
        _std_messages_actions(messages)


def test_step_delta():
    log_file = "/tmp/test_step_delta.tmp"
    with GOELogFileHandle(log_file) as fh:
        messages = OffloadMessages.from_options(FakeOpts(), log_fh=fh)
        messages.step_delta("Normal Stuff", timedelta(0, 160, 615919))
        messages.log("Honk honk", ansi_code="red")
        messages.step_delta("Bad Stuff", timedelta(0, 130, 651717))
        messages.warning("Honk honk", ansi_code="red")
        messages.step_delta("Bad Stuff", timedelta(0, 9101, 651717))
        messages.log_step_deltas()


def test_offload_step():
    def do_nothing():
        pass

    def do_divzero():
        return 1 / 0

    with open("/dev/null", "a") as fh:
        # Sanity check with no modifiers, all steps recorded
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
        # Now check that step interaction works
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
        # Normal step should be recorded in steps
        messages.offload_step(
            command_steps.STEP_MESSAGES,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        assert messages_title in messages.steps
        # Skipped step should not be in recorded steps
        messages.offload_step(
            command_steps.STEP_UNITTEST_SKIP,
            do_nothing,
            command_type=orchestration_constants.COMMAND_TEST,
        )
        assert skip_title not in messages.steps
        # Check test assertion thrown
        with pytest.raises(OffloadMessagesForcedException) as _:
            messages.offload_step(
                command_steps.STEP_UNITTEST_ERROR_BEFORE,
                do_nothing,
                command_type=orchestration_constants.COMMAND_TEST,
            )
        assert error_before_title not in messages.steps
        with pytest.raises(OffloadMessagesForcedException) as _:
            messages.offload_step(
                command_steps.STEP_UNITTEST_ERROR_AFTER,
                do_nothing,
                command_type=orchestration_constants.COMMAND_TEST,
            )
        assert error_after_title in messages.steps
        # Check flow when a genuine exception is encountered, we should still get that exception and
        # not suffer a subsequent issue in our handling code
        with pytest.raises(ZeroDivisionError) as _:
            messages.offload_step(
                command_steps.STEP_MESSAGES,
                do_divzero,
                command_type=orchestration_constants.COMMAND_TEST,
            )
