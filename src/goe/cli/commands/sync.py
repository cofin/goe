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

"""'goe sync' subcommand for schema drift detection and DDL synchronization."""

from optparse import Values

import rich_click as click

from goe.config.orchestration_config import OrchestrationConfig
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.factory.orchestration_repo_client_factory import (
    orchestration_repo_client_factory,
)
from goe.schema_sync.schema_sync import (
    get_schema_sync_opts,
    normalise_schema_sync_options,
)
from goe.schema_sync.schema_sync import (
    schema_sync as run_schema_sync,
)


@click.command(
    name="sync",
    help="Inspect schema drift between source RDBMS and backend DW and apply synchronization DDL.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--include",
    default="*.*",
    help="CSV list of schemas or schema.tables to examine (supports wildcards, e.g. SH.*, *.SALES).",
)
@click.option(
    "-x",
    "--execute",
    is_flag=True,
    help="Apply evolution DDL directly to target backend, rather than previewing.",
)
@click.option(
    "--command-file",
    help="File path to record generated/applied evolution DDL commands.",
)
@click.pass_context
def sync(ctx: click.Context, **kwargs) -> None:
    """Execute schema drift analysis and target evolution."""
    parser = get_schema_sync_opts()
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
    normalise_schema_sync_options(options)

    config = OrchestrationConfig.from_dict({"verbose": options.verbose, "vverbose": options.vverbose})
    messages = OffloadMessages()
    execution_id = ExecutionId()
    repo_client = orchestration_repo_client_factory(
        config.target_dbtype,
        config,
        messages,
        dry_run=not options.execute,
    )
    run_schema_sync(options, messages, repo_client, config, execution_id)
