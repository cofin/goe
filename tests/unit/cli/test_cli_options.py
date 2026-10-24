# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OptionSpec-driven Click option builders and CLI decorators."""

from __future__ import annotations

from typing import Any

import rich_click as click
from click.testing import CliRunner

from goe.cli.common import common_options as cli_common_options
from goe.cli.common import handle_cli_exceptions
from goe.cli.options import (
    apply_option_specs,
    build_click_options,
    column_transform_options,
    common_options,
    partition_options,
    table_target_options,
    transport_options,
)
from goe.config.option_registry import get_option_specs_for_group
from goe.exceptions import ConfigurationError, ValidationError


def test_build_click_options_wires_Canonical_names_and_defaults() -> None:
    """build_click_options attaches OptionSpec flags and populates canonical kwargs."""
    captured: dict[str, Any] = {}

    @click.command()
    @common_options
    @table_target_options
    @partition_options
    @transport_options
    @column_transform_options
    def sample_cmd(**kwargs: Any) -> None:
        captured.update(kwargs)

    runner = CliRunner()
    result = runner.invoke(
        sample_cmd,
        [
            "-t",
            "SH.SALES",
            "-x",
            "--otel-enabled",
            "--otel-service-name",
            "goe-cli-test",
            "--otel-exporter-protocol",
            "otlp_http",
            "--otel-endpoint",
            "http://collector:4318",
            "--otel-sample-ratio",
            "0.25",
            "--offload-type",
            "FULL",
            "-d",
            "COL_A",
            "--decimal-columns-type",
            "10,2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["table"] == "SH.SALES"
    assert captured["execute"] is True
    assert captured["otel_enabled"] is True
    assert captured["otel_service_name"] == "goe-cli-test"
    assert captured["otel_exporter_protocol"] == "otlp_http"
    assert captured["otel_endpoint"] == "http://collector:4318"
    assert captured["otel_sample_ratio"] == "0.25"
    assert captured["offload_type"] == "FULL"
    assert captured["decimal_columns_csv_list"] == ("COL_A",)
    assert captured["decimal_columns_type_list"] == ("10,2",)


def test_apply_option_specs_filters_by_command_and_group() -> None:
    """apply_option_specs attaches only options matching command_name and optional groups."""
    captured: dict[str, Any] = {}

    @click.command()
    @apply_option_specs("validate", groups=("common", "verification"))
    def validate_cmd(**kwargs: Any) -> None:
        captured.update(kwargs)

    runner = CliRunner()
    result = runner.invoke(validate_cmd, ["--verify", "aggregate", "-v"])
    assert result.exit_code == 0, result.output
    assert captured["verify"] == "aggregate"
    assert captured["verbose"] is True
    assert "offload_transport_method" not in captured


def test_build_click_options_direct_sequence() -> None:
    """build_click_options can wrap an explicit sequence of OptionSpec objects."""
    specs = get_option_specs_for_group("verification")
    captured: dict[str, Any] = {}

    @click.command()
    @build_click_options(specs)
    def verify_cmd(**kwargs: Any) -> None:
        captured.update(kwargs)

    runner = CliRunner()
    result = runner.invoke(verify_cmd, ["--verify", "count"])
    assert result.exit_code == 0, result.output
    assert captured["verify"] == "count"


def test_cli_common_options_exposes_otel_flags_and_handles_goe_errors() -> None:
    """goe.cli.common supports OpenTelemetry flags and maps GOEError exit_code."""
    captured: dict[str, Any] = {}

    @click.command()
    @cli_common_options
    @handle_cli_exceptions
    def cmd_ok(**kwargs: Any) -> None:
        captured.update(kwargs)

    runner = CliRunner()
    res = runner.invoke(
        cmd_ok,
        [
            "--otel-enabled",
            "--otel-service-name",
            "svc",
            "--otel-exporter-protocol",
            "console",
            "--otel-endpoint",
            "http://localhost:4317",
            "--otel-sample-ratio",
            "0.5",
        ],
    )
    assert res.exit_code == 0, res.output
    assert captured["otel_enabled"] is True
    assert captured["otel_service_name"] == "svc"

    @click.command()
    @cli_common_options
    @handle_cli_exceptions
    def cmd_err(**_kwargs: Any) -> None:
        raise ConfigurationError("bad env setting")

    err_res = runner.invoke(cmd_err, [])
    assert err_res.exit_code == ConfigurationError.default_exit_code

    @click.command()
    @cli_common_options
    @handle_cli_exceptions
    def cmd_val_err(**_kwargs: Any) -> None:
        raise ValidationError("bad option")

    val_res = runner.invoke(cmd_val_err, [])
    assert val_res.exit_code == ValidationError.default_exit_code
