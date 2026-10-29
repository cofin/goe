# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Typed subprocess execution and sensitive-token redaction utilities."""

import shlex
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from goe.exceptions import OffloadException
from goe.typing import FrozenBaseStruct
from goe.util.string_utils import redact_text

__all__ = [
    "CommandResult",
    "SubprocessExecutionError",
    "run_checked_cmd",
]


class CommandResult(FrozenBaseStruct, frozen=True):
    """Immutable result of a completed local subprocess execution."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class SubprocessExecutionError(OffloadException):
    """Raised when a checked subprocess exits with a non-zero return code."""

    def __init__(
        self,
        args: tuple[str, ...],
        returncode: int,
        stdout: str,
        stderr: str,
        *,
        redact_tokens: Iterable[str] = (),
    ) -> None:
        token_list = tuple(t for t in redact_tokens if t)
        safe_cmd = redact_text(shlex.join(args), token_list)
        safe_stderr = redact_text(stderr.strip(), token_list)
        safe_stdout = redact_text(stdout.strip(), token_list)
        detail = safe_stderr or safe_stdout or "no output"
        super().__init__(f"Command {safe_cmd!r} failed with exit code {returncode}: {detail}")
        self.args_tuple = tuple(redact_text(arg, token_list) for arg in args)
        self.returncode = returncode
        self.stdout = safe_stdout
        self.stderr = safe_stderr


def run_checked_cmd(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    check: bool = True,
    input_text: str | None = None,
    redact_tokens: Iterable[str] = (),
) -> CommandResult:
    """Execute cmd without shell=True, returning a typed CommandResult."""
    args_tuple = tuple(str(part) for part in cmd)
    started = time.monotonic()
    completed = subprocess.run(
        args_tuple,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    duration = time.monotonic() - started
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if check and completed.returncode != 0:
        raise SubprocessExecutionError(
            args_tuple,
            completed.returncode,
            stdout,
            stderr,
            redact_tokens=redact_tokens,
        )
    return CommandResult(
        args=args_tuple,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
    )
