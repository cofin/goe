# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for bounded thread-pool execution utilities."""

import pytest

from goe.util.concurrency import run_bounded


def test_run_bounded_preserves_order_and_handles_empty() -> None:
    """run_bounded returns results in input order and handles empty sequences without spawning threads."""
    assert run_bounded([], lambda x: x) == []
    items = [1, 2, 3, 4, 5, 6]
    results = run_bounded(items, lambda x: x * 10, max_workers=3)
    assert results == [10, 20, 30, 40, 50, 60]


def test_run_bounded_propagates_worker_exceptions() -> None:
    """run_bounded propagates exceptions raised by worker callables."""

    def _boom(val: int) -> int:
        if val == 3:
            raise ValueError("worker failed on 3")
        return val

    with pytest.raises(ValueError, match="worker failed on 3"):
        run_bounded([1, 2, 3, 4], _boom, max_workers=2)
