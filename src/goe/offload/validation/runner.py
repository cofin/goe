# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Concurrent cross-DB validation execution and mismatch reconciliation."""

import math
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from goe.offload.validation.ast_builder import (
    AggregateQuestion,
    ValidationBatchQuery,
)
from goe.typing import FrozenBaseStruct
from goe.util.concurrency import run_bounded

__all__ = (
    "DEFAULT_APPROXIMATE_TOLERANCE",
    "ColumnMismatch",
    "CrossDbValidator",
    "QueryExecutorFn",
    "ValidationResult",
)

DEFAULT_APPROXIMATE_TOLERANCE: float = 1e-6

type QueryExecutorFn = Callable[[str, Mapping[str, Any]], list[dict[str, Any]]]


class ColumnMismatch(FrozenBaseStruct, frozen=True):
    """Single aggregate mismatch between source and target databases."""

    group_key: tuple[tuple[str, Any], ...]
    alias: str
    column: str | None
    func: str
    source_value: Any
    target_value: Any


class ValidationResult(FrozenBaseStruct, frozen=True):
    """Immutable outcome of a cross-DB validation run."""

    success: bool
    mismatches: tuple[ColumnMismatch, ...]
    batches_executed: int
    rows_compared: int


class CrossDbValidator:
    """Execute source and target validation batches concurrently and reconcile results."""

    def __init__(
        self,
        *,
        source_executor: QueryExecutorFn,
        target_executor: QueryExecutorFn,
        approximate_tolerance: float = DEFAULT_APPROXIMATE_TOLERANCE,
    ) -> None:
        self._source_executor = source_executor
        self._target_executor = target_executor
        self._approximate_tolerance = approximate_tolerance

    def execute_batches(
        self,
        *,
        source_batches: Sequence[ValidationBatchQuery],
        target_batches: Sequence[ValidationBatchQuery],
        questions: Sequence[AggregateQuestion],
    ) -> ValidationResult:
        """Run source and target batch sequences concurrently via run_bounded and compare results."""
        if len(source_batches) != len(target_batches):
            raise ValueError("source_batches and target_batches must have identical length")
        if not source_batches:
            return ValidationResult(
                success=True,
                mismatches=(),
                batches_executed=0,
                rows_compared=0,
            )

        def _run_source() -> list[list[dict[str, Any]]]:
            return [self._source_executor(b.sql, b.parameters) for b in source_batches]

        def _run_target() -> list[list[dict[str, Any]]]:
            return [self._target_executor(b.sql, b.parameters) for b in target_batches]

        results = run_bounded([_run_source, _run_target], max_workers=2)
        source_batch_rows, target_batch_rows = results[0], results[1]

        question_by_alias = {q.alias.upper(): q for q in questions}
        mismatches: list[ColumnMismatch] = []
        rows_compared = 0

        for idx, src_batch in enumerate(source_batches):
            src_rows = source_batch_rows[idx]
            tgt_rows = target_batch_rows[idx]
            group_bys = src_batch.group_bys
            src_map = self._index_by_group(src_rows, group_bys)
            tgt_map = self._index_by_group(tgt_rows, group_bys)
            all_keys = list(dict.fromkeys([*src_map.keys(), *tgt_map.keys()]))
            rows_compared += len(all_keys)

            for gkey in all_keys:
                srow = src_map.get(gkey, {})
                trow = tgt_map.get(gkey, {})
                for alias in src_batch.aliases:
                    q = question_by_alias[alias.upper()]
                    sval = srow.get(alias.upper())
                    tval = trow.get(alias.upper())
                    if not self._values_equal(sval, tval, approximate=q.approximate):
                        mismatches.append(
                            ColumnMismatch(
                                group_key=gkey,
                                alias=q.alias,
                                column=q.column,
                                func=q.func,
                                source_value=sval,
                                target_value=tval,
                            )
                        )

        return ValidationResult(
            success=len(mismatches) == 0,
            mismatches=tuple(mismatches),
            batches_executed=len(source_batches),
            rows_compared=rows_compared,
        )

    def _values_equal(self, left: Any, right: Any, *, approximate: bool) -> bool:
        """Compare source and target aggregate values with optional floating-point tolerance."""
        if left is None and right is None:
            return True
        if left is None or right is None:
            return False
        if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
            if approximate or isinstance(left, float) or isinstance(right, float):
                return math.isclose(
                    float(left),
                    float(right),
                    rel_tol=self._approximate_tolerance,
                    abs_tol=self._approximate_tolerance,
                )
            return Decimal(str(left)) == Decimal(str(right))
        return str(left).strip() == str(right).strip()

    @staticmethod
    def _index_by_group(
        rows: Sequence[Mapping[str, Any]],
        group_bys: Sequence[str],
    ) -> dict[tuple[tuple[str, Any], ...], dict[str, Any]]:
        """Normalize row keys to uppercase and index by group-by column tuple."""
        indexed: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
        for row in rows:
            upper_row = {str(k).upper(): v for k, v in row.items()}
            key = tuple((g.upper(), upper_row.get(g.upper())) for g in group_bys)
            indexed[key] = upper_row
        if not indexed and not group_bys:
            indexed[()] = {}
        return indexed
