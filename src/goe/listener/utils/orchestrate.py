# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Orchestration lock and log-reading utilities for the GOE Listener."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from goe.listener import exceptions
from goe.listener.config import settings
from goe.platform.locking import (
    OrchestrationLockTimeout,
    orchestration_lock_for_table,
)

__all__ = (
    "check_for_running_command",
    "read_execution_log_bounded",
    "resolve_allowed_log_dir",
)

CLOUD_LOG_SCHEMES = ("gs://", "s3://", "abfss://", "wasbs://", "hdfs://")


def check_for_running_command(owner_table: str) -> bool:
    """Validate that no other local process holds an orchestration lock on owner_table."""
    parts = owner_table.split(".", 1) if owner_table and "." in owner_table else ["", ""]
    owner_name, table_name = parts[0].strip(), parts[1].strip()
    if owner_name and table_name:
        try:
            table_lock = orchestration_lock_for_table(owner_name, table_name)
            table_lock.acquire()
            table_lock.release()
        except OrchestrationLockTimeout as exc:
            raise exceptions.ApplicationError(
                status_code=409,
                message=f"Another job has locked the table {owner_name}.{table_name}.",
            ) from exc
        return False

    raise exceptions.ApplicationError(
        status_code=400,
        message="Could not determine owner and table from supplied input.",
    )


def resolve_allowed_log_dir(config: Any = None) -> Path:
    """Return the canonical resolved OFFLOAD_LOGDIR directory."""
    raw_dir = os.environ.get("OFFLOAD_LOGDIR")
    if not raw_dir and config is not None:
        raw_dir = getattr(config, "log_path", None) or getattr(config, "offload_logdir", None)
    if not raw_dir:
        offload_home = Path(os.environ.get("OFFLOAD_HOME", "/tmp/goe"))
        raw_dir = str(offload_home / "log")
    return Path(raw_dir).resolve()


def read_execution_log_bounded(
    raw_log_path: str,
    *,
    execution_id: str,
    max_bytes: int | None = None,
    allowed_log_dir: Path | None = None,
    dfs_client: Any = None,
) -> tuple[str, bool, str]:
    """Read up to max_bytes of a local or cloud execution log with path-containment enforcement."""
    limit = max(1, int(max_bytes if max_bytes is not None else settings.max_log_bytes))
    cleaned = raw_log_path.strip()
    if not cleaned:
        return "", False, f"Log file for execution {execution_id} not found."

    if cleaned.startswith(CLOUD_LOG_SCHEMES):
        return _read_cloud_log(cleaned, execution_id=execution_id, limit=limit, dfs_client=dfs_client)

    log_dir = (allowed_log_dir or resolve_allowed_log_dir()).resolve()
    candidate = Path(cleaned).resolve()
    if not candidate.is_relative_to(log_dir):
        raise exceptions.ApplicationError(
            status_code=403,
            message="Execution log path is outside OFFLOAD_LOGDIR.",
        )

    file_name = candidate.stem
    if not candidate.is_file():
        return file_name, False, f"Log file for execution {execution_id} not found."

    with candidate.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        start_pos = max(0, size - limit)
        fh.seek(start_pos, os.SEEK_SET)
        data = fh.read(limit)
    return file_name, True, data.decode("utf-8", errors="replace")


def _read_cloud_log(
    uri: str,
    *,
    execution_id: str,
    limit: int,
    dfs_client: Any = None,
) -> tuple[str, bool, str]:
    """Read a bounded log payload from a cloud URI via GOEDfs."""
    file_name = Path(uri.rstrip("/")).stem
    client = dfs_client
    if client is None:
        return file_name, False, f"Log file for execution {execution_id} not found."
    try:
        raw = client.read(uri)
    except FileNotFoundError:
        return file_name, False, f"Log file for execution {execution_id} not found."
    if raw is None:
        return file_name, False, f"Log file for execution {execution_id} not found."
    raw_bytes = raw.encode("utf-8", errors="replace") if isinstance(raw, str) else bytes(raw)
    if len(raw_bytes) > limit:
        raw_bytes = raw_bytes[-limit:]
    return file_name, True, raw_bytes.decode("utf-8", errors="replace")
