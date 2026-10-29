# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadMessages facade routing console, file, telemetry, and repository step events through ExecutionContext."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from goe.observability.spans import (
    add_span_log_event,
    current_trace_ids,
    record_skipped_step,
    traced_step,
)
from goe.orchestration import command_steps, orchestration_constants
from goe.orchestration.command_steps import STEP_TITLES, step_title
from goe.orchestration.context import (
    ExecutionContext,
    current_execution_context,
)
from goe.orchestration.sinks import (
    COLORS,
    NORMAL,
    QUIET,
    SUPPRESS_STDOUT,
    VERBOSE,
    VERBOSENESS,
    VVERBOSE,
    ConsoleSink,
    LogEvent,
    LogFileSink,
    RepositoryStepSink,
    StepSkippedEvent,
    StepStartedEvent,
    ansi_wrap,
)

if TYPE_CHECKING:
    from goe.persistence.oracle.oracle_repository import OracleRepositoryService

__all__ = [
    "COLORS",
    "FORCED_EXCEPTION_TEXT",
    "NORMAL",
    "QUIET",
    "SUPPRESS_STDOUT",
    "VERBOSE",
    "VERBOSENESS",
    "VVERBOSE",
    "OffloadMessages",
    "OffloadMessagesException",
    "OffloadMessagesForcedException",
    "OffloadMessagesMixin",
    "ansi_wrap",
    "step_title_to_step_id",
]


class OffloadMessagesException(Exception):
    """Exception raised by OffloadMessages for invalid configuration or arguments."""


class OffloadMessagesForcedException(Exception):
    """Exception raised when error_before_step or error_after_step is triggered."""


FORCED_EXCEPTION_TEXT = "Forcing exception"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def step_title_to_step_id(title_or_id: str | None) -> str | None:
    """Normalize a human step title into its lowercase underscore step identifier."""
    if title_or_id:
        return title_or_id.replace(" ", "_").lower()
    return None


class OffloadMessages:
    """Class for logging, storing & reporting messages in Offload & Present backed by ExecutionContext."""

    def __init__(
        self,
        detail: int = NORMAL,
        log_fh: Any = None,
        ansi: bool = True,
        error_before_step: str | None = None,
        error_after_step: str | None = None,
        skip: Sequence[str] | None = None,
        execution_id: Any = None,
        repo_client: Any = None,
        command_type: str | None = None,
        dev_log: bool = False,
        dev_log_level: int = logging.INFO,
        line_prefix: str | None = None,
        context: ExecutionContext | None = None,
    ) -> None:
        logger.info("OffloadMessages setup")
        if command_type:
            assert command_type in orchestration_constants.ALL_COMMAND_CODES, f"Unknown command type: {command_type}"

        if log_fh is None and context is not None and context.log_file_sink is not None:
            log_fh = context.log_file_sink.handle

        self.messages: dict[str, list[Any]] = {"notices": [], "warnings": [], "events": []}
        self.steps: dict[str, Any] = {}
        self._log_fh = log_fh
        self._detail = detail
        self._ansi = bool(ansi)
        self._skip = list(skip) if skip else []
        self._error_before_step = error_before_step
        self._error_after_step = error_after_step
        self.execution_id = execution_id
        self._repo_client = repo_client
        self._command_type: str | None = command_type
        self._dev_log = dev_log
        self._dev_log_level = dev_log_level
        self.line_prefix = line_prefix or ""
        self.suppress_stdout_override: bool | None = None
        self._owns_log_fh = False
        self._extra_sinks: tuple[Any, ...] = (
            tuple(s for s in context.sinks if not isinstance(s, (ConsoleSink, LogFileSink, RepositoryStepSink)))
            if context is not None
            else ()
        )
        self._ctx = self._build_context()

    @staticmethod
    def detail_from_options(opts: Any) -> int:
        """Resolve verbosity level from an options object."""
        if getattr(opts, "quiet", False):
            return QUIET
        if getattr(opts, "vverbose", False):
            return VVERBOSE
        if getattr(opts, "verbose", False):
            return VERBOSE
        if getattr(opts, "suppress_stdout", False):
            return SUPPRESS_STDOUT
        return NORMAL

    @staticmethod
    def from_context(
        context: ExecutionContext,
        *,
        error_before_step: str | None = None,
        error_after_step: str | None = None,
        skip: Sequence[str] | None = None,
        repo_client: Any = None,
    ) -> OffloadMessages:
        """Construct OffloadMessages bound to an existing ExecutionContext."""
        log_fh = context.log_file_sink.handle if context.log_file_sink is not None else None
        effective_repo = repo_client
        if effective_repo is None and context.repository_sink is not None:
            effective_repo = context.repository_sink.repo_client
        return OffloadMessages(
            detail=context.detail,
            log_fh=log_fh,
            ansi=context.ansi,
            error_before_step=error_before_step,
            error_after_step=error_after_step,
            skip=skip,
            execution_id=context.execution_id,
            repo_client=effective_repo,
            command_type=context.command_type,
            dev_log=context.dev_log,
            dev_log_level=context.dev_log_level,
            context=context,
        )

    @staticmethod
    def from_options(
        opts: Any,
        log_fh: Any = None,
        execution_id: Any = None,
        repo_client: Any = None,
        command_type: str | None = None,
        context: ExecutionContext | None = None,
    ) -> OffloadMessages:
        """Construct OffloadMessages from an options object or OrchestrationConfig."""
        assert hasattr(opts, "quiet")
        assert hasattr(opts, "verbose")
        assert hasattr(opts, "vverbose")
        assert hasattr(opts, "ansi")
        detail = OffloadMessages.detail_from_options(opts)
        resolved_fh = log_fh
        if resolved_fh is None:
            active_ctx = context or current_execution_context()
            if active_ctx is not None and active_ctx.log_file_sink is not None:
                resolved_fh = active_ctx.log_file_sink.handle
        return OffloadMessages(
            detail=detail,
            log_fh=resolved_fh,
            ansi=bool(opts.ansi),
            error_before_step=getattr(opts, "error_before_step", None),
            error_after_step=getattr(opts, "error_after_step", None),
            skip=getattr(opts, "skip", None),
            execution_id=execution_id,
            repo_client=repo_client,
            command_type=command_type,
            context=context,
        )

    @staticmethod
    def from_options_dict(
        opts_dict: dict[str, Any],
        log_fh: Any = None,
        execution_id: Any = None,
        repo_client: Any = None,
        command_type: str | None = None,
    ) -> OffloadMessages:
        """Construct OffloadMessages from a raw options dictionary."""
        if opts_dict.get("quiet"):
            detail = QUIET
        elif opts_dict.get("vverbose"):
            detail = VVERBOSE
        elif opts_dict.get("verbose"):
            detail = VERBOSE
        elif opts_dict.get("suppress_stdout"):
            detail = SUPPRESS_STDOUT
        else:
            detail = NORMAL
        return OffloadMessages(
            detail=detail,
            log_fh=log_fh,
            ansi=bool(opts_dict.get("ansi")),
            error_before_step=opts_dict.get("error_before_step"),
            error_after_step=opts_dict.get("error_after_step"),
            skip=opts_dict.get("skip"),
            execution_id=execution_id,
            repo_client=repo_client,
            command_type=command_type,
        )

    @staticmethod
    def ansi_wrap(txt: str, color_name: Any, ansi: bool = True) -> str:
        """Wrap txt in ANSI color sequences when ansi is True."""
        return ansi_wrap(txt, color_name, ansi=ansi)

    @property
    def context(self) -> ExecutionContext:
        """Return the underlying ExecutionContext for this OffloadMessages instance."""
        return self._ctx

    @property
    def verbosity(self) -> int:
        """Return the configured integer verbosity level."""
        return self._detail

    @property
    def command_type(self) -> str | None:
        """Return the orchestration command code this object was created for."""
        return self._command_type

    def get_execution_id(self) -> Any:
        """Return the bound ExecutionId."""
        return self.execution_id

    def set_execution_id(self, execution_id: Any) -> None:
        """Update the bound ExecutionId and refresh the ExecutionContext."""
        self.execution_id = execution_id
        self._ctx = self._build_context()

    def init_log(self, log_dir: str, log_name: str) -> None:
        """Open a dedicated log file handle under log_dir and bind it to this instance."""
        assert log_dir and log_name
        logger.debug("init_log(%s, %s)" % (log_dir, log_name))
        self.close_log()
        file_sink = LogFileSink.open_for_prefix(
            log_dir,
            log_name,
            detail=self._detail,
            ansi=False,
            write_all_details=True,
        )
        self._log_fh = file_sink.handle
        self._owns_log_fh = True
        self._ctx = self._build_context()

    def close_log(self) -> None:
        """Close the log file handle if present."""
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None
            self._owns_log_fh = False
            self._ctx = self._build_context()

    def get_log_fh(self) -> Any:
        """Return the active log file handle."""
        return self._log_fh

    def get_log_fh_name(self) -> str | None:
        """Return the file path of the active log file handle."""
        return self._log_fh.name if self._log_fh else None

    def log(
        self,
        line: Any,
        detail: int | None = NORMAL,
        ansi_code: str | Sequence[str] | None = None,
        ts: datetime | None = None,
        redis_publish: bool = False,
        emit_span_event: bool = False,
    ) -> Any:
        """Write to log file and optionally to STDOUT via ExecutionContext sinks."""
        line_str = "" if line is None else (line if isinstance(line, str) else str(line))
        log_ts = ts.strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, datetime) else None

        if emit_span_event:
            add_span_log_event("INFO", line_str)

        effective_console_detail = SUPPRESS_STDOUT if self.suppress_stdout_override else self._detail
        for sink in self._ctx.sinks:
            if isinstance(sink, ConsoleSink):
                sink.detail = effective_console_detail
                sink.ansi = self._ansi
            elif isinstance(sink, LogFileSink):
                sink.detail = self._detail
                sink.ansi = False

        norm_ansi: str | tuple[str, ...] | None = (
            ansi_code if isinstance(ansi_code, str) or ansi_code is None else tuple(str(x) for x in ansi_code)
        )
        self._ctx.emit(
            LogEvent(
                line=line_str,
                detail=NORMAL if detail is None else detail,
                ansi_code=norm_ansi,
                timestamp_str=log_ts,
                prefix=self.line_prefix,
                redis_publish=redis_publish,
                emit_span_event=False,
            )
        )

    def info(self, line: Any, detail: int = NORMAL, ansi_code: str | Sequence[str] | None = None) -> None:
        """Log line when verbosity is at least NORMAL."""
        if self._detail >= NORMAL:
            self.log(line, detail, ansi_code)

    def detail(self, line: Any, detail: int = NORMAL, ansi_code: str | Sequence[str] | None = None) -> None:
        """Log line when verbosity is at least VERBOSE."""
        if self._detail >= VERBOSE:
            self.log(line, detail, ansi_code)

    def debug(self, line: Any, detail: int = NORMAL, ansi_code: str | Sequence[str] | None = None) -> None:
        """Log line when verbosity is at least VVERBOSE."""
        if self._detail >= VVERBOSE:
            self.log(line, detail, ansi_code)

    def notice(self, msg: str, detail: int = VERBOSE) -> None:
        """Record a notice message and log it at detail."""
        if msg not in self.messages["notices"]:
            self.messages["notices"].append(msg)
        self.log(msg, detail)

    def warning(self, msg: str, detail: int = NORMAL, ansi_code: str | Sequence[str] | None = None) -> None:
        """Record a warning message, log it with WARNING: prefix, and emit a span event."""
        if msg not in self.messages["warnings"]:
            self.messages["warnings"].append(msg)
        self.log("WARNING:" + msg, detail, ansi_code)
        add_span_log_event("WARNING", msg)

    def event(self, token: Any) -> None:
        """Record a programmatic event token for test and caller inspection."""
        assert token
        self.messages["events"].append(token)

    def debug_enabled(self) -> bool:
        """Return True when verbosity is at least VVERBOSE."""
        return bool(self._detail >= VVERBOSE)

    def log_timestamp(
        self,
        ansi_code: str | Sequence[str] | None = "grey",
        execute: bool = True,
        detail: int = VERBOSE,
    ) -> datetime | None:
        """Log the current timestamp when execute is True and return it."""
        ts = None
        if execute:
            ts = datetime.now().replace(microsecond=0)
            self.log(ts.strftime("%c"), detail=detail, ansi_code=ansi_code)
        return ts

    def offload_step(
        self,
        step_constant: str,
        step_fn: Callable[[], Any],
        execute: bool = True,
        optional: bool = False,
        command_type: str | None = None,
        mandatory_step: bool = False,
        record_step_delta: bool = True,
    ) -> Any:
        """Execute an orchestration step with timing, logging, telemetry spans, and repository tracking."""

        def log_timedelta(start_time: datetime | None, ansi_code: str = "grey") -> timedelta | None:
            if execute and start_time is not None:
                ts2 = datetime.now().replace(microsecond=0)
                self.log(
                    "Step time: %s" % (ts2 - start_time),
                    detail=VERBOSE,
                    ansi_code=ansi_code,
                )
                return ts2 - start_time
            return None

        def step_repo_logging(check_command_type: str | None) -> bool:
            return bool(
                check_command_type
                not in (
                    None,
                    orchestration_constants.COMMAND_DIAGNOSE,
                    orchestration_constants.COMMAND_OSR,
                    orchestration_constants.COMMAND_SCHEMA_SYNC,
                    orchestration_constants.COMMAND_TEST,
                )
            )

        assert step_constant in STEP_TITLES, f"Unknown step constant: {step_constant}"
        if command_type:
            assert command_type in orchestration_constants.ALL_COMMAND_CODES, f"Unknown command type: {command_type}"

        parent_command_type = command_type or self._command_type
        if step_repo_logging(parent_command_type):
            assert self._repo_client, f"Repository client must be initialized for command type: {parent_command_type}"

        title = step_title(step_constant)

        self.log("")
        self.log(title, ansi_code="underline")
        ts = self.log_timestamp(execute=execute)

        step_id = step_title_to_step_id(title) or step_constant.lower()
        if self._skip and step_id in self._skip:
            if mandatory_step:
                raise OffloadMessagesException('Step "%s" is mandatory and cannot be skipped' % title)
            record_skipped_step(step_id, step_constant, title, command_type=parent_command_type)
            self._ctx.emit(
                StepSkippedEvent(
                    step_id=step_id,
                    step_title=title,
                    step_code=step_constant,
                    command_type=parent_command_type,
                    execution_id=self.execution_id,
                )
            )
            self.log("skipped")
            return None

        repo_sink = self._ctx.repository_sink
        self._ctx.emit(
            StepStartedEvent(
                step_id=step_id,
                step_title=title,
                step_code=step_constant,
                command_type=parent_command_type,
                execution_id=self.execution_id,
                mandatory=mandatory_step,
                optional=optional,
                execute=execute,
            )
        )

        with traced_step(
            step_id,
            step_constant,
            title,
            command_type=parent_command_type,
            mandatory=mandatory_step,
            optional=optional,
            execute=execute,
        ) as step_op:
            if step_repo_logging(parent_command_type) and repo_sink is not None:
                csid = repo_sink.start_step(
                    step_constant,
                    execution_id=self.execution_id,
                    command_type=parent_command_type,
                )
            elif step_repo_logging(parent_command_type):
                csid = self._repo_client.start_command_step(self.execution_id, parent_command_type, step_constant)
            else:
                csid = None

            if step_id == self._error_before_step:
                raise OffloadMessagesForcedException("%s before step: %s" % (FORCED_EXCEPTION_TEXT, title))

            try:
                step_results = step_fn()
                td = log_timedelta(ts)

                if execute:
                    self.log("Done", ansi_code="green")
                    if record_step_delta:
                        self.step_delta(title, td)
                else:
                    self.step_no_delta(title)

                if step_repo_logging(parent_command_type):
                    trace_ids = current_trace_ids()
                    if repo_sink is not None:
                        repo_sink.finish_step(
                            csid,
                            orchestration_constants.COMMAND_SUCCESS,
                            step_details=trace_ids if trace_ids else None,
                        )
                    elif trace_ids:
                        self._repo_client.end_command_step(
                            csid, orchestration_constants.COMMAND_SUCCESS, step_details=trace_ids
                        )
                    else:
                        self._repo_client.end_command_step(csid, orchestration_constants.COMMAND_SUCCESS)

                return step_results
            except Exception as exc:
                step_op.fail(exc)
                log_timedelta(ts)
                if step_repo_logging(parent_command_type):
                    error_context = {
                        command_steps.CTX_ERROR_MESSAGE: str(exc),
                        command_steps.CTX_EXCEPTION_STACK: traceback.format_exc(),
                        **current_trace_ids(),
                    }
                    if repo_sink is not None:
                        repo_sink.finish_step(
                            csid,
                            orchestration_constants.COMMAND_ERROR,
                            step_details=error_context,
                        )
                    else:
                        self._repo_client.end_command_step(
                            csid,
                            orchestration_constants.COMMAND_ERROR,
                            step_details=error_context,
                        )
                if optional:
                    self.log(traceback.format_exc(), detail=VVERBOSE)
                    self.warning('Error in "%s": %s' % (title, str(exc)), ansi_code="red")
                    self.log("Optional step, continuing", ansi_code="green")
                    return None
                raise
            finally:
                if step_id == self._error_after_step:
                    raise OffloadMessagesForcedException("%s after step: %s" % (FORCED_EXCEPTION_TEXT, title))

    def setup_offload_step(
        self,
        skip: Any = None,
        error_before_step: Any = None,
        error_after_step: Any = None,
        repo_client: OracleRepositoryService | None = None,
        command_type: str | None = None,
    ) -> None:
        """Configure operational attributes used by offload_step()."""
        if skip is not None:
            self._skip = list(skip) if skip else []
        if error_before_step is not None:
            self._error_before_step = step_title_to_step_id(error_before_step)
        if error_after_step is not None:
            self._error_after_step = step_title_to_step_id(error_after_step)
        if repo_client is not None:
            self._repo_client = repo_client
        if command_type is not None:
            self._command_type = command_type
        self._ctx = self._build_context()

    def get_events(self) -> list[Any]:
        """Return recorded programmatic events."""
        return self.messages["events"]

    def get_messages(self) -> list[str]:
        """Return combined warnings and notices."""
        return self.messages["warnings"] + self.messages["notices"]

    def get_notices(self) -> list[str]:
        """Return recorded notices."""
        return self.messages["notices"]

    def get_warnings(self) -> list[str]:
        """Return recorded warnings."""
        return self.messages["warnings"]

    def log_messages(self) -> None:
        """Emit accumulated warnings and notices at the end of an operation."""
        logger.info("log_messages()")
        if self.get_warnings():
            self.log("Warnings:", ansi_code="red")
            for msg in self.get_warnings():
                self.log(msg)
        if self.get_notices():
            self.log("Notices:", ansi_code="green")
            for msg in self.get_notices():
                self.log(msg)

    def step_delta(self, step: str, time_delta: timedelta | None) -> None:
        """Accumulate elapsed step duration in seconds and invocation count."""
        if time_delta is None:
            return
        if step in self.steps:
            self.steps[step]["seconds"] = self.steps[step]["seconds"] + time_delta.total_seconds()
            self.steps[step]["count"] += 1
        else:
            self.steps[step] = {"seconds": time_delta.total_seconds(), "count": 1}

    def step_no_delta(self, step: str) -> None:
        """Record a step invocation without elapsed duration in preview mode."""
        if step in self.steps:
            self.steps[step]["count"] += 1
        else:
            self.steps[step] = {"seconds": 0, "count": 1}

    def log_step_deltas(self, topn: int = 10, detail: int = VVERBOSE) -> None:
        """Log a summary table of the top elapsed steps."""
        logger.info("log_step_deltas()")
        if not self.steps:
            return
        logged_seconds = sum(_["seconds"] for _ in list(self.steps.values()))
        step_width = max(len(step) for step in self.steps)
        step_format = "{0: <" + str(step_width) + "} {1: >9} {2: >7}"
        self.log(step_format.format("Step", "Seconds", "Percent"), detail=detail)
        for i, (step_key, step_dict) in enumerate(
            sorted(iter(self.steps.items()), key=lambda x: x[1]["seconds"], reverse=True)
        ):
            if i >= topn:
                break
            ratio = (step_dict["seconds"] / logged_seconds) if logged_seconds > 0 else 0
            self.log(
                step_format.format(
                    step_key,
                    "{:9.0f}".format(step_dict["seconds"]),
                    f"{ratio:5.1%}",
                ),
                detail=detail,
            )
        if logged_seconds:
            self.log(
                "Total time logged: %s" % str(timedelta(seconds=logged_seconds)),
                detail=VVERBOSE,
            )

    def close(self) -> None:
        """Close the log file handle if owned by this instance."""
        if self._owns_log_fh:
            self.close_log()

    def _build_context(self) -> ExecutionContext:
        console_sink = ConsoleSink(detail=self._detail, ansi=self._ansi)
        sinks: list[Any] = [console_sink]
        if self._log_fh is not None:
            sinks.append(
                LogFileSink(
                    self._log_fh,
                    detail=self._detail,
                    ansi=False,
                    owns_handle=self._owns_log_fh,
                    write_all_details=True,
                )
            )
        if self._repo_client is not None:
            sinks.append(
                RepositoryStepSink(
                    self._repo_client,
                    execution_id=self.execution_id,
                    command_type=self._command_type,
                )
            )
        sinks.extend(self._extra_sinks)
        return ExecutionContext(
            detail=self._detail,
            ansi=self._ansi,
            execution_id=self.execution_id,
            command_type=self._command_type,
            dev_log=self._dev_log,
            dev_log_level=self._dev_log_level,
            sinks=tuple(sinks),
        )


class OffloadMessagesMixin:
    """Helper class that injects GOE logging routines into child classes."""

    def __init__(self, messages: OffloadMessages | None = None, ext_logger: logging.Logger | None = None) -> None:
        self.warn = self._set_func(
            "warn",
            messages,
            ext_logger,
            lambda: partial(messages.warning, ansi_code="red") if messages else (lambda *_a, **_k: None),
            lambda: (lambda msg, **_kwargs: ext_logger.warning(msg)) if ext_logger else (lambda *_a, **_k: None),
        )
        self.notice = self._set_func(
            "notice",
            messages,
            ext_logger,
            lambda: messages.notice if messages else (lambda *_a, **_k: None),
            lambda: (lambda msg, **_kwargs: ext_logger.info(msg)) if ext_logger else (lambda *_a, **_k: None),
        )
        self.log = self._set_func(
            "log",
            messages,
            ext_logger,
            lambda: messages.log if messages else (lambda *_a, **_k: None),
            lambda: (lambda msg, **_kwargs: ext_logger.info(msg)) if ext_logger else (lambda *_a, **_k: None),
        )
        self.log_normal = self._set_func(
            "log_normal",
            messages,
            ext_logger,
            lambda: partial(messages.log, detail=NORMAL) if messages else (lambda *_a, **_k: None),
            lambda: (lambda msg, **_kwargs: ext_logger.info(msg)) if ext_logger else (lambda *_a, **_k: None),
        )
        self.log_verbose = self._set_func(
            "log_verbose",
            messages,
            ext_logger,
            lambda: partial(messages.log, detail=VERBOSE) if messages else (lambda *_a, **_k: None),
            lambda: (lambda msg, **_kwargs: ext_logger.info(msg)) if ext_logger else (lambda *_a, **_k: None),
        )
        self.log_vverbose = self._set_func(
            "log_vverbose",
            messages,
            ext_logger,
            lambda: partial(messages.log, detail=VVERBOSE) if messages else (lambda *_a, **_k: None),
            lambda: (lambda msg, **_kwargs: ext_logger.info(msg)) if ext_logger else (lambda *_a, **_k: None),
        )

    @staticmethod
    def _set_func(
        marker: str,
        messages: Any,
        ext_logger: Any,
        messages_func: Callable[[], Any],
        logger_func: Callable[[], Any],
    ) -> Callable[..., Any]:
        if messages and isinstance(messages, OffloadMessages):
            logger.debug("Setting: %s call to use 'messages'" % marker)
            return messages_func()
        if logger and isinstance(ext_logger, logging.Logger):
            logger.debug("Setting: %s call to use 'logger'" % marker)
            return logger_func()
        logger.debug("Setting: %s call to EMPTY" % marker)
        return lambda *_args, **_kwargs: None
