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
