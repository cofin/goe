# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the goe listener CLI command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_listener_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "status" in result.output


def test_listener_start_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--workers" in result.output


@patch("goe.cli.commands.listener.subprocess.run")
@patch("goe.cli.commands.listener.verify_vertebra_runtime_gate", new_callable=AsyncMock)
def test_listener_start_dispatch(mock_gate: AsyncMock, mock_run) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--port", "9000"])
    assert result.exit_code == 0
    assert mock_gate.called
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert "--port" in cmd
    assert cmd[cmd.index("--port") + 1] == "9000"


@patch("goe.cli.commands.listener.httpx.get")
def test_listener_status_healthy(mock_get) -> None:
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = '{"status":true}'
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 0
    assert "healthy" in result.output.lower()


@patch("goe.cli.commands.listener.httpx.get", side_effect=OSError("connection refused"))
def test_listener_status_unreachable(mock_get) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 0
    assert "not reachable" in result.output.lower()


@patch("goe.cli.commands.listener.subprocess.run")
@patch("goe.cli.commands.listener.verify_vertebra_runtime_gate", new_callable=AsyncMock)
def test_listener_bare_invocation_starts_server(mock_gate: AsyncMock, mock_run) -> None:
    """Verify bare goe listener starts the server by default."""
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--port", "9090", "-v"])
    assert result.exit_code == 0
    assert mock_gate.called
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--port") + 1] == "9090"


@patch("goe.cli.commands.listener.subprocess.run")
@patch("goe.cli.commands.listener.verify_vertebra_runtime_gate", new_callable=AsyncMock)
def test_listener_group_options_forwarded_to_start(mock_gate: AsyncMock, mock_run) -> None:
    """Verify server options placed before start subcommand are forwarded to start."""
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--port", "9091", "start"])
    assert result.exit_code == 0
    assert mock_gate.called
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--port") + 1] == "9091"
