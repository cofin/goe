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


def test_listener_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "status" in result.output


def test_listener_start_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--workers" in result.output


@patch("goe.cli.commands.listener.uvicorn.run")
def test_listener_start_dispatch(mock_uvicorn):
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--port", "9000"])
    assert result.exit_code == 0
    assert mock_uvicorn.called
    assert mock_uvicorn.call_args[1]["port"] == 9000
