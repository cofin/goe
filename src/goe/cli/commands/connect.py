# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe connect' subcommand for pre-flight connectivity and environment validation."""

import rich_click as click

from goe.config.config_file import check_config_path
from goe.connect.connect import connect as run_connect


@click.command(
    name="connect",
    help="Validate connectivity to source RDBMS, cloud storage, backend DW, and Spark cluster.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--upgrade-environment-file",
    is_flag=True,
    help="Synchronize current offload.env with the latest template.",
)
@click.pass_context
def connect(ctx: click.Context, upgrade_environment_file: bool = False) -> None:
    """Run pre-flight connectivity tests and display status report."""
    check_config_path()
    run_connect()
