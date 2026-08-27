# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from click.testing import CliRunner

from goe.cli.main import cli


def test_report_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0
    assert "--schema" in result.output
    assert "--table" in result.output
    assert "--output-format" in result.output
    assert "--output-level" in result.output


@patch("goe.cli.commands.report.offload_status_report_run")
def test_report_dispatch(mock_osr):
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "-s", "SH", "-t", "SALES", "-o", "JSON"])
    assert result.exit_code == 0
    assert mock_osr.called
    options = mock_osr.call_args[0][0]
    assert options.schema == "SH"
    assert options.table == "SALES"
    assert options.output_format == "JSON"
