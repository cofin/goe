# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Scoped ExecutionContext and ContextVar lifecycle helpers for concurrent orchestration."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, TextIO

import msgspec

from goe.orchestration.sinks import (
    NORMAL,
    QUIET,
    SUPPRESS_STDOUT,
    VERBOSE,
    VVERBOSE,
    ConsoleSink,
    ExecutionEvent,
    LogFileSink,
    RepositoryStepSink,
    TelemetrySink,
)
from goe.typing import FrozenBaseStruct

if TYPE_CHECKING:
    from goe.orchestration.execution_id import ExecutionId

__all__ = [
    "ExecutionContext",
    "bind_execution_context",
    "current_execution_context",
    "execution_context_scope",
    "get_execution_context",
    "reset_execution_context",
    "resolve_detail_from_options",
    "set_execution_context",
]


class ExecutionContext(FrozenBaseStruct, frozen=True):
    """Immutable per-execution context carrying output sinks, verbosity, and telemetry identifiers."""

    detail: int = NORMAL
    ansi: bool = False
    execution_id: ExecutionId | None = None
    command_type: str | None = None
    log_dir: str = "/tmp"
    dev_log: bool = False
    dev_log_level: int = logging.INFO
    sinks: tuple[Any, ...] = ()
    operation_name: str | None = None
    config: Any = None
    log_path: str | None = None
    dry_run: bool = False
    trace_id: str | None = None
    span_id: str | None = None

    @classmethod
    def for_console(
        cls,
        *,
        detail: int = NORMAL,
        ansi: bool = False,
        execution_id: ExecutionId | None = None,
        command_type: str | None = None,
        log_dir: str | None = None,
        dev_log: bool = False,
        dev_log_level: int = logging.INFO,
        stream: TextIO | None = None,
        include_telemetry: bool = True,
        operation_name: str | None = None,
        config: Any = None,
        log_path: str | None = None,
        dry_run: bool = False,
    ) -> ExecutionContext:
        """Construct an ExecutionContext configured with a ConsoleSink and optional TelemetrySink."""
        resolved_dir = (
            log_dir or os.environ.get("OFFLOAD_LOGDIR") or os.path.join(os.environ.get("OFFLOAD_HOME", "/tmp"), "log")
        )
        console_sink = ConsoleSink(detail=detail, ansi=ansi, stream=stream)
        sink_list: list[Any] = [console_sink]
        if include_telemetry:
            sink_list.append(TelemetrySink())
        return cls(
            detail=detail,
            ansi=ansi,
            execution_id=execution_id,
            command_type=command_type,
            log_dir=resolved_dir,
            dev_log=dev_log,
            dev_log_level=dev_log_level,
            sinks=tuple(sink_list),
            operation_name=operation_name,
            config=config,
            log_path=log_path,
            dry_run=dry_run,
        )

    @property
    def log_file_sink(self) -> LogFileSink | None:
        """Return the attached LogFileSink if one is present."""
        for sink in self.sinks:
            if isinstance(sink, LogFileSink):
                return sink
        return None

    @property
    def repository_sink(self) -> RepositoryStepSink | None:
        """Return the attached RepositoryStepSink if one is present."""
        for sink in self.sinks:
            if isinstance(sink, RepositoryStepSink):
                return sink
        return None

    def emit(self, event: ExecutionEvent) -> None:
        """Dispatch an ExecutionEvent to all attached sinks in order."""
        for sink in self.sinks:
            sink.emit(event)

    def with_log_file(
        self,
        log_name_prefix: str,
        *,
        log_dir: str | None = None,
        write_all_details: bool = True,
    ) -> ExecutionContext:
        """Return a new ExecutionContext with a freshly opened LogFileSink."""
        existing = self.log_file_sink
        if existing is not None:
            existing.close()
        target_dir = log_dir or self.log_dir
        new_file_sink = LogFileSink.open_for_prefix(
            target_dir,
            log_name_prefix,
            detail=self.detail,
            ansi=self.ansi,
            write_all_details=write_all_details,
        )
        retained = [s for s in self.sinks if not isinstance(s, LogFileSink)]
        retained.append(new_file_sink)
        return msgspec.structs.replace(
            self,
            log_dir=target_dir,
            log_path=new_file_sink.name,
            sinks=tuple(retained),
        )

    def with_repository(
        self,
        repo_client: Any,
        *,
        execution_id: ExecutionId | None = None,
        command_type: str | None = None,
    ) -> ExecutionContext:
        """Return a new ExecutionContext with a bound RepositoryStepSink."""
        eff_exec_id = execution_id or self.execution_id
        eff_cmd_type = command_type or self.command_type
        retained = [s for s in self.sinks if not isinstance(s, RepositoryStepSink)]
        if repo_client is not None:
            retained.append(
                RepositoryStepSink(
                    repo_client,
                    execution_id=eff_exec_id,
                    command_type=eff_cmd_type,
                )
            )
        return msgspec.structs.replace(
            self,
            execution_id=eff_exec_id,
            command_type=eff_cmd_type,
            sinks=tuple(retained),
        )

    def with_sinks(self, *extra_sinks: Any) -> ExecutionContext:
        """Return a new ExecutionContext with extra_sinks appended."""
        return msgspec.structs.replace(self, sinks=(*self.sinks, *extra_sinks))

    def with_execution(
        self,
        *,
        execution_id: ExecutionId | None = None,
        command_type: str | None = None,
        detail: int | None = None,
        ansi: bool | None = None,
    ) -> ExecutionContext:
        """Return a new ExecutionContext with updated execution metadata and sink settings."""
        eff_detail = self.detail if detail is None else detail
        eff_ansi = self.ansi if ansi is None else ansi
        eff_exec_id = self.execution_id if execution_id is None else execution_id
        eff_cmd_type = self.command_type if command_type is None else command_type
        updated_sinks: list[Any] = []
        for sink in self.sinks:
            if isinstance(sink, (ConsoleSink, LogFileSink)):
                sink.detail = eff_detail
                sink.ansi = eff_ansi
            updated_sinks.append(sink)
        return msgspec.structs.replace(
            self,
            detail=eff_detail,
            ansi=eff_ansi,
            execution_id=eff_exec_id,
            command_type=eff_cmd_type,
            sinks=tuple(updated_sinks),
        )

    def close(self) -> None:
        """Close all attached sinks."""
        for sink in self.sinks:
            try:
                sink.close()
            except Exception:
                pass


_CURRENT_EXECUTION_CONTEXT: ContextVar[ExecutionContext | None] = ContextVar(
    "goe_current_execution_context",
    default=None,
)


def current_execution_context() -> ExecutionContext | None:
    """Return the ExecutionContext bound to the current thread or async task, if any."""
    return _CURRENT_EXECUTION_CONTEXT.get()


def get_execution_context() -> ExecutionContext | None:
    """Alias for current_execution_context returning the active ExecutionContext."""
    return _CURRENT_EXECUTION_CONTEXT.get()


def set_execution_context(ctx: ExecutionContext | None) -> Token[ExecutionContext | None]:
    """Bind ctx to the current ContextVar and return its reset token."""
    return _CURRENT_EXECUTION_CONTEXT.set(ctx)


def reset_execution_context(token: Token[ExecutionContext | None]) -> None:
    """Restore the ContextVar to its state prior to token."""
    _CURRENT_EXECUTION_CONTEXT.reset(token)


@contextmanager
def bind_execution_context(ctx: ExecutionContext) -> Iterator[ExecutionContext]:
    """Bind ctx for the duration of a with-block and restore the prior context on exit."""
    token = set_execution_context(ctx)
    try:
        yield ctx
    finally:
        reset_execution_context(token)


execution_context_scope = bind_execution_context


def resolve_detail_from_options(options: Any, *, suppress_stdout_override: bool | None = None) -> int:
    """Resolve the integer detail level from an options struct or namespace."""
    if getattr(options, "quiet", False):
        return QUIET
    if getattr(options, "suppress_stdout", False) or suppress_stdout_override is True:
        return SUPPRESS_STDOUT
    if getattr(options, "vverbose", False):
        return VVERBOSE
    if getattr(options, "verbose", False):
        return VERBOSE
    return NORMAL


def _normalize_ansi_sequence(ansi_code: str | Sequence[str] | None) -> str | tuple[str, ...] | None:
    if isinstance(ansi_code, str) or ansi_code is None:
        return ansi_code
    return tuple(str(x) for x in ansi_code)
