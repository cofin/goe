# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
