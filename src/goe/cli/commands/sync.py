# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe sync' subcommand for schema drift detection and DDL synchronization."""

import sys
from optparse import Values
from typing import Any

import rich_click as click

from goe.cli.common import common_options, extract_common_options
from goe.config.orchestration_config import OrchestrationConfig
from goe.goe import get_log_fh, init, init_log, log_close
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
@common_options
@click.pass_context
def sync(ctx: click.Context, **kwargs: Any) -> None:
    """Execute schema drift analysis and target evolution."""
    common_opts = extract_common_options(ctx, kwargs)
    parser = get_schema_sync_opts()
    defaults = parser.get_default_values()
    options_dict = defaults.__dict__.copy()
    options_dict.update(common_opts)

    for k, v in kwargs.items():
        if v is not None:
            options_dict[k] = v

    options = Values(options_dict)
    normalise_schema_sync_options(options)

    init(options)
    init_log("schema_sync")
    config = OrchestrationConfig.from_dict({"verbose": options.verbose, "vverbose": options.vverbose})
    execution_id = ExecutionId()
    messages = OffloadMessages.from_options(options, log_fh=get_log_fh(), execution_id=execution_id)
    repo_client = orchestration_repo_client_factory(
        config,
        messages,
        dry_run=bool(not options.execute),
        trace_action="repo_client(schema_sync)",
    )
    try:
        return_code = run_schema_sync(options, messages, execution_id, repo_client)
    finally:
        repo_client.close()
        log_close()

    if return_code:
        sys.exit(return_code)
