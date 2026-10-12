# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for OpenTelemetry CLI and options wiring."""

from typing import Any

import pytest
import rich_click as click
from click.testing import CliRunner

from goe.cli.common import common_options, extract_common_options
from goe.config.options import CommonOptions
from goe.observability.config import ObservabilitySettings

_CAPTURED: dict[str, Any] = {}


def test_flags_absent_leave_output_unchanged() -> None:
    resolved = _run([])
    assert "otel_enabled" not in resolved
    assert "log_format" not in resolved


def test_flags_present_are_returned() -> None:
    resolved = _run(["--otel-enabled", "--otel-exporter", "memory", "--log-format", "json"])
    assert resolved["otel_enabled"] is True
    assert resolved["otel_exporter"] == "memory"
    assert resolved["log_format"] == "json"


def test_common_options_fields_drive_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOE_OTEL_ENABLED", raising=False)
    options = CommonOptions.from_mapping({"otel_enabled": True, "otel_exporter": "memory", "log_format": "json"})
    settings = ObservabilitySettings.from_env_and_config(options)
    assert settings.enabled is True
    assert settings.exporter == "memory"
    assert settings.log_format == "json"
    assert ObservabilitySettings.from_env_and_config(CommonOptions.from_mapping({})).enabled is False


def _run(args: list[str]) -> dict[str, Any]:
    """Invoke the probe command decorated with common_options and return the extracted options."""
    _CAPTURED.clear()
    result = CliRunner().invoke(_probe, args)
    assert result.exit_code == 0, result.output
    return dict(_CAPTURED)


@click.command()
@common_options
@click.pass_context
def _probe(ctx: click.Context, **kwargs: Any) -> None:
    """Extract and record common options for test assertions."""
    _CAPTURED.update(extract_common_options(ctx, kwargs))
