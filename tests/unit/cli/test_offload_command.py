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
