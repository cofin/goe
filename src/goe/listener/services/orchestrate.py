# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Factory for per-job OrchestrationRunner instances in the GOE Listener."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from goe.orchestration.orchestration_runner import OrchestrationRunner
from goe.orchestration.sinks import ExecutionSink

__all__ = ("create_orchestration_runner",)


def create_orchestration_runner(
    *,
    config_overrides: dict[str, Any] | None = None,
    settings: Any = None,
    sinks: Sequence[ExecutionSink] = (),
) -> OrchestrationRunner:
    """Construct a fresh OrchestrationRunner with stdout suppressed for a Listener job."""
    return OrchestrationRunner(
        config_overrides=config_overrides,
        suppress_stdout=True,
        settings=settings,
        sinks=sinks,
    )
