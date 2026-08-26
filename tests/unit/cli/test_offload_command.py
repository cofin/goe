# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_offload_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["offload", "--help"])
    assert result.exit_code == 0
    assert "--table" in result.output
    assert "--execute" in result.output
    assert "--offload-type" in result.output
    assert "--older-than-date" in result.output
    assert "Target & Source Selection" in result.output


def test_offload_missing_required_table():
    runner = CliRunner()
    result = runner.invoke(cli, ["offload"])
    assert result.exit_code != 0
    assert "Missing option" in result.output or "required" in result.output.lower()


@patch("goe.cli.commands.offload.offload_by_cli")
def test_offload_dispatch(mock_offload):
    runner = CliRunner()
    result = runner.invoke(cli, ["offload", "-t", "SH.SALES", "-x"])
    assert result.exit_code == 0
    assert mock_offload.called
    options = mock_offload.call_args[0][0]
    assert options.owner_table == "SH.SALES"
    assert options.execute is True
