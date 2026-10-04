# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_sync_help() -> None:
    """Verify goe sync --help renders expected options."""
    runner = CliRunner()
    result = runner.invoke(cli, ["sync", "--help"])
    assert result.exit_code == 0
    assert "--include" in result.output
    assert "--execute" in result.output
    assert "--command-file" in result.output


@patch("goe.cli.commands.sync.log_close", create=True)
@patch("goe.cli.commands.sync.init_log", create=True)
@patch("goe.cli.commands.sync.init", create=True)
@patch("goe.cli.commands.sync.get_log_fh", create=True)
@patch("goe.cli.commands.sync.OffloadMessages.from_options")
@patch("goe.cli.commands.sync.run_schema_sync")
@patch("goe.cli.commands.sync.orchestration_repo_client_factory")
@patch("goe.cli.commands.sync.OrchestrationConfig.from_dict")
def test_sync_dispatch(
    mock_config,
    mock_factory,
    mock_run_sync,
    mock_from_options,
    mock_get_log_fh,
    mock_init,
    mock_init_log,
    mock_log_close,
) -> None:
    """Verify goe sync invokes 2-arg repo_client_factory and 4-arg run_schema_sync and closes resources."""
    mock_run_sync.return_value = 0
    runner = CliRunner()
    result = runner.invoke(cli, ["sync", "--include", "SH.*", "-x", "-v"])
    assert result.exit_code == 0
    assert mock_init.called
    mock_init_log.assert_called_once_with("schema_sync")
    assert len(mock_factory.call_args[0]) == 2
    assert mock_factory.call_args[0][0] is mock_config.return_value
    assert mock_factory.call_args[0][1] is mock_from_options.return_value
    assert mock_factory.call_args[1] == {
        "dry_run": False,
        "trace_action": "repo_client(schema_sync)",
    }
    assert len(mock_run_sync.call_args[0]) == 4
    options = mock_run_sync.call_args[0][0]
    assert options.include == "SH.*"
    assert options.execute is True
    assert options.verbose is True
    assert isinstance(options.log_path, str) and options.log_path
    assert mock_run_sync.call_args[0][1] is mock_from_options.return_value
    assert mock_run_sync.call_args[0][3] is mock_factory.return_value
    assert mock_factory.return_value.close.called
    assert mock_log_close.called


@patch("goe.cli.commands.sync.log_close", create=True)
@patch("goe.cli.commands.sync.init_log", create=True)
@patch("goe.cli.commands.sync.init", create=True)
@patch("goe.cli.commands.sync.get_log_fh", create=True)
@patch("goe.cli.commands.sync.OffloadMessages.from_options")
@patch("goe.cli.commands.sync.run_schema_sync", return_value=1)
@patch("goe.cli.commands.sync.orchestration_repo_client_factory")
@patch("goe.cli.commands.sync.OrchestrationConfig.from_dict")
def test_sync_nonzero_exit_code(
    mock_config,
    mock_factory,
    mock_run_sync,
    mock_from_options,
    mock_get_log_fh,
    mock_init,
    mock_init_log,
    mock_log_close,
) -> None:
    """Verify goe sync exits with return_code when run_schema_sync returns non-zero."""
    runner = CliRunner()
    result = runner.invoke(cli, ["sync", "--include", "SH.*"])
    assert result.exit_code == 1
    assert mock_factory.return_value.close.called
    assert mock_log_close.called


@patch("goe.cli.commands.sync.log_close", create=True)
@patch("goe.cli.commands.sync.init_log", create=True)
@patch("goe.cli.commands.sync.init", create=True)
@patch("goe.cli.commands.sync.OrchestrationConfig.from_dict", side_effect=RuntimeError("bad config"))
def test_sync_closes_log_when_config_fails(
    mock_config,
    mock_init,
    mock_init_log,
    mock_log_close,
) -> None:
    """Verify goe sync calls log_close even if OrchestrationConfig.from_dict raises before repo_client is created."""
    runner = CliRunner()
    result = runner.invoke(cli, ["sync", "--include", "SH.*"])
    assert result.exit_code != 0
    assert mock_log_close.called
