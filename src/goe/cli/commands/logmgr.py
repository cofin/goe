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

"""'goe logmgr' subcommand for log archiving, compression, and retention management."""

import datetime
import os
import shutil
from pathlib import Path

import rich_click as click

from goe.cli.console import print_info, print_success


@click.command(
    name="logmgr",
    help="Archive old execution log files and enforce retention policies.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--log-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory containing active logs (defaults to $OFFLOAD_HOME/log).",
)
@click.option(
    "--min-age-minutes",
    type=int,
    default=60,
    show_default=True,
    help="Minimum age (in minutes) of log files before being moved to archive.",
)
@click.option(
    "--archive-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Target archive directory (defaults to <log-dir>/archive/YYYY.MM.DD).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="List log files eligible for archiving or purging without modifying the filesystem.",
)
@click.option(
    "--purge-days",
    type=int,
    help="Purge archived logs older than N days.",
)
def logmgr(
    log_dir: Path | None = None,
    min_age_minutes: int = 60,
    archive_dir: Path | None = None,
    dry_run: bool = False,
    purge_days: int | None = None,
) -> None:
    """Archive old logs into dated folders and prune expired logs."""
    if log_dir is None:
        offload_home = os.environ.get("OFFLOAD_HOME")
        if offload_home:
            log_dir = Path(offload_home) / "log"
        else:
            log_dir = Path.cwd() / "log"

    if not log_dir.exists():
        print_info(f"Log directory '{log_dir}' does not exist. Nothing to archive.")
        return

    now = datetime.datetime.now()
    if archive_dir is None:
        archive_dir = log_dir / "archive" / now.strftime("%Y.%m.%d")

    moved_count = 0
    cutoff_time = now.timestamp() - (min_age_minutes * 60)

    for item in log_dir.iterdir():
        if item.is_file() and item.stat().st_mtime <= cutoff_time:
            if not dry_run:
                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(archive_dir / item.name))
            moved_count += 1

    if dry_run:
        print_info(f"[dry-run] Found {moved_count} log file(s) eligible for archive in {archive_dir}")
    else:
        print_success(f"Archived {moved_count} log file(s) to {archive_dir}")

    if purge_days is not None and purge_days > 0:
        purged_count = 0
        purge_cutoff = now.timestamp() - (purge_days * 86400)
        archive_root = log_dir / "archive"
        if archive_root.exists():
            for root, _dirs, files in os.walk(archive_root):
                for f in files:
                    file_path = Path(root) / f
                    if file_path.stat().st_mtime <= purge_cutoff:
                        if not dry_run:
                            file_path.unlink()
                        purged_count += 1
        if dry_run:
            print_info(f"[dry-run] Found {purged_count} archived file(s) older than {purge_days} day(s)")
        else:
            print_success(f"Purged {purged_count} archived file(s) older than {purge_days} day(s)")
