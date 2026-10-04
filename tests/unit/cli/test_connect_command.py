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
    options_override = mock_connect.call_args.args[0]
    assert options_override.upgrade_environment_file is False


@patch("goe.cli.commands.connect.check_config_path")
@patch("goe.cli.commands.connect.run_connect")
def test_connect_upgrade_environment_file_forwarded(mock_connect, mock_check):
    runner = CliRunner()
    result = runner.invoke(cli, ["connect", "--upgrade-environment-file"])
    assert result.exit_code == 0
    assert mock_check.called
    assert mock_connect.called
    options_override = mock_connect.call_args.args[0]
    assert options_override.upgrade_environment_file is True


@patch("goe.cli.commands.connect.check_config_path")
@patch("goe.cli.commands.connect.run_connect")
def test_connect_create_backend_db_and_common_options(mock_connect, mock_check):
    """Verify goe connect accepts hidden --create-backend-db and trailing common options."""
    runner = CliRunner()
    result = runner.invoke(cli, ["connect", "-v", "--create-backend-db", "--no-version-check"])
    assert result.exit_code == 0
    assert mock_check.called
    assert mock_connect.called
    options_override = mock_connect.call_args.args[0]
    assert options_override.verbose is True
    assert options_override.create_backend_db is True
    assert options_override.ver_check is False
    assert isinstance(options_override.log_path, str) and options_override.log_path
