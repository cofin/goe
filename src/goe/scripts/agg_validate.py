#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

##########################################################################
# agg_validate: Check data consistency between Oracle and backend
#     by comparing "column aggregate_functions" (min, max, count, ...) between the two
#
##########################################################################

import logging
import re
import sys

from goe.config.options import AggValidateOptions
from goe.config.orchestration_config import OrchestrationConfig
from goe.goe import (
    get_log_fh,
    get_log_fh_name,
    init,
    init_log,
    log,
    log_timestamp,
    normalise_owner_table_options,
    version,
)
from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_validation import (
    DEFAULT_AGGS,
    GROUPBY_PARTITIONS,
    SUPPORTED_OPERATIONS,
    CrossDbValidator,
)
from goe.orchestration import command_steps
from goe.util.goe_log import log_exception
from goe.util.misc_functions import (
    csv_split,
    is_number,
    is_pos_int,
    parse_python_from_string,
)


# -----------------------------------------------------------------------
# EXCEPTIONS
# -----------------------------------------------------------------------
class AggValidateException(Exception):
    pass


# -----------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------

PROG_BANNER = "Validate (agg_validate) v%s" % version()

REGEX_FILTER = re.compile(r"(\S+)\s+(%s)\s+(\S+)" % "|".join(SUPPORTED_OPERATIONS), re.IGNORECASE)


# -----------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------
logger = logging.getLogger("agg_validate")


# -----------------------------------------------------------------------
# SCRIPT ROUTINES
# -----------------------------------------------------------------------


def validate_table(args, messages):
    """Validate specific table"""

    def step_fn():
        config = OrchestrationConfig.from_dict({"verbose": args.verbose})
        validator = CrossDbValidator(
            db_name=args.owner,
            table_name=args.table_name,
            connection_options=config,
            messages=messages,
        )

        status, _ = validator.validate(
            selects=args.selects,
            filters=args.filters,
            group_bys=args.group_bys,
            aggs=args.aggregate_functions,
            safe=not args.skip_boundary_check,
            as_of_scn=args.as_of_scn,
            execute=args.execute,
            frontend_parallelism=args.frontend_parallelism,
        )
        if status:
            messages.log("[OK]", ansi_code="green")
            return True
        messages.log("[ERROR]", ansi_code="red")
        return False

    return (
        messages.offload_step(
            command_steps.STEP_VALIDATE_DATA,
            step_fn,
            execute=args.execute,
        )
        or False
    )


def set_logging(log_level):
    """Set "global" logging parameters"""

    logging.basicConfig(
        level=logging.getLevelName(log_level),
        format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_title():
    """Print utility title"""

    print("%s\n" % (PROG_BANNER))


def post_process_args(args: AggValidateOptions) -> None:
    """Post process arguments"""

    def parse_filters(filters):
        def parse_single_filter(filt):
            match = REGEX_FILTER.match(filt)
            if match:
                return (
                    match.group(1),
                    match.group(2),
                    parse_python_from_string(match.group(3)),
                )
            raise AggValidateException("Invalid FILTER expression: %s" % filt)

        return [parse_single_filter(_.strip()) for _ in filters.split(",")]

    if args.filters:
        args.filters = parse_filters(args.filters)
    if args.selects:
        if len(args.selects) == 1 and is_number(args.selects[0]):
            args.selects = args.selects[0]
        else:
            args.selects = csv_split(args.selects)
    if args.group_bys and args.group_bys != GROUPBY_PARTITIONS:
        args.group_bys = csv_split(args.group_bys)
    if args.aggregate_functions and args.aggregate_functions != DEFAULT_AGGS:
        args.aggregate_functions = csv_split(args.aggregate_functions)
    if args.frontend_parallelism:
        if not is_pos_int(args.frontend_parallelism):
            raise AggValidateException("Invalid frontend parallelism: %s" % args.frontend_parallelism)
        args.frontend_parallelism = int(args.frontend_parallelism)


def run_agg_validate(args: AggValidateOptions) -> bool:
    """Run aggregate validation with parsed args namespace."""
    init(args)
    init_log("agg_validate_%s" % args.owner_table)
    log("")
    log(PROG_BANNER, ansi_code="underline")
    log("Log file: %s" % get_log_fh_name())

    normalise_owner_table_options(args)
    set_logging(args.dev_log_level)

    try:
        messages = OffloadMessages.from_options(args)
        return validate_table(args=args, messages=messages)
    except Exception as exc:
        log("Exception caught at top-level", ansi_code="red")
        log_timestamp()
        log_exception(exc, log_fh=get_log_fh(), options=args)
        sys.exit(1)
