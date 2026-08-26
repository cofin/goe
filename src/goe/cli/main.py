# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Main CLI entry point and root command for the GOE framework."""

import sys

import rich_click as click

from goe.cli import config
from goe.cli.commands.connect import connect
from goe.cli.commands.listener import listener
from goe.cli.commands.logmgr import logmgr
from goe.cli.commands.offload import offload
from goe.cli.commands.report import report
from goe.cli.commands.sync import sync
from goe.cli.commands.validate import validate
from goe.cli.console import print_error, print_heading
from goe.util.goe_version import goe_version


@click.group(
    name="goe",
    help="[bold blue]Gluent Offload Engine (GOE)[/bold blue]\n\n"
    "High-performance offloading, schema synchronization, and data validation between RDBMS and cloud data warehouses.\n\n"
    "[dim]Documentation: https://github.com/gluent/goe[/dim]",
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose output.",
)
@click.option(
    "--vv",
    "--vverbose",
    "vverbose",
    is_flag=True,
    help="Enable extra verbose output.",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress non-essential output.",
)
@click.option(
    "--no-ansi",
    is_flag=True,
    help="Disable ANSI color codes.",
)
@click.version_option(
    version=goe_version(),
    prog_name="goe",
    message="%(prog)s version %(version)s",
)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose: bool = False,
    vverbose: bool = False,
    quiet: bool = False,
    no_ansi: bool = False,
) -> None:
    """Main GOE CLI entry point."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["vverbose"] = vverbose
    ctx.obj["quiet"] = quiet
    ctx.obj["no_ansi"] = no_ansi

    if ctx.invoked_subcommand is not None:
        print_heading(ctx.invoked_subcommand)
    else:
        print_heading()
        click.echo(ctx.get_help())


cli.add_command(offload)
cli.add_command(connect)
cli.add_command(validate)
cli.add_command(sync)
cli.add_command(report)
cli.add_command(listener)
cli.add_command(logmgr)


def main() -> None:
    """CLI execution entrypoint."""
    try:
        cli()
    except SystemExit:
        raise
    except Exception as exc:
        print_error(f"Fatal error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
