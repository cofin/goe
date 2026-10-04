# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe connect' subcommand for pre-flight connectivity and environment validation."""

from optparse import Values
from typing import Any

import rich_click as click

from goe.cli.common import common_options, extract_common_options
from goe.config.config_file import check_config_path
from goe.connect.connect import connect as run_connect
from goe.connect.connect import get_connect_opts


@click.command(
    name="connect",
    help="Validate connectivity to source RDBMS, cloud storage, backend DW, and Spark cluster.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--upgrade-environment-file",
    "upgrade_environment_file",
    is_flag=True,
    default=False,
    help="Synchronize current offload.env with the latest template.",
)
@click.option(
    "--create-backend-db",
    "create_backend_db",
    is_flag=True,
    default=None,
    hidden=True,
    help="Create backend database/dataset during connectivity check if missing.",
)
@common_options
@click.pass_context
def connect(
    ctx: click.Context,
    upgrade_environment_file: bool = False,
    create_backend_db: bool | None = None,
    **kwargs: Any,
) -> None:
    """Run pre-flight connectivity tests and display status report."""
    common_opts = extract_common_options(ctx, kwargs)
    check_config_path()
    parser = get_connect_opts()
    defaults = parser.get_default_values()
    options_dict = defaults.__dict__.copy()
    options_dict.update(common_opts)

    options_dict["upgrade_environment_file"] = upgrade_environment_file
    if create_backend_db is not None:
        options_dict["create_backend_db"] = create_backend_db
    run_connect(Values(options_dict))
