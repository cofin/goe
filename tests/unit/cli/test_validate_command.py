# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_validate_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--help"])
    assert result.exit_code == 0
    assert "--table" in result.output
    assert "--selects" in result.output
    assert "--filters" in result.output
    assert "--aggregate-functions" in result.output


def test_validate_missing_table():
    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code != 0
    assert "Missing option" in result.output or "required" in result.output.lower()


@patch("goe.cli.commands.validate.run_agg_validate")
def test_validate_dispatch(mock_validate):
    mock_validate.return_value = True
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "-t", "SH.SALES", "-S", "AMOUNT_SOLD"])
    assert result.exit_code == 0
    assert mock_validate.called
    options = mock_validate.call_args[0][0]
    assert options.owner_table == "SH.SALES"
    assert options.selects == "AMOUNT_SOLD"
