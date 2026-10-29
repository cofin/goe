# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe connect CLI subcommand and Listener connectivity service."""

from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from goe.cli.commands.connect import connect_cmd
from goe.cli.main import cli
from goe.config.settings import GOESettings
from goe.connect.models import CheckDetail, CheckResult, ConnectivityReport
from goe.listener.services.system import SystemService
from goe.serializers import decode_json


def test_connect_help() -> None:
    """Verify goe connect --help lists the --json flag."""
    runner = CliRunner()
    result = runner.invoke(cli, ["connect", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_cli_connect_text_output_and_exit_code_0() -> None:
    """goe connect prints formatted text report and exits with code 0 when all checks pass."""
    fake_report = _sample_report(failed=False)
    fake_settings = GOESettings.from_env(environ={})
    runner = CliRunner()
    with (
        mock.patch("goe.cli.commands.connect.GOESettings.from_env", return_value=fake_settings),
        mock.patch("goe.cli.commands.connect.ConnectRunner") as mock_runner_cls,
    ):
        mock_runner_cls.return_value.run.return_value = fake_report
        res = runner.invoke(connect_cmd, ["-v"])
    assert res.exit_code == 0, res.output
    assert "=== FRONTEND ===" in res.output
    assert "dsn: ora:1521/ORCL" in res.output
    assert "Connectivity check succeeded" in res.output


def test_cli_connect_json_flag_emits_valid_connectivity_report() -> None:
    """goe connect --json emits a JSON payload that decodes into ConnectivityReport."""
    fake_report = _sample_report(failed=False)
    fake_settings = GOESettings.from_env(environ={})
    runner = CliRunner()
    with (
        mock.patch("goe.cli.commands.connect.GOESettings.from_env", return_value=fake_settings),
        mock.patch("goe.cli.commands.connect.ConnectRunner") as mock_runner_cls,
    ):
        mock_runner_cls.return_value.run.return_value = fake_report
        res = runner.invoke(connect_cmd, ["--json"])
    assert res.exit_code == 0, res.output
    decoded = decode_json(res.output, target_type=ConnectivityReport)
    assert decoded == fake_report


def test_cli_connect_exits_1_when_any_probe_fails() -> None:
    """goe connect exits with code 1 when ConnectivityReport.passed is False."""
    fake_report = _sample_report(failed=True)
    fake_settings = GOESettings.from_env(environ={})
    runner = CliRunner()
    with (
        mock.patch("goe.cli.commands.connect.GOESettings.from_env", return_value=fake_settings),
        mock.patch("goe.cli.commands.connect.ConnectRunner") as mock_runner_cls,
    ):
        mock_runner_cls.return_value.run.return_value = fake_report
        res = runner.invoke(connect_cmd, [])
    assert res.exit_code == 1
    assert "Connectivity check failed" in res.output


def test_listener_system_connectivity_endpoint_returns_report() -> None:
    """SystemService.check_connectivity delegates to ConnectRunner and returns ConnectivityReport."""
    service = SystemService(config=None)
    report = service.check_connectivity(
        environ={
            "ORA_CONN": "ora-host:1521/ORCL",
            "ORA_ADM_USER": "GOE_ADM",
            "ORA_APP_USER": "GOE_APP",
            "QUERY_ENGINE": "BIGQUERY",
            "GOOGLE_CLOUD_PROJECT": "my-gcp-project",
            "OFFLOAD_FS_SCHEME": "gs",
            "OFFLOAD_FS_CONTAINER": "my-staging-bucket",
        }
    )
    assert isinstance(report, ConnectivityReport)
    assert report.passed is True


def _sample_report(*, failed: bool = False) -> ConnectivityReport:
    return ConnectivityReport(
        environment_summary="Host: dev-host | OS: Ubuntu 24.04 | Python: 3.12.7",
        results=(
            CheckResult(
                name="ORACLE frontend connection",
                category="frontend",
                status="passed",
                duration_ms=2.0,
                details=(CheckDetail(label="dsn", value="ora:1521/ORCL"),),
            ),
            CheckResult(
                name="BIGQUERY backend catalog",
                category="backend",
                status="failed" if failed else "passed",
                duration_ms=3.5,
                message="Dataset unreachable" if failed else None,
            ),
        ),
        total_duration_ms=5.5,
    )
