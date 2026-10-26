# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Validate that data in frontend RDBMS matches backend data warehouse via aggregates."""

import logging
import sys
from typing import Any, cast

from goe.config.options import AggValidateOptions
from goe.config.orchestration_config import OrchestrationConfig
from goe.exceptions import GOEError
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
    CrossDbValidationBuilder,
    CrossDbValidator,
)
from goe.orchestration import command_steps
from goe.util.goe_log import log_exception
from goe.util.string_utils import (
    csv_split,
    is_number,
    is_pos_int,
)

__all__ = (
    "DEFAULT_AGGS",
    "GROUPBY_PARTITIONS",
    "PROG_BANNER",
    "SUPPORTED_OPERATIONS",
    "AggValidateException",
    "post_process_args",
    "print_title",
    "run_agg_validate",
    "set_logging",
    "validate_table",
)


class AggValidateException(Exception):
    """Raised when agg_validate option parsing or execution fails."""


PROG_BANNER = "Validate (agg_validate) v%s" % version()

logger = logging.getLogger("agg_validate")


def validate_table(args: Any, messages: Any) -> bool:
    """Validate a specific table using CrossDbValidator."""

    def step_fn() -> bool:
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
        if getattr(args, "diff", False) and args.execute:
            diff_rows = validator.run_row_diff()
            if diff_rows:
                messages.warning(f"Row-level diff detected {len(diff_rows)} differing group row(s): {diff_rows}")
        messages.log("[ERROR]", ansi_code="red")
        return False

    return bool(
        messages.offload_step(
            command_steps.STEP_VALIDATE_DATA,
            step_fn,
            execute=args.execute,
        )
    )


def set_logging(log_level: str | None) -> None:
    """Set global logging parameters."""
    if log_level:
        logging.basicConfig(
            level=logging.getLevelName(log_level),
            format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def print_title() -> None:
    """Print utility title."""
    sys.stdout.write(f"{PROG_BANNER}\n\n")


def post_process_args(args: AggValidateOptions) -> None:
    """Post-process and AST-validate CLI arguments."""
    if isinstance(args.filters, str) and args.filters:
        builder = CrossDbValidationBuilder("oracle")
        try:
            args.filters = cast(list[tuple[str, str, object]], builder.parse_filter_tuples(args.filters))
        except GOEError as exc:
            raise AggValidateException(f"Invalid FILTER expression: {args.filters}") from exc
    if args.selects:
        if isinstance(args.selects, (list, str)) and len(args.selects) == 1 and is_number(args.selects[0]):
            args.selects = args.selects[0]
        elif isinstance(args.selects, str):
            args.selects = list[str | int](csv_split(args.selects))
    if isinstance(args.group_bys, str) and args.group_bys and args.group_bys != GROUPBY_PARTITIONS:
        args.group_bys = csv_split(args.group_bys)
    if (
        isinstance(args.aggregate_functions, str)
        and args.aggregate_functions
        and args.aggregate_functions != DEFAULT_AGGS
    ):
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
