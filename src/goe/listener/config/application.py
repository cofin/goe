# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Listener Configuration Settings."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from goe.config.config_file import load_env
from goe.config.orchestration_config import OrchestrationConfig

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
APP_DIR: Path = Path(BASE_DIR / "listener")
CONFIG_DIR: Path = Path(APP_DIR / "config")
FRONTEND_DIR: Path = Path(APP_DIR / "web")


@dataclass
class ListenerSettings:
    """Listener Configuration Object."""

    global_config: OrchestrationConfig | None = field(default_factory=lambda: _get_default_global_config())

    host: str = "0.0.0.0"
    port: int = 8085
    http_workers: int = 2
    reload: bool = False
    static_url: str = "/"
    static_path: str | None = None
    background_workers: int = 2
    shared_token: str | None = None
    certfile: str | None = None
    keyfile: str | None = None
    ssl_enabled: bool = False
    heartbeat_interval: int = 30

    def __post_init__(self) -> None:
        if self.global_config:
            if self.global_config.listener_host:
                self.host = self.global_config.listener_host
            if self.global_config.listener_port is not None:
                self.port = self.global_config.listener_port
            if self.global_config.listener_shared_token:
                self.shared_token = str(self.global_config.listener_shared_token)
            if self.global_config.listener_heartbeat_interval:
                self.heartbeat_interval = self.global_config.listener_heartbeat_interval

        if self.static_path is None:
            self.static_path = str(Path(FRONTEND_DIR / "public"))


@lru_cache
def get_listener_settings() -> ListenerSettings:
    """Get cached ListenerSettings."""
    return ListenerSettings()


def _get_default_global_config() -> OrchestrationConfig | None:
    try:
        load_env()
        return OrchestrationConfig.as_defaults(do_not_connect=True)
    except Exception:
        return None


settings: ListenerSettings = get_listener_settings()
