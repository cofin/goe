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
