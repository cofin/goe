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

import os
import time

from click.testing import CliRunner

from goe.cli.main import cli


def test_logmgr_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["logmgr", "--help"])
    assert result.exit_code == 0
    assert "--log-dir" in result.output
    assert "--min-age-minutes" in result.output
    assert "--dry-run" in result.output
    assert "--purge-days" in result.output


def test_logmgr_archive_execution(tmp_path):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    old_log = log_dir / "old_run.log"
    old_log.write_text("old log content")

    # Set mtime back 2 hours (120 mins)
    past_time = time.time() - 7200
    os.utime(str(old_log), (past_time, past_time))

    runner = CliRunner()
    result = runner.invoke(cli, ["logmgr", "--log-dir", str(log_dir), "--min-age-minutes", "60"])
    assert result.exit_code == 0
    assert not old_log.exists()
    archive_dir = log_dir / "archive"
    assert archive_dir.exists()
