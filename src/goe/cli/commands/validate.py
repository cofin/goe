# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe validate' subcommand for cross-database aggregation validation."""

import sys
from typing import TYPE_CHECKING, Any

import rich_click as click

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.cli.common import common_options, extract_common_options

if TYPE_CHECKING:
    from goe.config.options import AggValidateOptions
    from goe.offload.offload_validation import (
        post_process_args,
        run_agg_validate,
    )

_LAZY_IMPORTS: LazyImportMap = {
    "AggValidateOptions": ("goe.config.options", "AggValidateOptions"),
    "post_process_args": ("goe.offload.offload_validation", "post_process_args"),
    "run_agg_validate": ("goe.offload.offload_validation", "run_agg_validate"),
}


@click.command(
    name="validate",
    help="Validate data consistency between source RDBMS and target DW via aggregate comparisons.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "-t",
    "--table",
    "owner_table",
    required=True,
    help="Required. Source schema and table name in OWNER.TABLE format.",
)
@click.option(
    "--target-name",
    "target_owner_name",
    default=None,
    help="Override target schema and table name in OWNER.TABLE format.",
)
@click.option(
    "-x",
    "--execute/--no-execute",
    is_flag=True,
    default=False,
    help="Execute comparison queries, rather than dry-run SQL preview.",
)
@click.option(
    "-S",
    "--selects",
    help="Comma-separated list of column names or expressions to validate.",
)
@click.option(
    "-F",
    "--filters",
    help="Filter expressions applied to both source and target queries.",
)
@click.option(
    "-G",
    "--group-bys",
    help="Comma-separated column names for GROUP BY verification.",
)
@click.option(
    "-A",
    "--aggregate-functions",
    help="Comma-separated aggregate functions (COUNT, MIN, MAX, SUM, AVG).",
)
@click.option(
    "--as-of-scn",
    type=int,
    help="Oracle System Change Number (SCN) for snapshot-consistent validation.",
)
@click.option(
    "--frontend-parallelism",
    type=int,
    help="Degree of parallel execution threads on source database.",
)
@click.option(
    "--skip-boundary-check",
    is_flag=True,
    default=None,
    help="Skip partition boundary checks during validation.",
)
@click.option(
    "--diff",
    is_flag=True,
    default=False,
    help="Perform an in-memory DuckDB EXCEPT row diff on mismatched groups.",
)
@click.option(
    "--dev-log-level",
    "dev_log_level",
    default=None,
    hidden=True,
    help="Development log level (info, debug).",
)
@common_options
@click.pass_context
def validate(ctx: click.Context, **kwargs: Any) -> None:
    """Execute aggregate validation across databases."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    common_opts = extract_common_options(ctx, kwargs)
    overrides: dict[str, Any] = dict(common_opts)
    overrides.update({key: value for key, value in kwargs.items() if value is not None})
    options = AggValidateOptions.from_mapping(overrides)
    post_process_args(options)
    ret = run_agg_validate(options)
    sys.exit(0 if ret else 1)


def __getattr__(name: str) -> Any:
    """Lazily import agg_validate dependencies on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
