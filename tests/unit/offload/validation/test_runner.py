# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for CrossDbValidator."""

import threading
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from goe.offload.validation.ast_builder import (
    AggregateQuestion,
    ValidationBatchQuery,
)
from goe.offload.validation.runner import CrossDbValidator


def test_execute_batches_runs_concurrently_and_succeeds() -> None:
    """Verify source and target executors run concurrently and matching values pass."""
    barrier = threading.Barrier(2, timeout=2.0)

    def source_exec(sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        barrier.wait()
        return [{"P1": "2026-01", "CNT": 100, "SUM_A": Decimal("50.25"), "AVG_A": 1.0000001}]

    def target_exec(sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        barrier.wait()
        return [{"p1": "2026-01", "cnt": 100, "sum_a": Decimal("50.25"), "avg_a": 1.0000002}]

    questions = [
        AggregateQuestion(column=None, func="COUNT", alias="CNT"),
        AggregateQuestion(column="A", func="SUM", alias="SUM_A"),
        AggregateQuestion(column="A", func="AVG", alias="AVG_A", approximate=True),
    ]
    batch = ValidationBatchQuery(
        sql="SELECT 1",
        parameters={},
        aliases=("CNT", "SUM_A", "AVG_A"),
        group_bys=("P1",),
    )
    validator = CrossDbValidator(source_executor=source_exec, target_executor=target_exec)
    result = validator.execute_batches(
        source_batches=[batch],
        target_batches=[batch],
        questions=questions,
    )
    assert result.success is True
    assert result.mismatches == ()
    assert result.batches_executed == 1
    assert result.rows_compared == 1


def test_execute_batches_detects_mismatch() -> None:
    """Verify mismatched aggregate values are captured in ColumnMismatch structs."""

    def source_exec(sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        time.sleep(0.001)
        return [{"CNT": 100, "MIN_A": 10}]

    def target_exec(sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [{"CNT": 99, "MIN_A": 10}]

    questions = [
        AggregateQuestion(column=None, func="COUNT", alias="CNT"),
        AggregateQuestion(column="A", func="MIN", alias="MIN_A"),
    ]
    batch = ValidationBatchQuery(
        sql="SELECT 1",
        parameters={},
        aliases=("CNT", "MIN_A"),
        group_bys=(),
    )
    validator = CrossDbValidator(source_executor=source_exec, target_executor=target_exec)
    result = validator.execute_batches(
        source_batches=[batch],
        target_batches=[batch],
        questions=questions,
    )
    assert result.success is False
    assert len(result.mismatches) == 1
    mismatch = result.mismatches[0]
    assert mismatch.alias == "CNT"
    assert mismatch.source_value == 100
    assert mismatch.target_value == 99
