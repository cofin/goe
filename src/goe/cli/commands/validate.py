# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe validate' subcommand for cross-database aggregation validation."""

from optparse import Values

import rich_click as click

from goe.scripts.agg_validate import get_agg_validate_options, run_agg_validate


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
    "-x",
    "--execute",
    is_flag=True,
    default=True,
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
    help="Skip partition boundary boundary checks during validation.",
)
@click.pass_context
def validate(ctx: click.Context, **kwargs) -> None:
    """Execute aggregate validation across databases."""
    parser = get_agg_validate_options()
    defaults = parser.get_default_values()
    options_dict = defaults.__dict__.copy()

    if ctx.obj:
        options_dict.update(
            {
                "verbose": ctx.obj.get("verbose", False),
                "vverbose": ctx.obj.get("vverbose", False),
                "quiet": ctx.obj.get("quiet", False),
            }
        )

    for k, v in kwargs.items():
        if v is not None:
            options_dict[k] = v

    options = Values(options_dict)
    run_agg_validate(options)
