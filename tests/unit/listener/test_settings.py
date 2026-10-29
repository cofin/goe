# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ListenerSettings, blank numeric environment parsing, and URL normalization."""

from __future__ import annotations

import pytest

import goe.listener.config.application as app_config_module
from goe.config.orchestration_defaults import (
    listener_heartbeat_interval_default,
    listener_host_default,
    listener_port_default,
)
from goe.listener.config.application import ListenerSettings


@pytest.mark.parametrize("raw_val", ["", "   "])
def test_orchestration_defaults_blank_and_whitespace_env_vars(
    monkeypatch: pytest.MonkeyPatch,
    raw_val: str,
) -> None:
    """Verify listener_*_default helpers in orchestration_defaults.py strip whitespace and fall back to defaults."""
    monkeypatch.setenv("OFFLOAD_LISTENER_HOST", raw_val)
    monkeypatch.setenv("OFFLOAD_LISTENER_PORT", raw_val)
    monkeypatch.setenv("OFFLOAD_LISTENER_HEARTBEAT_INTERVAL", raw_val)

    assert listener_host_default() is None
    assert listener_port_default() == 8000
    assert listener_heartbeat_interval_default() == 60


@pytest.mark.parametrize("raw_val", ["", "   "])
def test_listener_settings_blank_and_whitespace_numeric_env_vars(
    monkeypatch: pytest.MonkeyPatch,
    raw_val: str,
) -> None:
    """Verify ListenerSettings falls back to defaults when numeric environment variables are empty or whitespace."""
    for env_key in (
        "OFFLOAD_LISTENER_PORT",
        "OFFLOAD_LISTENER_HEARTBEAT_INTERVAL",
        "OFFLOAD_LISTENER_HTTP_WORKERS",
        "OFFLOAD_LISTENER_MAX_LOG_BYTES",
        "OFFLOAD_LISTENER_THREADS",
        "OFFLOAD_LISTENER_DRAIN_TIMEOUT",
        "OFFLOAD_LISTENER_CONFIRMATION_TTL_SECONDS",
        "OFFLOAD_LISTENER_MCP_TASK_TTL_SECONDS",
    ):
        monkeypatch.setenv(env_key, raw_val)

    cfg = ListenerSettings(global_config=None)
    assert cfg.port == 8000
    assert cfg.heartbeat_interval == 30
    assert cfg.http_workers == 2
    assert cfg.max_log_bytes == 1_048_576
    assert cfg.threads == 1
    assert cfg.drain_timeout_seconds == 30
    assert cfg.shutdown_timeout_seconds == 35
    assert cfg.confirmation_ttl_seconds == 300
    assert cfg.mcp_task_ttl_seconds == 3600


def test_listener_settings_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ListenerSettings applies valid environment overrides for MCP, worker, and timeout fields."""
    monkeypatch.setenv("OFFLOAD_LISTENER_HTTP_WORKERS", "4")
    monkeypatch.setenv("OFFLOAD_LISTENER_MAX_LOG_BYTES", "2097152")
    monkeypatch.setenv("OFFLOAD_LISTENER_THREADS", "3")
    monkeypatch.setenv("OFFLOAD_LISTENER_DRAIN_TIMEOUT", "45")
    monkeypatch.setenv("OFFLOAD_LISTENER_CONFIRMATION_TTL_SECONDS", "600")
    monkeypatch.setenv("OFFLOAD_LISTENER_MCP_SKILLS_ENABLED", "false")
    monkeypatch.setenv("OFFLOAD_LISTENER_MCP_TASK_TTL_SECONDS", "7200")

    cfg = ListenerSettings(global_config=None)
    assert cfg.http_workers == 4
    assert cfg.max_log_bytes == 2_097_152
    assert cfg.threads == 3
    assert cfg.drain_timeout_seconds == 45
    assert cfg.shutdown_timeout_seconds == 50
    assert cfg.confirmation_ttl_seconds == 600
    assert cfg.mcp_skills_enabled is False
    assert cfg.mcp_task_ttl_seconds == 7200


@pytest.mark.parametrize(
    ("host", "ssl_enabled", "expected_client_host", "expected_base_url"),
    [
        ("", False, "127.0.0.1", "http://127.0.0.1:8000"),
        ("0.0.0.0", False, "127.0.0.1", "http://127.0.0.1:8000"),
        ("::", False, "127.0.0.1", "http://127.0.0.1:8000"),
        ("::1", False, "[::1]", "http://[::1]:8000"),
        ("127.0.0.1", False, "127.0.0.1", "http://127.0.0.1:8000"),
        ("goe-listener.internal", True, "goe-listener.internal", "https://goe-listener.internal:8000"),
    ],
)
def test_listener_settings_client_host_and_base_url_normalization(
    host: str,
    ssl_enabled: bool,
    expected_client_host: str,
    expected_base_url: str,
) -> None:
    """Verify client_host and base_url normalize wildcard bind addresses and respect ssl_enabled."""
    cfg = ListenerSettings(global_config=None, host=host, port=8000, ssl_enabled=ssl_enabled)
    assert cfg.client_host == expected_client_host
    assert cfg.base_url == expected_base_url


def test_listener_settings_removes_unused_scaffold_symbols() -> None:
    """Verify FRONTEND_DIR, static_url, static_path, and background_workers are removed from ListenerSettings."""
    cfg = ListenerSettings(global_config=None)
    assert not hasattr(app_config_module, "FRONTEND_DIR")
    assert "FRONTEND_DIR" not in app_config_module.__all__
    assert not hasattr(cfg, "static_url")
    assert not hasattr(cfg, "static_path")
    assert not hasattr(cfg, "background_workers")
    assert cfg.confirmation_ttl_seconds == 300
    assert cfg.mcp_skills_enabled is True
    assert cfg.mcp_task_ttl_seconds == 3600
