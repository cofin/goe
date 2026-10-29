# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe sync' subcommand for schema drift detection and DDL synchronization."""

import sys
from typing import TYPE_CHECKING, Any

import rich_click as click

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.cli.common import common_options, extract_common_options

if TYPE_CHECKING:
    from goe.config.options import SchemaSyncOptions
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.registry import create_repository_client
    from goe.orchestration.execution_id import ExecutionId
    from goe.orchestration.logging_init import get_log_fh, init, init_log, log_close
    from goe.sync.differ import (
        normalise_schema_sync_options,
        run_schema_sync,
    )

_LAZY_IMPORTS: LazyImportMap = {
    "ExecutionId": ("goe.orchestration.execution_id", "ExecutionId"),
    "OffloadMessages": ("goe.offload.offload_messages", "OffloadMessages"),
    "OrchestrationConfig": ("goe.config.orchestration_config", "OrchestrationConfig"),
    "SchemaSyncOptions": ("goe.config.options", "SchemaSyncOptions"),
    "SchemaSyncService": ("goe.sync.differ", "SchemaSyncService"),
    "create_repository_client": ("goe.offload.registry", "create_repository_client"),
    "get_log_fh": ("goe.orchestration.logging_init", "get_log_fh"),
    "init": ("goe.orchestration.logging_init", "init"),
    "init_log": ("goe.orchestration.logging_init", "init_log"),
    "log_close": ("goe.orchestration.logging_init", "log_close"),
    "normalise_schema_sync_options": ("goe.sync.differ", "normalise_schema_sync_options"),
    "run_schema_sync": ("goe.sync.differ", "run_schema_sync"),
}


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
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    common_opts = extract_common_options(ctx, kwargs)
    overrides: dict[str, Any] = dict(common_opts)
    overrides.update({key: value for key, value in kwargs.items() if value is not None})
    options = SchemaSyncOptions.from_mapping(overrides)
    normalise_schema_sync_options(options)

    init(options)
    init_log("schema_sync")
    repo_client = None
    try:
        config = OrchestrationConfig.from_dict({"verbose": options.verbose, "vverbose": options.vverbose})
        execution_id = ExecutionId()
        messages = OffloadMessages.from_options(options, log_fh=get_log_fh(), execution_id=execution_id)
        repo_client = create_repository_client(
            config,
            messages,
            dry_run=bool(not options.execute),
            trace_action="repo_client(schema_sync)",
        )
        return_code = run_schema_sync(options, messages, execution_id, repo_client)
    finally:
        if repo_client is not None:
            repo_client.close()
        log_close()

    if return_code:
        sys.exit(return_code)


def __getattr__(name: str) -> Any:
    """Lazily import schema_sync and orchestration dependencies on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
