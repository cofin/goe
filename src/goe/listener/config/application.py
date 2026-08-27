# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Listener Configuration Settings."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from goe.config.orchestration_config import OrchestrationConfig

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
APP_DIR: Path = Path(BASE_DIR / "listener")
CONFIG_DIR: Path = Path(APP_DIR / "config")
FRONTEND_DIR: Path = Path(APP_DIR / "web")


def _get_default_global_config() -> OrchestrationConfig | None:
    try:
        return OrchestrationConfig.as_defaults(do_not_connect=True)
    except Exception:
        return None


@dataclass
class ListenerSettings:
    """Listener Configuration Object."""

    global_config: OrchestrationConfig | None = field(default_factory=_get_default_global_config)

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
    redis_host: str | None = None
    redis_port: int = 6379
    redis_db: int = 0
    redis_username: str | None = None
    redis_password: str | None = None
    redis_ssl: bool = False
    redis_ssl_cert: str | None = None
    redis_use_sentinel: bool = False
    redis_sentinel_master: str = "goe-listener"

    def __post_init__(self) -> None:
        if self.global_config:
            if getattr(self.global_config, "listener_host", None):
                self.host = self.global_config.listener_host
            if getattr(self.global_config, "listener_port", None):
                self.port = self.global_config.listener_port
            if getattr(self.global_config, "listener_shared_token", None):
                self.shared_token = str(self.global_config.listener_shared_token)
            if getattr(self.global_config, "listener_heartbeat_interval", None):
                self.heartbeat_interval = self.global_config.listener_heartbeat_interval
            if getattr(self.global_config, "listener_redis_host", None):
                self.redis_host = self.global_config.listener_redis_host
            if getattr(self.global_config, "listener_redis_port", None):
                self.redis_port = self.global_config.listener_redis_port
            if getattr(self.global_config, "listener_redis_db", None):
                self.redis_db = self.global_config.listener_redis_db
            if getattr(self.global_config, "listener_redis_username", None):
                self.redis_username = self.global_config.listener_redis_username
            if getattr(self.global_config, "listener_redis_password", None):
                self.redis_password = str(self.global_config.listener_redis_password)
            if getattr(self.global_config, "listener_redis_use_ssl", None):
                self.redis_ssl = bool(self.global_config.listener_redis_use_ssl)
            if getattr(self.global_config, "listener_redis_ssl_cert", None):
                self.redis_ssl_cert = self.global_config.listener_redis_ssl_cert

        if self.static_path is None:
            self.static_path = str(Path(FRONTEND_DIR / "public"))

    @property
    def redis_url(self) -> str:
        """Returns a redis/valkey url to connect to."""
        proto = "rediss" if self.redis_ssl else "redis"
        if not self.redis_password:
            return f"{proto}://{self.redis_host or '127.0.0.1'}:{self.redis_port}/{self.redis_db}"
        return f"{proto}://:{self.redis_password}@{self.redis_host or '127.0.0.1'}:{self.redis_port}/{self.redis_db}"

    @property
    def db_config(self) -> dict:
        return {
            "host": self.redis_host,
            "port": self.redis_port,
            "db": self.redis_db,
            "username": self.redis_username,
            "password": self.redis_password,
            "ssl": self.redis_ssl,
            "ssl_cert": self.redis_ssl_cert,
            "use_sentinel": self.redis_use_sentinel,
            "sentinel_master": self.redis_sentinel_master,
        }


@lru_cache
def get_listener_settings() -> ListenerSettings:
    """Get cached ListenerSettings."""
    return ListenerSettings()


settings: ListenerSettings = get_listener_settings()
