# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_sync_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["sync", "--help"])
    assert result.exit_code == 0
    assert "--include" in result.output
    assert "--execute" in result.output
    assert "--command-file" in result.output


@patch("goe.cli.commands.sync.run_schema_sync")
@patch("goe.cli.commands.sync.orchestration_repo_client_factory")
@patch("goe.cli.commands.sync.OrchestrationConfig.from_dict")
def test_sync_dispatch(mock_config, mock_factory, mock_run_sync):
    runner = CliRunner()
    result = runner.invoke(cli, ["sync", "--include", "SH.*", "-x"])
    assert result.exit_code == 0
    assert mock_run_sync.called
    options = mock_run_sync.call_args[0][0]
    assert options.include == "SH.*"
    assert options.execute is True
