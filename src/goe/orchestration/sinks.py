# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Structured execution sinks for console, file, telemetry, and repository step output."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, TextIO, runtime_checkable

from goe.observability.spans import add_span_log_event, record_skipped_step
from goe.typing import FrozenBaseStruct
from goe.util.goe_log_fh import GOELogFileHandle
from goe.util.string_utils import standard_log_name

if TYPE_CHECKING:
    from goe.orchestration.execution_id import ExecutionId

__all__ = [
    "COLORS",
    "NORMAL",
    "QUIET",
    "SUPPRESS_STDOUT",
    "VERBOSE",
    "VERBOSENESS",
    "VVERBOSE",
    "ConsoleSink",
    "ExecutionEvent",
    "ExecutionSink",
    "ExecutionSinkProtocol",
    "LogEvent",
    "LogFileSink",
    "RepositoryStepSink",
    "StepFinishedEvent",
    "StepSkippedEvent",
    "StepStartedEvent",
    "TelemetrySink",
    "WarningEvent",
    "ansi_wrap",
]

QUIET, NORMAL, VERBOSE, VVERBOSE, SUPPRESS_STDOUT = list(range(-1, 4))
VERBOSENESS = {"quiet", "normal", "verbose", "vverbose"}

COLORS: dict[str, str] = {
    "none": "\033[0m",
    "endc": "\033[0m",
    "bright-grey": "\033[97m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "blue": "\033[94m",
    "yellow": "\033[93m",
    "green": "\033[92m",
    "red": "\033[91m",
    "grey": "\033[90m",
    "white": "\033[37m",
    "bright-cyan": "\033[36m",
    "bright-magenta": "\033[35m",
    "bright-blue": "\033[34m",
    "bright-yellow": "\033[33m",
    "bright-green": "\033[32m",
    "bright-red": "\033[31m",
    "black": "\033[30m",
    "bold": "\033[1m",
    "underline": "\033[4m",
}


class LogEvent(FrozenBaseStruct, frozen=True):
    """Structured log line event emitted during orchestration."""

    line: str
    detail: int = NORMAL
    ansi_code: str | tuple[str, ...] | None = None
    timestamp_str: str | None = None
    prefix: str = ""
    redis_publish: bool = False
    emit_span_event: bool = False
    span_event_level: str = "INFO"


class WarningEvent(FrozenBaseStruct, frozen=True):
    """Structured warning event emitted during orchestration."""

    line: str
    detail: int = NORMAL
    ansi_code: str | tuple[str, ...] | None = None
    prefix: str = ""
    separator: str = ""


class StepStartedEvent(FrozenBaseStruct, frozen=True):
    """Lifecycle event emitted before an orchestration step begins."""

    step_id: str
    step_title: str
    step_code: str | None = None
    command_type: str | None = None
    execution_id: ExecutionId | None = None
    mandatory: bool = False
    optional: bool = False
    execute: bool = True


class StepFinishedEvent(FrozenBaseStruct, frozen=True):
    """Lifecycle event emitted when an orchestration step completes or fails."""

    step_id: str
    step_title: str
    status: str
    command_step_id: int | None = None
    step_details: dict[str, Any] | None = None
    elapsed_formatted: str | None = None
    command_type: str | None = None
    execution_id: ExecutionId | None = None


class StepSkippedEvent(FrozenBaseStruct, frozen=True):
    """Lifecycle event emitted when an orchestration step is skipped."""

    step_id: str
    step_title: str
    step_code: str | None = None
    command_type: str | None = None
    execution_id: ExecutionId | None = None


ExecutionEvent = LogEvent | WarningEvent | StepStartedEvent | StepFinishedEvent | StepSkippedEvent


@runtime_checkable
class ExecutionSink(Protocol):
    """Protocol implemented by all execution event sinks."""

    def emit(self, event: ExecutionEvent) -> None:
        """Process a single execution event."""

    def close(self) -> None:
        """Release any resources held by the sink."""


ExecutionSinkProtocol = ExecutionSink


def ansi_wrap(text: str, ansi_code: str | Sequence[str] | None, ansi: bool = True) -> str:
    """Wrap text with one or more ANSI color/style sequences when ansi is True."""
    if not ansi or not ansi_code:
        return text
    color_names = [ansi_code] if isinstance(ansi_code, str) else list(ansi_code)
    return "".join(COLORS.get(cn, "") for cn in color_names) + str(text) + COLORS.get("none", "")


class ConsoleSink:
    """Thread-safe console sink writing formatted output to a stream without mutating sys.stdout."""

    def __init__(
        self,
        *,
        detail: int = NORMAL,
        ansi: bool = False,
        stream: TextIO | None = None,
    ) -> None:
        self._detail = detail
        self._ansi = ansi
        self._stream = stream
        self._lock = threading.Lock()
        self._stdout_in_error = False

    @property
    def detail(self) -> int:
        """Return the configured console verbosity threshold."""
        return self._detail

    @detail.setter
    def detail(self, value: int) -> None:
        """Update the configured console verbosity threshold."""
        self._detail = value

    @property
    def ansi(self) -> bool:
        """Return True when ANSI styling is enabled for console output."""
        return self._ansi

    @ansi.setter
    def ansi(self, value: bool) -> None:
        """Update whether ANSI styling is enabled for console output."""
        self._ansi = value

    def emit(self, event: ExecutionEvent) -> None:
        """Write formatted log or warning lines to the console when verbosity permits."""
        if isinstance(event, LogEvent):
            if self._detail == QUIET:
                self._write_line(".")
            elif (event.detail is None or event.detail <= self._detail) and self._detail != SUPPRESS_STDOUT:
                rendered = ansi_wrap(event.line, event.ansi_code, self._ansi)
                self._write_line(f"{event.prefix}{rendered}")
        elif isinstance(event, WarningEvent):
            if self._detail == QUIET:
                self._write_line(".")
            elif (event.detail is None or event.detail <= self._detail) and self._detail != SUPPRESS_STDOUT:
                raw = f"WARNING:{event.separator}{event.line}"
                rendered = ansi_wrap(raw, event.ansi_code, self._ansi)
                self._write_line(f"{event.prefix}{rendered}")

    def write_log(
        self,
        message: str,
        detail: int = NORMAL,
        ansi_code: str | Sequence[str] | None = None,
        ts: datetime | None = None,
        emit_span_event: bool = False,
        prefix: str = "",
    ) -> None:
        """Convenience helper to emit a LogEvent directly."""
        norm_ansi: str | tuple[str, ...] | None = (
            ansi_code if isinstance(ansi_code, str) or ansi_code is None else tuple(str(x) for x in ansi_code)
        )
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else None
        self.emit(
            LogEvent(
                line=message,
                detail=detail,
                ansi_code=norm_ansi,
                timestamp_str=ts_str,
                prefix=prefix,
                emit_span_event=emit_span_event,
            )
        )

    def write_warning(
        self,
        message: str,
        ansi_code: str | Sequence[str] | None = None,
        prefix: str = "",
        separator: str = "",
    ) -> None:
        """Convenience helper to emit a WarningEvent directly."""
        norm_ansi: str | tuple[str, ...] | None = (
            ansi_code if isinstance(ansi_code, str) or ansi_code is None else tuple(str(x) for x in ansi_code)
        )
        self.emit(WarningEvent(line=message, ansi_code=norm_ansi, prefix=prefix, separator=separator))

    def write_notice(self, message: str, detail: int = VERBOSE, prefix: str = "") -> None:
        """Convenience helper to emit a notice line."""
        self.write_log(message, detail=detail, prefix=prefix)

    def close(self) -> None:
        """Flush the underlying console stream without closing it."""
        target = self._stream if self._stream is not None else sys.stdout
        with self._lock:
            try:
                target.flush()
            except Exception:
                pass

    def _write_line(self, text: str) -> None:
        if self._stdout_in_error:
            return
        target = self._stream if self._stream is not None else sys.stdout
        with self._lock:
            try:
                target.write(f"{text or ''}\n")
                target.flush()
            except OSError:
                self._stdout_in_error = True


class LogFileSink:
    """Per-execution file sink wrapping GOELogFileHandle with thread-safe writes."""

    def __init__(
        self,
        log_fh: GOELogFileHandle | Any,
        *,
        detail: int = NORMAL,
        ansi: bool = False,
        owns_handle: bool = False,
        write_all_details: bool = True,
    ) -> None:
        self._log_fh = log_fh
        self._detail = detail
        self._ansi = ansi
        self._owns_handle = owns_handle
        self._write_all_details = write_all_details
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def open_for_prefix(
        cls,
        log_dir: str,
        log_name_prefix: str,
        *,
        detail: int = NORMAL,
        ansi: bool = False,
        write_all_details: bool = True,
    ) -> LogFileSink:
        """Create and open a uniquely named log file under log_dir for log_name_prefix."""
        base_name = standard_log_name(log_name_prefix)
        stem, ext = os.path.splitext(base_name)
        log_file = os.path.join(log_dir, base_name)
        uniq = 1
        while os.path.exists(log_file):
            log_file = os.path.join(log_dir, f"{stem}_{uniq}{ext}")
            uniq += 1
        try:
            handle = GOELogFileHandle(log_file, mode="w")
        except PermissionError:
            fallback = os.path.join("/tmp", standard_log_name(log_name_prefix))
            handle = GOELogFileHandle(fallback, mode="w")
        return cls(
            handle,
            detail=detail,
            ansi=ansi,
            owns_handle=True,
            write_all_details=write_all_details,
        )

    @property
    def handle(self) -> Any:
        """Return the underlying GOELogFileHandle."""
        return self._log_fh

    @property
    def name(self) -> str | None:
        """Return the file path of the underlying log file handle."""
        if self._log_fh is None:
            return None
        return getattr(self._log_fh, "name", None)

    @property
    def detail(self) -> int:
        """Return the configured file verbosity level."""
        return self._detail

    @detail.setter
    def detail(self, value: int) -> None:
        """Update the configured file verbosity level."""
        self._detail = value

    @property
    def ansi(self) -> bool:
        """Return True when ANSI codes should be written into the log file."""
        return self._ansi

    @ansi.setter
    def ansi(self, value: bool) -> None:
        """Update whether ANSI codes should be written into the log file."""
        self._ansi = value

    def emit(self, event: ExecutionEvent) -> None:
        """Write formatted log or warning lines into the log file handle."""
        if self._log_fh is None or self._closed:
            return
        if isinstance(event, LogEvent):
            if self._should_write_to_file(event.detail):
                rendered = ansi_wrap(event.line, event.ansi_code, self._ansi)
                ts_prefix = f"{event.timestamp_str}: " if event.timestamp_str else ""
                self._write(f"{ts_prefix}{rendered or ''}\n")
        elif isinstance(event, WarningEvent):
            raw = f"WARNING:{event.separator}{event.line}"
            rendered = ansi_wrap(raw, event.ansi_code, self._ansi)
            self._write(f"{event.prefix}{rendered}\n")

    def write_log(
        self,
        message: str,
        detail: int = NORMAL,
        ansi_code: str | Sequence[str] | None = None,
        ts: datetime | None = None,
        emit_span_event: bool = False,
        prefix: str = "",
    ) -> None:
        """Convenience helper to emit a LogEvent directly to the log file."""
        norm_ansi: str | tuple[str, ...] | None = (
            ansi_code if isinstance(ansi_code, str) or ansi_code is None else tuple(str(x) for x in ansi_code)
        )
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else None
        self.emit(
            LogEvent(
                line=message,
                detail=detail,
                ansi_code=norm_ansi,
                timestamp_str=ts_str,
                prefix=prefix,
                emit_span_event=emit_span_event,
            )
        )

    def write_warning(
        self,
        message: str,
        ansi_code: str | Sequence[str] | None = None,
        prefix: str = "",
        separator: str = "",
    ) -> None:
        """Convenience helper to emit a WarningEvent directly to the log file."""
        norm_ansi: str | tuple[str, ...] | None = (
            ansi_code if isinstance(ansi_code, str) or ansi_code is None else tuple(str(x) for x in ansi_code)
        )
        self.emit(WarningEvent(line=message, ansi_code=norm_ansi, prefix=prefix, separator=separator))

    def close(self) -> None:
        """Flush and close the underlying log file handle if owned by this sink."""
        with self._lock:
            if self._closed or self._log_fh is None:
                return
            self._closed = True
            if self._owns_handle:
                try:
                    self._log_fh.close()
                except Exception:
                    pass

    def _should_write_to_file(self, event_detail: int) -> bool:
        if self._write_all_details:
            return True
        return (self._detail >= event_detail) or (self._detail in (NORMAL, SUPPRESS_STDOUT) and event_detail <= VERBOSE)

    def _write(self, payload: str) -> None:
        with self._lock:
            if not self._closed and self._log_fh is not None:
                self._log_fh.write(payload)
                self._log_fh.flush()


class TelemetrySink:
    """Sink forwarding structured log and skipped-step events to OpenTelemetry spans."""

    def emit(self, event: ExecutionEvent) -> None:
        """Forward span log events and skipped step markers to OpenTelemetry."""
        if isinstance(event, LogEvent) and event.emit_span_event:
            add_span_log_event(event.span_event_level, event.line)
        elif isinstance(event, StepSkippedEvent):
            record_skipped_step(
                event.step_id,
                event.step_code or event.step_id,
                event.step_title,
                command_type=event.command_type,
            )

    def close(self) -> None:
        """No-op close for stateless telemetry sink."""


class RepositoryStepSink:
    """Sink persisting command step start/finish records via a repository client."""

    def __init__(
        self,
        repo_client: Any,
        *,
        execution_id: ExecutionId | None = None,
        command_type: str | None = None,
    ) -> None:
        self._repo_client = repo_client
        self._execution_id = execution_id
        self._command_type = command_type

    @property
    def repo_client(self) -> Any:
        """Return the underlying repository client."""
        return self._repo_client

    def start_step(
        self,
        step_id: str,
        *,
        execution_id: ExecutionId | None = None,
        command_type: str | None = None,
    ) -> int | None:
        """Record the start of a command step in the repository and return its step ID."""
        eff_exec_id = execution_id or self._execution_id
        eff_cmd_type = command_type or self._command_type
        if self._repo_client is not None and eff_cmd_type is not None:
            return self._repo_client.start_command_step(eff_exec_id, eff_cmd_type, step_id)
        return None

    def finish_step(
        self,
        command_step_id: int | None,
        status: str,
        *,
        step_details: dict[str, Any] | None = None,
    ) -> None:
        """Record the completion or error status of a command step in the repository."""
        if self._repo_client is None:
            return
        if step_details:
            self._repo_client.end_command_step(command_step_id, status, step_details=step_details)
        else:
            self._repo_client.end_command_step(command_step_id, status)

    def emit(self, event: ExecutionEvent) -> None:
        """Handle StepFinishedEvent when emitted through the generic sink interface."""
        if isinstance(event, StepFinishedEvent) and event.command_step_id is not None:
            self.finish_step(
                event.command_step_id,
                event.status,
                step_details=event.step_details,
            )

    def close(self) -> None:
        """No-op close; repository client lifecycle is owned by the runner."""
