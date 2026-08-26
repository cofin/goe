#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""goe_log: GOE general logging routines

Replacement of 'loggers' from goe.py that avoid globals
and do not rely on 'expected' parameter structure
"""

import logging
import sys
import traceback
from argparse import Namespace
from datetime import datetime

from goe.offload.offload_messages import (
    NORMAL,
    VERBOSE,
    VERBOSENESS,
    VVERBOSE,
    OffloadMessages,
)
from goe.util.misc_functions import get_option

###############################################################################
# LOGGING
###############################################################################
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())  # Disabling logging by default

###############################################################################
# GLOBALS
###############################################################################
global_log_fh = None


def set_option(options, opt, val):
    """Set 'opt' attribute in 'options' object
    with special processing for 'verbose' options
    """
    assert options and opt

    setattr(options, opt, val)

    # If verboseness 'level' is supplied and is set to True
    # make all other 'levels' False
    opt = opt.lower()
    if opt in VERBOSENESS and val:
        minus_opts = tuple(VERBOSENESS - set((opt,)))
        for m_opt in minus_opts:
            setattr(options, m_opt, False)


def get_default_options(addons=None):
    """'Sensible defaults' for 'options' object used in this module's routines"""

    options = Namespace()
    set_option(options, "ansi", False)
    set_option(options, "normal", True)

    if addons:
        for add_opt in addons:
            set_option(options, add_opt, addons[add_opt])

    return options


def get_default_log():
    return global_log_fh


def log(line, detail=NORMAL, ansi_code=None, log_fh=None, options=get_default_options()):
    # Log to a (text, on disk) log file
    log_handle = log_fh or global_log_fh
    if log_handle:
        log_handle.write(line + "\n")
        log_handle.flush()

    # Log to screen
    if get_option(options, "quiet"):
        sys.stdout.write(".")
        sys.stdout.flush()
    elif (
        detail == NORMAL
        or (detail <= VERBOSE and get_option(options, "verbose"))
        or (detail <= VVERBOSE and get_option(options, "vverbose"))
    ):
        line = ansi(line, ansi_code, options=options)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log_exception(exception, detail=NORMAL, log_fh=None, options=get_default_options()):
    log_handle = log_fh or global_log_fh
    if log_handle and log_handle != sys.stderr:
        log_handle.write(traceback.format_exc() + "\n")
        log_handle.flush()

    if detail > NORMAL or get_option(options, "verbose") or get_option(options, "vverbose"):
        sys.stdout.write(traceback.format_exc() + "\n")
        sys.stdout.flush()
    else:
        sys.stdout.write("%s: %s \n" % (str(type(exception).__name__), str(exception)))
        sys.stdout.flush()


def ansi(line, ansi_code, options=get_default_options()):
    return OffloadMessages.ansi_wrap(line, ansi_code, get_option(options, "ansi"))


def log_timestamp(ansi_code="grey", options=get_default_options()):
    if get_option(options, "execute"):
        ts = datetime.now()
        ts = ts.replace(microsecond=0)
        log(ts.strftime("%c"), detail=VERBOSE, ansi_code=ansi_code, options=options)
        return ts
    return None


def log_timedelta(start_time, ansi_code="grey", options=get_default_options()):
    if get_option(options, "execute"):
        ts2 = datetime.now()
        ts2 = ts2.replace(microsecond=0)
        log(
            "Step time: %s" % (ts2 - start_time),
            detail=VERBOSE,
            ansi_code=ansi_code,
            options=options,
        )
        return ts2 - start_time
