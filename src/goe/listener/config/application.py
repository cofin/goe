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
            if self.global_config.listener_host:
                self.host = self.global_config.listener_host
            if self.global_config.listener_port:
                self.port = self.global_config.listener_port
            if self.global_config.listener_shared_token:
                self.shared_token = str(self.global_config.listener_shared_token)
            if self.global_config.listener_heartbeat_interval:
                self.heartbeat_interval = self.global_config.listener_heartbeat_interval
            if self.global_config.listener_redis_host:
                self.redis_host = self.global_config.listener_redis_host
            if self.global_config.listener_redis_port:
                self.redis_port = self.global_config.listener_redis_port
            if self.global_config.listener_redis_db:
                self.redis_db = self.global_config.listener_redis_db
            if self.global_config.listener_redis_username:
                self.redis_username = self.global_config.listener_redis_username
            if self.global_config.listener_redis_password:
                self.redis_password = str(self.global_config.listener_redis_password)
            if self.global_config.listener_redis_use_ssl:
                self.redis_ssl = bool(self.global_config.listener_redis_use_ssl)
            if self.global_config.listener_redis_ssl_cert:
                self.redis_ssl_cert = self.global_config.listener_redis_ssl_cert

        if self.static_path is None:
            self.static_path = str(Path(FRONTEND_DIR / "public"))

    @property
    def redis_url(self) -> str:
        """Returns a redis url to connect to."""
        proto = "rediss" if self.redis_ssl else "redis"
        if not self.redis_password:
            return f"{proto}://{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"{proto}://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cache_enabled(self) -> bool:
        """Returns if redis is enabled."""
        return bool(self.redis_host)


@lru_cache(maxsize=1)
def get_app_settings() -> ListenerSettings:
    """Cache app settings."""
    return ListenerSettings()


settings = get_app_settings()
