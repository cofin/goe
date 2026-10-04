# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

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
    """Verify goe logmgr archives log files older than --min-age-minutes (e.g. 2 hours old with 60 min threshold)."""
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    old_log = log_dir / "old_run.log"
    old_log.write_text("old log content")

    past_time = time.time() - 7200
    os.utime(str(old_log), (past_time, past_time))

    runner = CliRunner()
    result = runner.invoke(cli, ["logmgr", "--log-dir", str(log_dir), "--min-age-minutes", "60"])
    assert result.exit_code == 0
    assert not old_log.exists()
    archive_dir = log_dir / "archive"
    assert archive_dir.exists()


def test_logmgr_honors_log_mv_mins_env_and_common_options(tmp_path, monkeypatch):
    """Verify goe logmgr falls back to LOG_MV_MINS when --min-age-minutes is omitted and accepts common options."""
    monkeypatch.setenv("LOG_MV_MINS", "15")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    old_log = log_dir / "aged_20m.log"
    old_log.write_text("log aged 20 minutes")

    past_time = time.time() - (20 * 60)
    os.utime(str(old_log), (past_time, past_time))

    runner = CliRunner()
    result = runner.invoke(cli, ["logmgr", "--log-dir", str(log_dir), "-v"])
    assert result.exit_code == 0
    assert not old_log.exists()
    archive_dir = log_dir / "archive"
    assert archive_dir.exists()
