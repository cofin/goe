# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for goe.observability.config.ObservabilitySettings."""

from types import SimpleNamespace

import pytest

from goe.observability.config import ObservabilitySettings


def test_defaults_are_disabled() -> None:
    settings = ObservabilitySettings.from_env_and_config()
    assert settings.enabled is False
    assert settings.exporter == "none"
    assert settings.log_format == "text"
    assert settings.log_json_sidecar is False
    assert settings.sample_rate == 1.0


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOE_OTEL_ENABLED", "true")
    monkeypatch.setenv("GOE_OTEL_EXPORTER", "OTLP")
    monkeypatch.setenv("GOE_OTEL_PROTOCOL", "http/protobuf")
    monkeypatch.setenv("GOE_OTEL_SAMPLE_RATE", "0.25")
    monkeypatch.setenv("GOE_LOG_FORMAT", "json")
    settings = ObservabilitySettings.from_env_and_config()
    assert settings.enabled is True
    assert settings.exporter == "otlp"
    assert settings.protocol == "http/protobuf"
    assert settings.sample_rate == 0.25
    assert settings.log_format == "json"


def test_config_attributes_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOE_OTEL_ENABLED", "false")
    monkeypatch.setenv("GOE_OTEL_EXPORTER", "console")
    config = SimpleNamespace(otel_enabled=True, otel_exporter="memory", otel_endpoint=None)
    settings = ObservabilitySettings.from_env_and_config(config)
    assert settings.enabled is True
    assert settings.exporter == "memory"
    assert settings.endpoint is None


def test_invalid_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOE_OTEL_EXPORTER", "zipkin")
    monkeypatch.setenv("GOE_OTEL_SAMPLE_RATE", "not-a-number")
    monkeypatch.setenv("GOE_LOG_FORMAT", "xml")
    settings = ObservabilitySettings.from_env_and_config()
    assert settings.exporter == "none"
    assert settings.sample_rate == 1.0
    assert settings.log_format == "text"


def test_sample_rate_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOE_OTEL_SAMPLE_RATE", "7")
    assert ObservabilitySettings.from_env_and_config().sample_rate == 1.0
    monkeypatch.setenv("GOE_OTEL_SAMPLE_RATE", "-1")
    assert ObservabilitySettings.from_env_and_config().sample_rate == 0.0


def test_tracing_active_requires_enabled_and_exporter() -> None:
    assert ObservabilitySettings(enabled=True, exporter="none").tracing_active is False
    assert ObservabilitySettings(enabled=False, exporter="memory").tracing_active is False
    assert ObservabilitySettings(enabled=True, exporter="memory").tracing_active is True


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all GOE_OTEL_* and GOE_LOG_* variables so each test starts from defaults."""
    for name in (
        "GOE_OTEL_ENABLED",
        "GOE_OTEL_SERVICE_NAME",
        "GOE_OTEL_EXPORTER",
        "GOE_OTEL_ENDPOINT",
        "GOE_OTEL_PROTOCOL",
        "GOE_OTEL_SAMPLE_RATE",
        "GOE_OTEL_LOG_CORRELATION",
        "GOE_OTEL_SQLCOMMENTER",
        "GOE_OTEL_JSONL_PATH",
        "GOE_OTEL_ENVIRONMENT",
        "GOE_LOG_FORMAT",
        "GOE_LOG_JSON_SIDECAR",
    ):
        monkeypatch.delenv(name, raising=False)
