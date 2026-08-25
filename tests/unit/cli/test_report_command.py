# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
