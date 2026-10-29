# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Functions used as entry points for Orchestration CLI commands."""

from __future__ import annotations

import sys
from typing import Any

from goe.config.orchestration_config import OrchestrationConfig
from goe.observability.runtime import ensure_observability
from goe.orchestration.constants import OFFLOAD_OP_NAME, verbose
from goe.orchestration.logging_init import (
    get_log_fh,
    get_log_fh_name,
    init,
    init_log,
    log,
    log_close,
    log_command_line,
    log_timestamp,
    version,
)
from goe.orchestration.orchestration_runner import OrchestrationRunner
from goe.orchestration.stages.plan_resolution import normalise_options
from goe.util.goe_log import log_exception


def offload_by_cli(options: Any, messages_override: Any = None) -> None:
    """CLI entrypoint for Offload."""
    ensure_observability(options)
    init(options)
    init_log("offload_%s" % options.owner_table)

    try:
        log("")
        log("Offload v%s" % version(), ansi_code="underline")
        log("Log file: %s" % get_log_fh_name())
        log("")
        log_command_line()

        options.operation_name = OFFLOAD_OP_NAME
        normalise_options(options)

        config_overrides = {
            "verbose": options.verbose,
            "vverbose": options.vverbose,
            "offload_transport_dsn": options.offload_transport_dsn,
            "error_on_token": options.error_on_token,
        }
        config = OrchestrationConfig.from_dict(config_overrides)

        config.log_connectivity_messages(lambda m: log(m, detail=verbose))

        OrchestrationRunner(settings=config).offload(
            options,
            reuse_log=True,
            messages_override=messages_override,
        )

        log_close()
    except Exception as exc:
        log("Exception caught at top-level", ansi_code="red")
        log_timestamp()
        log_exception(exc, log_fh=get_log_fh(), options=options)
        log_close()
        sys.exit(1)
