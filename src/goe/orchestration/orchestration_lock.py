# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OrchestrationLock: Library providing simple locking mechanism for orchestration commands.
In general the lock is expected to be the source owner/table name of a command.
"""

import logging
import os
from abc import ABCMeta, abstractmethod

from filelock import FileLock, Timeout

from goe.persistence.orchestration_metadata import OrchestrationMetadata

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OrchestrationLockTimeout(Exception):
    pass


LOCK_FILE_PREFIX = "orchestration_"
LOCK_FILE_SUFFIX = ".lock"


def orchestration_lock_for_table(owner, table_name, dry_run=False):
    """Return lock handler using owner/table_name as lock ids.
    For now we only support FileLock implementation but others could be slotted in in the future.
    """
    return FileLockOrchestrationLock([owner, table_name], dry_run=dry_run)


def orchestration_lock_from_hybrid_metadata(hybrid_metadata, dry_run=False):
    """Return lock handler using offloaded owner/table metadata as lock ids.
    For now we only support FileLock implementation but others could be slotted in in the future.
    """
    assert hybrid_metadata
    assert isinstance(hybrid_metadata, OrchestrationMetadata)
    assert hybrid_metadata.offloaded_owner
    assert hybrid_metadata.offloaded_table
    return FileLockOrchestrationLock(
        [hybrid_metadata.offloaded_owner, hybrid_metadata.offloaded_table],
        dry_run=dry_run,
    )


class OrchestrationLockInterface(metaclass=ABCMeta):
    """Library providing simple locking mechanism for orchestration commands.

    In general the lock is expected to be the source owner/table name of a command.
    Lock files are located in $OFFLOAD_HOME/run.
    """

    def __init__(self, lock_ids, dry_run=False):
        assert lock_ids
        assert isinstance(lock_ids, (list, str))
        if isinstance(lock_ids, str):
            self._lock_ids = [lock_ids]
        else:
            self._lock_ids = lock_ids
        self._dry_run = dry_run
        self._lock: FileLock | None = None

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.release()

    @abstractmethod
    def acquire(self):
        pass

    @abstractmethod
    def release(self):
        pass

    def _exception_message(self):
        return "Another Orchestration process has locked id: {}".format(".".join(self._lock_ids))


class FileLockOrchestrationLock(OrchestrationLockInterface):
    """FileLock implementation of OrchestrationLockInterface.

    Lock files are located in $OFFLOAD_HOME/run.
    """

    def __init__(self, lock_ids, dry_run=False):
        super().__init__(lock_ids, dry_run=dry_run)
        self._file_name = self._lock_file_name()
        logger.info(f"Orchestration lock filename: {self._file_name}")
        self._lock = FileLock(self._file_name)

    def acquire(self):
        """Acquire the file lock with zero timeout when not in dry-run mode.

        FileLock.acquire() creates a lock file with default umask, which may prevent
        other users from running commands if they cannot write to the lock file.
        """
        try:
            if not self._dry_run and self._lock is not None:
                self._lock.acquire(timeout=0)
        except Timeout as exc:
            logger.info(f"Orchestration lock acquire timeout: {exc!s}")
            raise OrchestrationLockTimeout(self._exception_message()) from exc

    def release(self):
        if not self._dry_run and self._lock is not None:
            self._lock.release()

    def _lock_file_name(self):
        file_name = LOCK_FILE_PREFIX + "_".join(self._lock_ids) + LOCK_FILE_SUFFIX
        return os.path.join(os.environ.get("OFFLOAD_HOME") or "", "run", file_name)
