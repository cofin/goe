# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for typed subprocess execution and sensitive-token redaction."""

import sys

import pytest

from goe.typing import FrozenBaseStruct
from goe.util.subprocess_utils import (
    CommandResult,
    SubprocessExecutionError,
    run_checked_cmd,
)


def test_run_checked_cmd_captures_output() -> None:
    """run_checked_cmd returns a FrozenBaseStruct CommandResult on success."""
    assert issubclass(CommandResult, FrozenBaseStruct)
    result = run_checked_cmd([sys.executable, "-c", "import sys; sys.stdout.write('ok')"])
    assert result.returncode == 0
    assert result.stdout == "ok"
    assert result.stderr == ""
    assert result.duration_seconds >= 0.0


def test_run_checked_cmd_redacts_secrets_on_failure() -> None:
    """run_checked_cmd raises SubprocessExecutionError with sensitive tokens redacted."""
    secret = "my_super_secret_token"
    with pytest.raises(SubprocessExecutionError) as exc_info:
        run_checked_cmd(
            [sys.executable, "-c", f"import sys; sys.stderr.write('{secret}'); sys.exit(2)"],
            redact_tokens=(secret,),
        )
    message = str(exc_info.value)
    assert secret not in message
    assert "***" in message
    assert exc_info.value.returncode == 2
