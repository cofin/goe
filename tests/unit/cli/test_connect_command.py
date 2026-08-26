# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_connect_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["connect", "--help"])
    assert result.exit_code == 0
    assert "--upgrade-environment-file" in result.output


@patch("goe.cli.commands.connect.check_config_path")
@patch("goe.cli.commands.connect.run_connect")
def test_connect_dispatch(mock_connect, mock_check):
    runner = CliRunner()
    result = runner.invoke(cli, ["connect"])
    assert result.exit_code == 0
    assert mock_check.called
    assert mock_connect.called
