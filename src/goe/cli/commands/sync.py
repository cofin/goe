# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe sync' subcommand for schema drift detection and DDL synchronization."""

import sys
from optparse import Values
from typing import TYPE_CHECKING, Any

import rich_click as click

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.cli.common import common_options, extract_common_options

if TYPE_CHECKING:
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

_LAZY_IMPORTS: LazyImportMap = {
    "ExecutionId": ("goe.orchestration.execution_id", "ExecutionId"),
    "OffloadMessages": ("goe.offload.offload_messages", "OffloadMessages"),
    "OrchestrationConfig": ("goe.config.orchestration_config", "OrchestrationConfig"),
    "get_log_fh": ("goe.goe", "get_log_fh"),
    "get_schema_sync_opts": ("goe.schema_sync.schema_sync", "get_schema_sync_opts"),
    "init": ("goe.goe", "init"),
    "init_log": ("goe.goe", "init_log"),
    "log_close": ("goe.goe", "log_close"),
    "normalise_schema_sync_options": ("goe.schema_sync.schema_sync", "normalise_schema_sync_options"),
    "orchestration_repo_client_factory": (
        "goe.persistence.factory.orchestration_repo_client_factory",
        "orchestration_repo_client_factory",
    ),
    "run_schema_sync": ("goe.schema_sync.schema_sync", "schema_sync"),
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
    repo_client = None
    try:
        config = OrchestrationConfig.from_dict({"verbose": options.verbose, "vverbose": options.vverbose})
        execution_id = ExecutionId()
        messages = OffloadMessages.from_options(options, log_fh=get_log_fh(), execution_id=execution_id)
        repo_client = orchestration_repo_client_factory(
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
