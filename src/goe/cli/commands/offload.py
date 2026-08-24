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

"""'goe offload' subcommand for high-performance data offloading."""

from optparse import Values

import rich_click as click

from goe.goe import get_options
from goe.orchestration.cli_entry_points import offload_by_cli


@click.command(
    name="offload",
    help="Offload datasets from RDBMS sources to modern cloud data warehouses.",
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
    "--target",
    help="Backend target query engine.",
)
@click.option(
    "--target-name",
    "target_owner_name",
    help="Override target owner and/or table name in OWNER.TABLE format.",
)
@click.option(
    "-x",
    "--execute",
    is_flag=True,
    help="Perform operations, rather than dry-run preview.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Force offload execution without interactive confirmation.",
)
@click.option(
    "--skip-steps",
    "skip",
    help="Comma-separated list of step IDs to skip.",
)
@click.option(
    "--ddl-file",
    help="Path to write generated target DDL.",
)
@click.option(
    "--create-backend-db",
    is_flag=True,
    help="Create target backend database/dataset if missing.",
)
@click.option(
    "--reset-backend-table",
    is_flag=True,
    help="Drop and recreate existing backend target table.",
)
@click.option(
    "--reuse-backend-table",
    is_flag=True,
    help="Append to existing backend target table.",
)
@click.option(
    "--reset-hybrid-view",
    is_flag=True,
    help="Drop and recreate existing hybrid view.",
)
@click.option(
    "--purge",
    is_flag=True,
    help="Purge staged data files from cloud storage after completion.",
)
@click.option(
    "--preserve-load-table",
    is_flag=True,
    help="Do not drop staging load table on success.",
)
@click.option(
    "--offload-type",
    help="Offload mode: FULL or INCREMENTAL.",
)
@click.option(
    "--older-than-date",
    help="Incremental boundary: Offload partitions older than YYYY-MM-DD.",
)
@click.option(
    "--older-than-days",
    type=int,
    help="Incremental boundary: Offload partitions older than N days.",
)
@click.option(
    "--less-than-value",
    help="Incremental boundary: Offload partitions less than value.",
)
@click.option(
    "--equal-to-values",
    help="Incremental boundary: Offload partitions matching values (CSV).",
)
@click.option(
    "--partition-names",
    help="Explicit CSV list of source partition names to offload.",
)
@click.option(
    "--offload-transport-method",
    help="Transport engine: SPARK_DATAPROC, SPARK_SUBMIT, or AUTO.",
)
@click.option(
    "--offload-transport-parallelism",
    type=int,
    help="Degree of parallel JDBC extraction connections.",
)
@click.option(
    "--offload-transport-dsn",
    help="Source connection string override for transport tasks.",
)
@click.pass_context
def offload(ctx: click.Context, **kwargs) -> None:
    """Execute offload operation with provided options."""
    parser = get_options()
    defaults = parser.get_default_values()
    options_dict = defaults.__dict__.copy()

    if ctx.obj:
        options_dict.update(
            {
                "verbose": ctx.obj.get("verbose", False),
                "vverbose": ctx.obj.get("vverbose", False),
                "quiet": ctx.obj.get("quiet", False),
                "ansi": not ctx.obj.get("no_ansi", False),
            }
        )

    for k, v in kwargs.items():
        if v is not None:
            options_dict[k] = v

    options = Values(options_dict)
    offload_by_cli(options)
