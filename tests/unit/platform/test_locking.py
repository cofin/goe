# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for FileOrchestrationLock and table lock factory helpers."""

from pathlib import Path

import pytest

from goe.persistence.models import OffloadMetadata
from goe.platform.locking import (
    FileOrchestrationLock,
    OrchestrationLockTimeout,
    orchestration_lock_for_table,
    orchestration_lock_from_hybrid_metadata,
)


def test_file_orchestration_lock_acquires_and_blocks_concurrent_holder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """orchestration_lock_for_table acquires $OFFLOAD_HOME/run lock and blocks concurrent holders."""
    monkeypatch.setenv("OFFLOAD_HOME", str(tmp_path))
    (tmp_path / "run").mkdir(parents=True, exist_ok=True)

    first_lock = orchestration_lock_for_table("SH", "SALES")
    first_lock.acquire()
    try:
        second_lock = orchestration_lock_for_table("SH", "SALES")
        with pytest.raises(
            OrchestrationLockTimeout,
            match=r"Another Orchestration process has locked id: SH\.SALES",
        ):
            second_lock.acquire()
    finally:
        first_lock.release()

    with orchestration_lock_for_table("SH", "SALES"):
        pass


def test_file_orchestration_lock_from_hybrid_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """orchestration_lock_from_hybrid_metadata locks by offloaded_owner and offloaded_table."""
    monkeypatch.setenv("OFFLOAD_HOME", str(tmp_path))
    (tmp_path / "run").mkdir(parents=True, exist_ok=True)

    metadata = OffloadMetadata.from_attributes(
        offloaded_owner="SH",
        offloaded_table="COSTS",
    )
    lock = orchestration_lock_from_hybrid_metadata(metadata)
    with lock:
        contending = orchestration_lock_for_table("SH", "COSTS")
        with pytest.raises(OrchestrationLockTimeout):
            contending.acquire()


def test_file_orchestration_lock_dry_run_does_not_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run FileOrchestrationLock does not acquire an exclusive filesystem lock."""
    monkeypatch.setenv("OFFLOAD_HOME", str(tmp_path))
    (tmp_path / "run").mkdir(parents=True, exist_ok=True)

    dry_lock = FileOrchestrationLock(["SH", "SALES"], dry_run=True)
    with dry_lock:
        second_lock = orchestration_lock_for_table("SH", "SALES")
        second_lock.acquire()
        second_lock.release()
