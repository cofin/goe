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
