# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""File-based orchestration table locking primitives using filelock in $OFFLOAD_HOME/run/."""

import logging
import os
from abc import ABCMeta, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from filelock import FileLock, Timeout

if TYPE_CHECKING:
    from goe.persistence.models import OffloadMetadata

__all__ = [
    "LOCK_FILE_PREFIX",
    "LOCK_FILE_SUFFIX",
    "FileLockOrchestrationLock",
    "FileOrchestrationLock",
    "OrchestrationLockInterface",
    "OrchestrationLockTimeout",
    "orchestration_lock_for_table",
    "orchestration_lock_from_hybrid_metadata",
]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

LOCK_FILE_PREFIX = "orchestration_"
LOCK_FILE_SUFFIX = ".lock"


class OrchestrationLockTimeout(Exception):
    """Raised when an orchestration table lock cannot be acquired immediately."""


class OrchestrationLockInterface(metaclass=ABCMeta):
    """Abstract interface for orchestration command table locks."""

    def __init__(self, lock_ids: Sequence[str] | str, dry_run: bool = False) -> None:
        assert lock_ids
        assert isinstance(lock_ids, (list, tuple, str))
        if isinstance(lock_ids, str):
            self._lock_ids = [lock_ids]
        else:
            self._lock_ids = list(lock_ids)
        self._dry_run = dry_run
        self._lock: FileLock | None = None

    def __enter__(self) -> "OrchestrationLockInterface":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, exc_traceback: Any) -> None:
        self.release()

    @abstractmethod
    def acquire(self) -> None:
        """Acquire the orchestration lock."""

    @abstractmethod
    def release(self) -> None:
        """Release the orchestration lock."""

    def _exception_message(self) -> str:
        return "Another Orchestration process has locked id: {}".format(".".join(self._lock_ids))


class FileOrchestrationLock(OrchestrationLockInterface):
    """FileLock implementation of OrchestrationLockInterface storing locks in $OFFLOAD_HOME/run."""

    def __init__(self, lock_ids: Sequence[str] | str, dry_run: bool = False) -> None:
        super().__init__(lock_ids, dry_run=dry_run)
        self._file_name = self._lock_file_name()
        logger.info(f"Orchestration lock filename: {self._file_name}")
        self._lock = FileLock(self._file_name)

    def acquire(self) -> None:
        """Acquire the file lock with zero timeout when not in dry-run mode."""
        try:
            if not self._dry_run and self._lock is not None:
                self._lock.acquire(timeout=0)
        except Timeout as exc:
            logger.info(f"Orchestration lock acquire timeout: {exc!s}")
            raise OrchestrationLockTimeout(self._exception_message()) from exc

    def release(self) -> None:
        """Release the held file lock when not in dry-run mode."""
        if not self._dry_run and self._lock is not None:
            self._lock.release()

    def _lock_file_name(self) -> str:
        file_name = LOCK_FILE_PREFIX + "_".join(self._lock_ids) + LOCK_FILE_SUFFIX
        return os.path.join(os.environ.get("OFFLOAD_HOME") or "", "run", file_name)


FileLockOrchestrationLock = FileOrchestrationLock


def orchestration_lock_for_table(
    owner: str,
    table_name: str,
    dry_run: bool = False,
) -> FileOrchestrationLock:
    """Return a FileOrchestrationLock using owner and table_name as lock identifiers."""
    return FileOrchestrationLock([owner, table_name], dry_run=dry_run)


def orchestration_lock_from_hybrid_metadata(
    hybrid_metadata: "OffloadMetadata",
    dry_run: bool = False,
) -> FileOrchestrationLock:
    """Return a FileOrchestrationLock using offloaded owner/table attributes on hybrid_metadata."""
    assert hybrid_metadata
    assert hybrid_metadata.offloaded_owner
    assert hybrid_metadata.offloaded_table
    return FileOrchestrationLock(
        [hybrid_metadata.offloaded_owner, hybrid_metadata.offloaded_table],
        dry_run=dry_run,
    )
