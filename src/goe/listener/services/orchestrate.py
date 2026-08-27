# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Orchestration runner service for GOE Listener."""

import logging
from typing import Any

from goe.orchestration.orchestration_runner import OrchestrationRunner

logger = logging.getLogger(__name__)

_runner: OrchestrationRunner | None = None


def get_orchestration_runner() -> OrchestrationRunner:
    """Lazily get or initialize OrchestrationRunner."""
    global _runner
    if _runner is None:
        _runner = OrchestrationRunner(suppress_stdout=True)
    return _runner


class LazyOrchestrationRunner:
    """Proxy object delegating to lazily initialized OrchestrationRunner."""

    def offload(self, *args: Any, **kwargs: Any) -> Any:
        return get_orchestration_runner().offload(*args, **kwargs)


orchestration_runner = LazyOrchestrationRunner()
