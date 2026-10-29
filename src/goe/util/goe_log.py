# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""GOE general logging routines."""

from __future__ import annotations

import logging
import sys
import traceback
from argparse import Namespace
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from goe.offload.offload_messages import (
    NORMAL,
    VERBOSE,
    VERBOSENESS,
    VVERBOSE,
    OffloadMessages,
)
from goe.util.string_utils import get_option

__all__ = [
    "ansi",
    "get_default_log",
    "get_default_options",
    "global_log_fh",
    "log",
    "log_exception",
    "log_timedelta",
    "log_timestamp",
    "set_option",
]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

global_log_fh: Any = None


def set_option(options: object, opt: str, val: Any) -> None:
    """Set opt attribute in options object with mutual exclusion for verboseness levels."""
    assert options and opt
    setattr(options, opt, val)
    lowered = opt.lower()
    if lowered in VERBOSENESS and val:
        minus_opts = tuple(VERBOSENESS - {lowered})
        for m_opt in minus_opts:
            setattr(options, m_opt, False)


def get_default_options(addons: Mapping[str, Any] | None = None) -> Namespace:
    """Build default options Namespace for logging routines."""
    options = Namespace()
    set_option(options, "ansi", False)
    set_option(options, "normal", True)
    if addons:
        for add_opt, add_val in addons.items():
            set_option(options, add_opt, add_val)
    return options


def get_default_log() -> Any:
    """Return the active module-level fallback log file handle."""
    return global_log_fh


def log(
    line: str,
    detail: int = NORMAL,
    ansi_code: str | None = None,
    log_fh: Any = None,
    options: object | None = None,
) -> None:
    """Write a line to the log handle and stdout according to verbosity options."""
    resolved_options = options if options is not None else get_default_options()
    log_handle = log_fh or global_log_fh
    if log_handle:
        log_handle.write(line + "\n")
        log_handle.flush()

    if get_option(resolved_options, "quiet"):
        sys.stdout.write(".")
        sys.stdout.flush()
    elif (
        detail == NORMAL
        or (detail <= VERBOSE and get_option(resolved_options, "verbose"))
        or (detail <= VVERBOSE and get_option(resolved_options, "vverbose"))
    ):
        formatted = ansi(line, ansi_code, options=resolved_options)
        sys.stdout.write(formatted + "\n")
        sys.stdout.flush()


def log_exception(
    exception: BaseException,
    detail: int = NORMAL,
    log_fh: Any = None,
    options: object | None = None,
) -> None:
    """Write an exception traceback or summary to the log handle and stdout."""
    resolved_options = options if options is not None else get_default_options()
    log_handle = log_fh or global_log_fh
    if log_handle and log_handle != sys.stderr:
        log_handle.write(traceback.format_exc() + "\n")
        log_handle.flush()

    if detail > NORMAL or get_option(resolved_options, "verbose") or get_option(resolved_options, "vverbose"):
        sys.stdout.write(traceback.format_exc() + "\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(f"{type(exception).__name__}: {exception} \n")
        sys.stdout.flush()


def ansi(line: str, ansi_code: str | None, options: object | None = None) -> str:
    """Wrap line in ANSI color codes when ansi is enabled on options."""
    resolved_options = options if options is not None else get_default_options()
    ansi_wrap: Any = OffloadMessages.ansi_wrap
    return str(ansi_wrap(line, ansi_code, get_option(resolved_options, "ansi")))


def log_timestamp(ansi_code: str = "grey", options: object | None = None) -> datetime | None:
    """Log the current timestamp when execute is True and return the timestamp."""
    resolved_options = options if options is not None else get_default_options()
    if get_option(resolved_options, "execute"):
        ts = datetime.now().replace(microsecond=0)
        log(ts.strftime("%c"), detail=VERBOSE, ansi_code=ansi_code, options=resolved_options)
        return ts
    return None


def log_timedelta(
    start_time: datetime,
    ansi_code: str = "grey",
    options: object | None = None,
) -> timedelta | None:
    """Log elapsed step time since start_time when execute is True."""
    resolved_options = options if options is not None else get_default_options()
    if get_option(resolved_options, "execute"):
        ts2 = datetime.now().replace(microsecond=0)
        delta = ts2 - start_time
        log(f"Step time: {delta}", detail=VERBOSE, ansi_code=ansi_code, options=resolved_options)
        return delta
    return None
