# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared CLI options and context merging helpers for the unified GOE CLI."""

import os
from collections.abc import Callable
from typing import Any

import rich_click as click

from goe.cli.console import console, heading_console
from goe.util.goe_version import goe_version

COMMON_OPTION_KEYS: tuple[str, ...] = (
    "verbose",
    "vverbose",
    "quiet",
    "no_ansi",
    "log_path",
    "log_level",
    "ver_check",
    "error_before_step",
    "error_after_step",
    "error_on_token",
    "suppress_stdout",
)


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Print the GOE version banner and exit when --version is passed."""
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"goe version {goe_version()}")
    ctx.exit(0)


def common_options(func: Callable[..., Any]) -> Callable[..., Any]:
    """Attach standard GOE global and hidden diagnostic options to a Click command or group."""
    options = [
        click.option(
            "--version",
            is_flag=True,
            is_eager=True,
            expose_value=False,
            callback=_print_version,
            help="Show the version and exit.",
        ),
        click.option(
            "-v",
            "--verbose",
            "verbose",
            is_flag=True,
            default=None,
            help="Enable verbose output.",
        ),
        click.option(
            "--vv",
            "--vverbose",
            "vverbose",
            is_flag=True,
            default=None,
            help="Enable extra verbose output.",
        ),
        click.option(
            "-q",
            "--quiet",
            "quiet",
            is_flag=True,
            default=None,
            help="Suppress non-essential output.",
        ),
        click.option(
            "--no-ansi",
            "no_ansi",
            is_flag=True,
            default=None,
            help="Disable ANSI color codes.",
        ),
        click.option(
            "--log-path",
            "log_path",
            default=None,
            hidden=True,
            help="Override OFFLOAD_LOGFILE environment setting.",
        ),
        click.option(
            "--log-level",
            "log_level",
            default=None,
            hidden=True,
            help="Set log level (info, debug).",
        ),
        click.option(
            "--no-version-check",
            "ver_check",
            is_flag=True,
            flag_value=False,
            default=None,
            hidden=True,
            help="Disable GOE component version verification.",
        ),
        click.option(
            "--error-before-step",
            "error_before_step",
            default=None,
            hidden=True,
            help="Raise synthetic error before specified orchestration step.",
        ),
        click.option(
            "--error-after-step",
            "error_after_step",
            default=None,
            hidden=True,
            help="Raise synthetic error after specified orchestration step.",
        ),
        click.option(
            "--error-on-token",
            "error_on_token",
            default=None,
            hidden=True,
            help="Raise synthetic error when specified message token is logged.",
        ),
        click.option(
            "--suppress-stdout",
            "suppress_stdout",
            is_flag=True,
            default=None,
            hidden=True,
            help="Suppress standard output stream in OffloadMessages.",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def extract_common_options(ctx: click.Context | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Pop common option keys from kwargs, merge with root context, and return normalized options."""
    parent_obj: dict[str, Any] = {}
    if ctx is not None:
        ctx.ensure_object(dict)
        if isinstance(ctx.obj, dict):
            parent_obj = dict(ctx.obj)

    popped: dict[str, Any] = {key: kwargs.pop(key, None) for key in COMMON_OPTION_KEYS}

    verbose = bool(popped["verbose"] or parent_obj.get("verbose", False))
    vverbose = bool(popped["vverbose"] or parent_obj.get("vverbose", False))
    quiet = bool(popped["quiet"] or parent_obj.get("quiet", False))
    no_ansi = bool(popped["no_ansi"] or parent_obj.get("no_ansi", False))
    suppress_stdout = bool(popped["suppress_stdout"] or parent_obj.get("suppress_stdout", False))

    log_path = popped["log_path"] if popped["log_path"] is not None else parent_obj.get("log_path")
    if log_path is None:
        log_path = os.environ.get("OFFLOAD_LOGFILE")

    log_level = popped["log_level"] if popped["log_level"] is not None else parent_obj.get("log_level")
    if log_level is None:
        log_level = "info"

    if popped["ver_check"] is not None:
        ver_check = bool(popped["ver_check"])
    elif "ver_check" in parent_obj and parent_obj["ver_check"] is not None:
        ver_check = bool(parent_obj["ver_check"])
    else:
        ver_check = True

    error_before_step = (
        popped["error_before_step"] if popped["error_before_step"] is not None else parent_obj.get("error_before_step")
    )
    error_after_step = (
        popped["error_after_step"] if popped["error_after_step"] is not None else parent_obj.get("error_after_step")
    )
    error_on_token = (
        popped["error_on_token"] if popped["error_on_token"] is not None else parent_obj.get("error_on_token")
    )

    console.no_color = no_ansi
    heading_console.no_color = no_ansi

    resolved_ctx = {
        "verbose": verbose,
        "vverbose": vverbose,
        "quiet": quiet,
        "no_ansi": no_ansi,
        "ansi": not no_ansi,
        "log_path": log_path,
        "log_level": log_level,
        "ver_check": ver_check,
        "error_before_step": error_before_step,
        "error_after_step": error_after_step,
        "error_on_token": error_on_token,
        "suppress_stdout": suppress_stdout,
    }
    if ctx is not None and isinstance(ctx.obj, dict):
        ctx.obj.update(resolved_ctx)

    return {
        "verbose": verbose,
        "vverbose": vverbose,
        "quiet": quiet,
        "ansi": not no_ansi,
        "log_path": log_path,
        "log_level": log_level,
        "ver_check": ver_check,
        "error_before_step": error_before_step,
        "error_after_step": error_after_step,
        "error_on_token": error_on_token,
        "suppress_stdout": suppress_stdout,
    }
