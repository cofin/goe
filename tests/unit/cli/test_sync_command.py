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
