# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Bounded thread-pool execution and async/sync bridging utilities."""

from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlspec.utils.portal import (
    Portal,
    get_global_portal,
)
from sqlspec.utils.sync_tools import (
    CapacityLimiter,
    async_,
    await_,
    ensure_async_,
    run_,
    set_default_async_executor,
    with_ensure_async_,
)

from goe.util.string_utils import typed_property

__all__ = [
    "STATUS_NOOP",
    "CapacityLimiter",
    "ParallelExecException",
    "ParallelExecutor",
    "Portal",
    "async_",
    "await_",
    "ensure_async_",
    "get_global_portal",
    "run_",
    "run_bounded",
    "set_default_async_executor",
    "with_ensure_async_",
]

STATUS_NOOP = "<noop>"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class ParallelExecException(Exception):
    """Raised when a parallel execution task fails or receives invalid options."""


class ParallelExecutor:
    """Execute tasks sequentially or across bounded ThreadPoolExecutor workers."""

    submitted = typed_property("submitted", int)
    executed = typed_property("executed", int)
    successful = typed_property("successful", int)
    failed = typed_property("failed", int)
    noop = typed_property("noop", int)

    def __init__(self) -> None:
        self._submitted: int = 0
        self._executed: int = 0
        self._successful: int = 0
        self._failed: int = 0
        self._noop: int = 0
        self._tasks: dict[Any, Any] = {}
        logger.debug("ParallelExecutor() object successfully initialized")

    @property
    def tasks(self) -> dict[Any, Any]:
        """Return task execution statuses keyed by task identifier."""
        return self._tasks

    def execute_sequentially(self, job_tasks: Sequence[Any], ids: bool = False) -> list[Any]:
        """Execute job_tasks sequentially in the caller thread."""
        assert job_tasks
        self._initialize()
        logger.debug("Starting sequential execution")

        for default_job_id, task_item in enumerate(job_tasks):
            job_id: Any = default_job_id
            args: list[Any] = []
            if not isinstance(task_item, list):
                if ids:
                    raise ParallelExecException("'ids' parameter is incompatible with 'simple task' mode")
                task = task_item
            else:
                task, args = task_item[0], list(task_item[1:])
                if ids:
                    job_id = args.pop(0)

            self._submitted += 1
            st = task(*args)
            logger.debug("Result for job: %s is: %s", job_id, st)
            self._tasks[job_id] = st
            self._executed += 1
            if st == STATUS_NOOP:
                self._noop += 1
            elif st:
                self._successful += 1
            else:
                self._failed += 1

        return list(self._tasks.values())

    def execute_in_threads(
        self,
        parallel: int | None,
        job_tasks: Sequence[Any],
        kill_on_first_error: bool = True,
        ids: bool = False,
    ) -> list[Any]:
        """Execute job_tasks across a ThreadPoolExecutor with up to parallel workers."""
        assert job_tasks
        if not parallel:
            return self.execute_sequentially(job_tasks, ids)

        self._initialize()
        logger.debug("Starting execution with: %s parallel threads", parallel)

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            submitted_threads: dict[concurrent.futures.Future[Any], Any] = {}
            for default_thread_id, task_item in enumerate(job_tasks):
                thread_id: Any = default_thread_id
                if not isinstance(task_item, list):
                    if ids:
                        raise ParallelExecException("'ids' parameter is incompatible with 'simple task' mode")
                    task = task_item
                    submitted_threads[executor.submit(task)] = thread_id
                else:
                    task, args = task_item[0], list(task_item[1:])
                    if ids:
                        thread_id = args.pop(0)
                    submitted_threads[executor.submit(task, *args)] = thread_id
                self._submitted += 1

            for future in concurrent.futures.as_completed(submitted_threads):
                thread_id = submitted_threads[future]
                try:
                    st = future.result()
                    logger.debug("Result for thread: %s is: %s", thread_id, st)
                    self._tasks[thread_id] = st
                    self._executed += 1
                    if st == STATUS_NOOP:
                        self._noop += 1
                    elif st:
                        self._successful += 1
                    else:
                        self._failed += 1
                except Exception as exc:
                    msg = f"Exception detected: {exc} in parallel thread: {thread_id}"
                    if kill_on_first_error:
                        raise ParallelExecException(msg) from exc
                    logger.warning(msg)
                    self._tasks[thread_id] = False
                    self._executed += 1
                    self._failed += 1

        return list(self._tasks.values())

    def _initialize(self) -> None:
        self._submitted = 0
        self._executed = 0
        self._successful = 0
        self._failed = 0
        self._noop = 0
        self._tasks = {}


def run_bounded[T, R](
    items: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int = 4,
) -> list[R]:
    """Execute fn over items with a bounded ThreadPoolExecutor, preserving input order."""
    if not items:
        return []
    worker_count = max(1, min(max_workers, len(items)))
    if worker_count == 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(fn, item) for item in items]
        try:
            return [future.result() for future in futures]
        except BaseException:
            for future in futures:
                future.cancel()
            raise
