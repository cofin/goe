# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Trace-correlated structured log lines and LogRecord enrichment for GOE."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import msgspec

from goe.observability.context import get_current_trace_context

__all__ = (
    "StructuredLogEntry",
    "encode_structured_log_line",
    "install_log_record_correlation",
    "uninstall_log_record_correlation",
)

_state: dict[str, Callable[..., logging.LogRecord] | None] = {"original_factory": None}


class StructuredLogEntry(msgspec.Struct, frozen=True, kw_only=True):
    """One JSON log line correlated with the active GOE execution and W3C span."""

    timestamp: str
    level: str
    message: str
    execution_id: str | None = None
    command_type: str | None = None
    step_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None


def encode_structured_log_line(data: str) -> str:
    """Encode one written log chunk as a JSON line; ``WARNING:``-prefixed chunks get level ``WARNING``."""
    message = data.rstrip("\n")
    snapshot = get_current_trace_context()
    entry = StructuredLogEntry(
        timestamp=datetime.now(UTC).isoformat(),
        level="WARNING" if message.startswith("WARNING:") else "INFO",
        message=message,
        execution_id=snapshot.execution_id,
        command_type=snapshot.command_type,
        step_id=snapshot.step_id,
        trace_id=snapshot.trace_id,
        span_id=snapshot.span_id,
    )
    return msgspec.json.encode(entry).decode() + "\n"


def install_log_record_correlation() -> None:
    """Wrap the LogRecord factory so every record carries trace and execution fields (idempotent)."""
    if _state["original_factory"] is not None:
        return
    _state["original_factory"] = logging.getLogRecordFactory()
    logging.setLogRecordFactory(_log_record_factory)


def uninstall_log_record_correlation() -> None:
    """Restore the LogRecord factory captured by ``install_log_record_correlation``."""
    original = _state["original_factory"]
    if original is not None:
        logging.setLogRecordFactory(original)
        _state["original_factory"] = None


def _log_record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Create a record via the original factory and attach correlation attributes."""
    original = _state["original_factory"]
    record = original(*args, **kwargs) if original is not None else logging.LogRecord(*args, **kwargs)
    snapshot = get_current_trace_context()
    record.trace_id = snapshot.trace_id or ""
    record.span_id = snapshot.span_id or ""
    record.execution_id = snapshot.execution_id or ""
    record.step_id = snapshot.step_id or ""
    record.command_type = snapshot.command_type or ""
    return record
