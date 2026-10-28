# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Logging, version banner, and execution context initialization helpers for orchestration."""

from __future__ import annotations

import importlib.metadata
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from goe import __version__ as package_version
from goe.orchestration.context import (
    ExecutionContext,
    current_execution_context,
    resolve_detail_from_options,
    set_execution_context,
)
from goe.orchestration.sinks import (
    COLORS,
    NORMAL,
    SUPPRESS_STDOUT,
    VERBOSE,
    VVERBOSE,
    LogEvent,
    ansi_wrap,
)
from goe.util.string_utils import obscure_list_items, set_goelib_logging

__all__ = [
    "COLORS",
    "NORMAL",
    "SUPPRESS_STDOUT",
    "VERBOSE",
    "VVERBOSE",
    "ansi",
    "comp_ver_check",
    "get_log_fh",
    "get_log_fh_name",
    "init",
    "init_log",
    "log",
    "log_close",
    "log_command_line",
    "log_timestamp",
    "normal",
    "strict_version_ready",
    "suppress_stdout",
    "verbose",
    "version",
    "version_abort",
    "vverbose",
]

suppress_stdout = SUPPRESS_STDOUT
normal = NORMAL
verbose = VERBOSE
vverbose = VVERBOSE


def version() -> str:
    """Return the package version string from version_build or package metadata."""
    offload_home = os.environ.get("OFFLOAD_HOME")
    if offload_home:
        version_file_path = Path(offload_home) / "version_build"
        if version_file_path.is_file():
            return version_file_path.read_text(encoding="utf-8").strip()
    try:
        return importlib.metadata.version("goe-framework")
    except Exception:
        return package_version


def strict_version_ready(ver_str: str | None) -> str | None:
    """Strip build/hash suffixes from a version string so major.minor.patch can be parsed."""
    if not ver_str:
        return ver_str
    return ver_str.split("-")[0]


def comp_ver_check(frontend_api_or_ver: Any, ref_ver_tuple: tuple[int, ...] | None = None) -> Any:
    """Compare either a semantic version string against ref_ver_tuple or frontend_api DB component version."""
    if ref_ver_tuple is not None:
        clean = strict_version_ready(str(frontend_api_or_ver)) or ""
        parsed = tuple(int(tok) for tok in clean.split(".")[:3] if tok.isdigit())
        return parsed >= ref_ver_tuple
    v_goe = version()
    v_ora = frontend_api_or_ver.goe_db_component_version()
    return v_goe == v_ora, v_goe, v_ora


def version_abort(check_version: Any = None, frontend_api: Any = None) -> tuple[bool, str, str]:
    """Check whether an Oracle component version mismatch requires aborting, or print version and exit."""
    if frontend_api is None:
        log(f"Gluent Offload Engine v{version()}")
        sys.exit(0)
    match, v_goe, v_ora = comp_ver_check(frontend_api)
    if check_version and not match and ".dev" not in v_goe:
        return True, v_goe, v_ora
    return False, v_goe, v_ora


def ansi(text: str, ansi_code: str | list[str] | tuple[str, ...] | None) -> str:
    """Apply ANSI color/style wrapping when the active ExecutionContext enables ANSI output."""
    ctx = current_execution_context()
    if ctx is not None and not ctx.ansi:
        return text
    return ansi_wrap(text, ansi_code)


def init(opt: Any) -> ExecutionContext:
    """Initialize and bind an ExecutionContext from CLI or service options."""
    if getattr(opt, "version", False):
        print(version())
        sys.exit(0)

    existing = current_execution_context()
    if existing is not None:
        existing.close()

    detail = resolve_detail_from_options(opt)
    ansi_enabled = bool(getattr(opt, "ansi", False))
    dev_level_raw = str(getattr(opt, "dev_log_level", "OFF") or "OFF").upper()
    dev_log_enabled = dev_level_raw in ("INFO", "DEBUG")
    dev_level_int = logging.DEBUG if dev_level_raw == "DEBUG" else logging.INFO

    if dev_log_enabled:
        set_goelib_logging(dev_level_raw)
    else:
        set_goelib_logging("CRITICAL")

    log_dir = (
        getattr(opt, "log_path", None)
        or os.environ.get("OFFLOAD_LOGDIR")
        or os.path.join(os.environ.get("OFFLOAD_HOME", "/tmp"), "log")
    )
    ctx = ExecutionContext.for_console(
        detail=detail,
        ansi=ansi_enabled,
        log_dir=log_dir,
        dev_log=dev_log_enabled,
        dev_log_level=dev_level_int,
    )
    set_execution_context(ctx)
    return ctx


def init_log(log_file_name_prefix: str) -> str | None:
    """Attach a per-execution log file sink to the active ExecutionContext."""
    ctx = current_execution_context()
    if ctx is None:
        ctx = ExecutionContext.for_console()
    updated = ctx.with_log_file(log_file_name_prefix)
    set_execution_context(updated)
    return get_log_fh_name()


def get_log_fh() -> Any:
    """Return the underlying GOELogFileHandle for the active ExecutionContext, if any."""
    ctx = current_execution_context()
    if ctx is None or ctx.log_file_sink is None:
        return None
    return ctx.log_file_sink.handle


def get_log_fh_name() -> str | None:
    """Return the file path of the active ExecutionContext log file, if any."""
    ctx = current_execution_context()
    if ctx is None or ctx.log_file_sink is None:
        return None
    return ctx.log_file_sink.name


def log_close() -> None:
    """Close the active ExecutionContext sinks and clear the active context."""
    ctx = current_execution_context()
    if ctx is None:
        return
    ctx.close()
    set_execution_context(None)


def log(
    line: str,
    detail: int = NORMAL,
    ansi_code: str | list[str] | tuple[str, ...] | None = None,
    ts: bool = False,
) -> None:
    """Emit a log line through the active ExecutionContext (or a default console context)."""
    ctx = current_execution_context()
    if ctx is None:
        ctx = ExecutionContext.for_console()
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if ts else None
    norm_ansi = tuple(ansi_code) if isinstance(ansi_code, (list, tuple)) else ansi_code
    ctx.emit(
        LogEvent(
            line=str(line),
            detail=detail,
            ansi_code=norm_ansi,
            timestamp_str=ts_str,
        )
    )


def log_timestamp() -> None:
    """Emit a grey timestamp line at VERBOSE detail."""
    now_str = datetime.now().replace(microsecond=0).isoformat(" ")
    log(now_str, detail=VERBOSE, ansi_code="grey")


def log_command_line(to_obscure: list[dict[str, str]] | None = None) -> None:
    """Log the current command-line invocation at VVERBOSE detail with sensitive values obscured."""
    items = [
        {"item": "--ora-adm-pass"},
        {"item": "--ora-app-pass"},
        {"item": "--hive-pass"},
        {"item": "--Sqoop-pass"},
        {"item": "--ldap-password"},
        *(to_obscure or []),
    ]
    log("Command line: " + " ".join(obscure_list_items(sys.argv, items)), detail=VVERBOSE)
