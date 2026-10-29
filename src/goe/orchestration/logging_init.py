# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Logging, version helpers, and runtime initialization for GOE orchestration."""

import importlib.metadata
import logging
import os
import sys
from datetime import datetime
from typing import Any

from goe.offload.offload_messages import OffloadMessages
from goe.orchestration.constants import normal, verbose, vverbose
from goe.util.goe_log_fh import GOELogFileHandle
from goe.util.string_utils import standard_log_name

options: Any = None
log_fh: Any = None
suppress_stdout_override = False
ts: datetime | None = None


def ansi(line, ansi_code):
    return OffloadMessages.ansi_wrap(line, ansi_code, options.ansi)


def log(line, detail=normal, ansi_code=None):
    """Write a line to the orchestration log file and optionally stdout.

    It has been known for exceptions to be thrown before options is defined.
    """
    global log_fh

    def fh_log(line):
        log_fh.write((line or "") + "\n")
        log_fh.flush()

    def stdout_log(line):
        sys.stdout.write((line or "") + "\n")
        sys.stdout.flush()

    if not log_fh:
        log_fh = sys.stderr
    fh_log(line)
    if not options:
        stdout_log(line)
    elif options.quiet:
        stdout_log(".")
    elif (
        detail == normal or (detail <= verbose and options.verbose) or (detail <= vverbose and options.vverbose)
    ) and not suppress_stdout_override:
        line = ansi(line, ansi_code)
        stdout_log(line)


def get_log_fh():
    return log_fh


def log_command_line(detail=vverbose):
    log("Command line:", detail=detail)
    log(" ".join(sys.argv), detail=detail)
    log("", detail=detail)


def log_close():
    global log_fh
    log_fh.close()


def log_timestamp(ansi_code="grey"):
    global ts
    ts = datetime.now()
    ts = ts.replace(microsecond=0)
    log(ts.strftime("%c"), detail=verbose, ansi_code=ansi_code)


def version():
    offload_home = os.environ.get("OFFLOAD_HOME")
    if offload_home:
        version_file_path = os.path.join(offload_home, "version_build")
        if os.path.exists(version_file_path):
            with open(version_file_path) as version_file:
                return version_file.read().strip()
    try:
        return importlib.metadata.version("goe-framework")
    except Exception:
        return "1.1.1.dev0"


def comp_ver_check(frontend_api):
    v_goe = version()
    v_ora = frontend_api.goe_db_component_version()
    return v_goe == v_ora, v_goe, v_ora


def version_abort(check_version, frontend_api):
    match, v_goe, v_ora = comp_ver_check(frontend_api)
    if check_version and not match and ".dev" not in v_goe:
        return True, v_goe, v_ora
    return False, v_goe, v_ora


def strict_version_ready(version_string):
    """Our offload version can have -RC or -DEV (or both!) appended.

    In order to use GOEVersion we need to tidy this up and chop off anything after (and including) a hyphen.
    """
    version_string = version_string.split("-")[0] if version_string else version_string
    return version_string


def init_log(log_name):
    """Set tool (debug instrumentation) logging."""
    global log_fh

    current_log_name = standard_log_name(log_name)
    log_path = os.path.join(options.log_path, current_log_name)
    log_fh = GOELogFileHandle(log_path)

    if hasattr(options, "dev_log") and options.dev_log:
        logging_params = {
            "level": logging.getLevelName(options.dev_log_level.upper()),
            "format": "%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
        if options.dev_log.upper() == "FILE":
            dev_log_name = os.path.join(options.log_path, "dev_%s" % current_log_name)
            logging_params["filename"] = dev_log_name
        logging.basicConfig(**logging_params)


def get_log_fh_name():
    global log_fh
    return log_fh.name if log_fh else None


def init(options_i):
    global options
    options = options_i

    if options.version:
        print(version())
        sys.exit(0)
