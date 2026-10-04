# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_listener_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "status" in result.output


def test_listener_start_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--workers" in result.output


@patch("goe.cli.commands.listener.Granian")
def test_listener_start_dispatch(mock_granian):
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--port", "9000"])
    assert result.exit_code == 0
    assert mock_granian.called
    assert mock_granian.call_args[1]["port"] == 9000


@patch("goe.cli.commands.listener.httpx.get")
def test_listener_status_healthy(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = '{"status":true}'
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 0
    assert "healthy" in result.output.lower()


@patch("goe.cli.commands.listener.httpx.get", side_effect=OSError("connection refused"))
def test_listener_status_unreachable(mock_get):
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 0
    assert "not reachable" in result.output.lower()


@patch("goe.cli.commands.listener.Granian")
def test_listener_bare_invocation_starts_server(mock_granian):
    """Verify bare goe listener (and bin/listener) starts the server by default."""
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--port", "9090", "-v"])
    assert result.exit_code == 0
    assert mock_granian.called
    assert mock_granian.call_args[1]["port"] == 9090
