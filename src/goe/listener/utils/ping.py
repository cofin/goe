# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Simple utility to request status of GOE Listener."""

from typing import TYPE_CHECKING

import requests

from goe.orchestration.orchestration_constants import PRODUCT_NAME_GEL

STATUS_OK = "OK"

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig


def ping(orchestration_config: "OrchestrationConfig") -> bool:
    """Submit a status call to GOE Listener."""
    url = f"http://{orchestration_config.listener_host}:{orchestration_config.listener_port}/api/system/status/"
    headers = {"Content-Type": "application/json"}
    if orchestration_config.listener_shared_token:
        headers.update({"x-goe-console-key": str(orchestration_config.listener_shared_token)})
    r = requests.get(url, headers=headers)
    if r.ok:
        if r.json().get("status") == STATUS_OK:
            return True
        raise RuntimeError(f"{PRODUCT_NAME_GEL} not OK: {r.text}")
    raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
