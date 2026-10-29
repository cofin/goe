# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Listener Configuration Settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Literal

import msgspec

from goe.config.config_file import load_env
from goe.config.orchestration_config import OrchestrationConfig
from goe.typing import FrozenBaseStruct

__all__ = (
    "APP_DIR",
    "BASE_DIR",
    "CONFIG_DIR",
    "ListenerSettings",
    "get_listener_settings",
    "settings",
)

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
APP_DIR: Path = Path(BASE_DIR / "listener")
CONFIG_DIR: Path = Path(APP_DIR / "config")


class ListenerSettings(FrozenBaseStruct, frozen=True):
    """Immutable Listener runtime, HTTP, and MCP configuration settings."""

    global_config: OrchestrationConfig | None = msgspec.field(default_factory=lambda: _get_default_global_config())

    host: str = "0.0.0.0"
    port: int = 8000
    http_workers: int = 2
    reload: bool = False
    shared_token: str | None = None
    certfile: str | None = None
    keyfile: str | None = None
    ssl_enabled: bool = False
    heartbeat_interval: int = 30
    max_log_bytes: int = 1_048_576
    topology: Literal["shm", "embedded"] = "shm"
    threads: int = 1
    drain_timeout_seconds: int = 30
    shutdown_timeout_seconds: int = 35
    confirmation_ttl_seconds: int = 300
    mcp_skills_enabled: bool = True
    mcp_task_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.global_config:
            if self.global_config.listener_host:
                msgspec.structs.force_setattr(self, "host", str(self.global_config.listener_host).strip())
            if self.global_config.listener_port is not None:
                msgspec.structs.force_setattr(self, "port", int(self.global_config.listener_port))
            if self.global_config.listener_shared_token:
                msgspec.structs.force_setattr(self, "shared_token", str(self.global_config.listener_shared_token))
            if self.global_config.listener_heartbeat_interval:
                msgspec.structs.force_setattr(
                    self,
                    "heartbeat_interval",
                    int(self.global_config.listener_heartbeat_interval),
                )

        if self.global_config is None:
            env_host = (os.environ.get("OFFLOAD_LISTENER_HOST") or "").strip()
            if env_host:
                msgspec.structs.force_setattr(self, "host", env_host)
            msgspec.structs.force_setattr(
                self,
                "port",
                _parse_int_env("OFFLOAD_LISTENER_PORT", self.port, minimum=1),
            )
            msgspec.structs.force_setattr(
                self,
                "heartbeat_interval",
                _parse_int_env("OFFLOAD_LISTENER_HEARTBEAT_INTERVAL", self.heartbeat_interval, minimum=1),
            )
            env_token = (os.environ.get("OFFLOAD_LISTENER_SHARED_TOKEN") or "").strip()
            if env_token and self.shared_token is None:
                msgspec.structs.force_setattr(self, "shared_token", env_token)

        msgspec.structs.force_setattr(
            self,
            "http_workers",
            _parse_int_env("OFFLOAD_LISTENER_HTTP_WORKERS", self.http_workers, minimum=1),
        )
        msgspec.structs.force_setattr(
            self,
            "max_log_bytes",
            _parse_int_env("OFFLOAD_LISTENER_MAX_LOG_BYTES", self.max_log_bytes, minimum=1024),
        )

        env_topology = (os.environ.get("OFFLOAD_LISTENER_TOPOLOGY") or "").strip().lower()
        if env_topology in ("shm", "embedded"):
            msgspec.structs.force_setattr(self, "topology", env_topology)

        threads_val = _parse_int_env(
            "OFFLOAD_LISTENER_THREADS",
            _parse_int_env("VERTEBRA_THREADS", self.threads, minimum=1),
            minimum=1,
        )
        msgspec.structs.force_setattr(self, "threads", threads_val)

        raw_drain = (os.environ.get("OFFLOAD_LISTENER_DRAIN_TIMEOUT") or "").strip()
        raw_vtb_drain = (os.environ.get("VERTEBRA_DRAIN_TIMEOUT") or "").strip()
        if raw_drain.isdigit() or raw_vtb_drain.isdigit():
            drain_val = _parse_int_env(
                "OFFLOAD_LISTENER_DRAIN_TIMEOUT",
                _parse_int_env("VERTEBRA_DRAIN_TIMEOUT", self.drain_timeout_seconds, minimum=1),
                minimum=1,
            )
            msgspec.structs.force_setattr(self, "drain_timeout_seconds", drain_val)
            msgspec.structs.force_setattr(
                self,
                "shutdown_timeout_seconds",
                _parse_int_env("VERTEBRA_SHUTDOWN_TIMEOUT", drain_val + 5, minimum=1),
            )
        else:
            msgspec.structs.force_setattr(
                self,
                "shutdown_timeout_seconds",
                _parse_int_env("VERTEBRA_SHUTDOWN_TIMEOUT", self.shutdown_timeout_seconds, minimum=1),
            )

        msgspec.structs.force_setattr(
            self,
            "confirmation_ttl_seconds",
            _parse_int_env("OFFLOAD_LISTENER_CONFIRMATION_TTL_SECONDS", self.confirmation_ttl_seconds, minimum=30),
        )
        msgspec.structs.force_setattr(
            self,
            "mcp_skills_enabled",
            _parse_bool_env("OFFLOAD_LISTENER_MCP_SKILLS_ENABLED", self.mcp_skills_enabled),
        )
        msgspec.structs.force_setattr(
            self,
            "mcp_task_ttl_seconds",
            _parse_int_env("OFFLOAD_LISTENER_MCP_TASK_TTL_SECONDS", self.mcp_task_ttl_seconds, minimum=60),
        )

    @property
    def client_host(self) -> str:
        """Return a client-connectable host derived from the configured bind address."""
        normalized = (self.host or "").strip()
        if normalized in ("", "0.0.0.0", "::", "[::]"):
            return "127.0.0.1"
        if ":" in normalized and not normalized.startswith("["):
            return f"[{normalized}]"
        return normalized

    @property
    def base_url(self) -> str:
        """Return the base HTTP(S) URL for local probes and MCP Streamable HTTP bridging."""
        scheme = "https" if self.ssl_enabled else "http"
        return f"{scheme}://{self.client_host}:{self.port}"

    def to_vertebra_env(self, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
        """Export Vertebra runtime environment variables while preserving caller-provided VERTEBRA_* keys."""
        source = dict(os.environ) if base_env is None else dict(base_env)
        defaults = {
            "VERTEBRA_HOST": str(self.host),
            "VERTEBRA_PORT": str(self.port),
            "VERTEBRA_TOPOLOGY": str(self.topology),
            "VERTEBRA_WORKERS": str(self.http_workers),
            "VERTEBRA_THREADS": str(self.threads),
            "VERTEBRA_DRAIN_TIMEOUT": str(self.drain_timeout_seconds),
            "VERTEBRA_SHUTDOWN_TIMEOUT": str(self.shutdown_timeout_seconds),
        }
        for key, val in defaults.items():
            source.setdefault(key, val)
        return source


@lru_cache
def get_listener_settings() -> ListenerSettings:
    """Get cached ListenerSettings."""
    return ListenerSettings()


def _parse_int_env(name: str, default: int, *, minimum: int | None = None) -> int:
    """Parse an integer environment variable, falling back to default when unset, blank, or invalid."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    if minimum is not None:
        return max(minimum, parsed)
    return parsed


def _parse_bool_env(name: str, default: bool) -> bool:
    """Parse a boolean environment variable, falling back to default when unset or blank."""
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    return default


def _get_default_global_config() -> OrchestrationConfig | None:
    try:
        load_env()
        return OrchestrationConfig.as_defaults(do_not_connect=True)
    except Exception:
        return None


settings: ListenerSettings = get_listener_settings()
