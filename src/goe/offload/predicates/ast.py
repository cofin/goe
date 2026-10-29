# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Immutable intermediate representation AST for GOE offload predicates."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import numpy as np

from goe.typing import FrozenBaseStruct

__all__ = (
    "BinaryComparison",
    "ColumnRef",
    "ComparisonOp",
    "InListPredicate",
    "LiteralKind",
    "LiteralValue",
    "LogicalAnd",
    "LogicalNot",
    "LogicalOr",
    "NullCheckPredicate",
    "PredicateExpr",
    "ScalarValue",
    "TypedValue",
    "alias_column_names",
    "column_names",
    "python_timestamp_to_string",
    "rename_column",
    "to_dsl",
    "with_column_alias",
)

type ComparisonOp = Literal["=", "!=", "<", "<=", ">", ">="]
type LiteralKind = Literal["integer", "decimal", "string", "bytes", "date", "datetime", "raw_sql"]
type ScalarValue = int | float | Decimal | str | bytes | date | datetime | np.datetime64


class ColumnRef(FrozenBaseStruct, frozen=True, tag="col"):
    """Column reference with optional table alias normalized to uppercase."""

    name: str
    alias: str | None = None


class TypedValue(FrozenBaseStruct, frozen=True, tag="val"):
    """Typed literal value preserving exact Decimal digits and nanosecond timestamps."""

    kind: LiteralKind
    text: str

    @property
    def raw(self) -> ScalarValue:
        """Return the typed Python or NumPy value for bind parameters and synthetic literals."""
        if self.kind == "integer":
            return int(self.text)
        if self.kind == "decimal":
            return Decimal(self.text)
        if self.kind == "bytes":
            return bytes.fromhex(self.text)
        if self.kind == "date":
            return np.datetime64(self.text, "D")
        if self.kind == "datetime":
            return np.datetime64(self.text.replace(" ", "T"))
        return self.text


class LiteralValue(FrozenBaseStruct, frozen=True, tag="lit"):
    """Literal AST node paired with an optional resolved database column data type."""

    value: TypedValue
    data_type: str | None = None


class BinaryComparison(FrozenBaseStruct, frozen=True, tag="cmp"):
    """Binary comparison between a column reference and a literal value."""

    op: ComparisonOp
    column: ColumnRef
    literal: LiteralValue
    lhs_is_column: bool = True


class InListPredicate(FrozenBaseStruct, frozen=True, tag="in"):
    """IN or NOT IN membership predicate over a tuple of literal values."""

    column: ColumnRef
    values: tuple[LiteralValue, ...]
    negated: bool = False


class NullCheckPredicate(FrozenBaseStruct, frozen=True, tag="null"):
    """IS NULL or IS NOT NULL predicate."""

    column: ColumnRef
    is_not_null: bool = False


class LogicalAnd(FrozenBaseStruct, frozen=True, tag="and"):
    """Conjunction over two or more child predicate expressions."""

    children: tuple["PredicateExpr", ...]


class LogicalOr(FrozenBaseStruct, frozen=True, tag="or"):
    """Disjunction over two or more child predicate expressions."""

    children: tuple["PredicateExpr", ...]


class LogicalNot(FrozenBaseStruct, frozen=True, tag="not"):
    """Logical negation of a child predicate expression."""

    child: "PredicateExpr"


type PredicateExpr = BinaryComparison | InListPredicate | NullCheckPredicate | LogicalAnd | LogicalOr | LogicalNot


def column_names(expr: PredicateExpr) -> list[str]:
    """Return unique uppercase column names referenced in a predicate expression."""
    return list(dict.fromkeys(col.name for col in _iter_columns(expr)))


def alias_column_names(expr: PredicateExpr) -> list[tuple[str | None, str]]:
    """Return unique ``(alias, column_name)`` pairs referenced in a predicate expression."""
    return list(dict.fromkeys((col.alias, col.name) for col in _iter_columns(expr)))


def rename_column(expr: PredicateExpr, original_name: str, new_name: str) -> PredicateExpr:
    """Return a new predicate expression with ``original_name`` replaced by ``new_name``."""
    orig_upper = original_name.upper()
    new_upper = new_name.upper()
    return _map_columns(
        expr,
        lambda col: ColumnRef(name=new_upper, alias=col.alias) if col.name == orig_upper else col,
    )


def with_column_alias(expr: PredicateExpr, new_alias: str | None) -> PredicateExpr:
    """Return a new predicate expression with all column aliases set to ``new_alias``."""
    normalized_alias = new_alias.upper() if new_alias is not None else None
    return _map_columns(
        expr,
        lambda col: ColumnRef(name=col.name, alias=normalized_alias),
    )


def to_dsl(expr: PredicateExpr) -> str:
    """Render a ``PredicateExpr`` back into canonical GOE offload predicate DSL text."""
    if isinstance(expr, BinaryComparison):
        col_dsl = _column_to_dsl(expr.column)
        lit_dsl = _literal_to_dsl(expr.literal)
        if expr.lhs_is_column:
            return f"{col_dsl} {expr.op} {lit_dsl}"
        return f"{lit_dsl} {expr.op} {col_dsl}"
    if isinstance(expr, InListPredicate):
        col_dsl = _column_to_dsl(expr.column)
        op_dsl = "NOT IN" if expr.negated else "IN"
        vals_dsl = ", ".join(_literal_to_dsl(v) for v in expr.values)
        return f"{col_dsl} {op_dsl} ({vals_dsl})"
    if isinstance(expr, NullCheckPredicate):
        col_dsl = _column_to_dsl(expr.column)
        null_dsl = "IS NOT NULL" if expr.is_not_null else "IS NULL"
        return f"{col_dsl} {null_dsl}"
    if isinstance(expr, LogicalAnd):
        return "(" + " AND ".join(to_dsl(child) for child in expr.children) + ")"
    if isinstance(expr, LogicalOr):
        return "(" + " OR ".join(to_dsl(child) for child in expr.children) + ")"
    return f"(NOT {to_dsl(expr.child)})"


def python_timestamp_to_string(
    python_ts: np.datetime64 | date | None,
    with_time: bool = True,
    subsecond: int = 0,
) -> str | None:
    """Convert a Python ``datetime64`` or ``date``/``datetime`` value into a formatted string."""
    if python_ts is None:
        return None
    if isinstance(python_ts, np.datetime64):
        if with_time and subsecond:
            np_unit: Literal["ns", "us", "ms"]
            if subsecond > 6:
                np_unit = "ns"
            elif subsecond > 3:
                np_unit = "us"
            else:
                np_unit = "ms"
            return np.datetime_as_string(python_ts, np_unit).replace("T", " ")
        if with_time:
            return np.datetime_as_string(python_ts, "s").replace("T", " ")
        return np.datetime_as_string(python_ts, "D")
    if isinstance(python_ts, date):
        if with_time and subsecond:
            return python_ts.strftime("%Y-%m-%d %H:%M:%S.%f")
        if with_time:
            return python_ts.strftime("%Y-%m-%d %H:%M:%S")
        return python_ts.strftime("%Y-%m-%d")
    return None


def _iter_columns(expr: PredicateExpr) -> list[ColumnRef]:
    """Collect all ``ColumnRef`` nodes in pre-order traversal."""
    if isinstance(expr, (BinaryComparison, InListPredicate, NullCheckPredicate)):
        return [expr.column]
    if isinstance(expr, (LogicalAnd, LogicalOr)):
        cols: list[ColumnRef] = []
        for child in expr.children:
            cols.extend(_iter_columns(child))
        return cols
    return _iter_columns(expr.child)


def _map_columns(expr: PredicateExpr, fn: Callable[[ColumnRef], ColumnRef]) -> PredicateExpr:
    """Apply ``fn`` to every ``ColumnRef`` in ``expr`` and return a new immutable tree."""
    if isinstance(expr, BinaryComparison):
        return BinaryComparison(
            op=expr.op,
            column=fn(expr.column),
            literal=expr.literal,
            lhs_is_column=expr.lhs_is_column,
        )
    if isinstance(expr, InListPredicate):
        return InListPredicate(
            column=fn(expr.column),
            values=expr.values,
            negated=expr.negated,
        )
    if isinstance(expr, NullCheckPredicate):
        return NullCheckPredicate(
            column=fn(expr.column),
            is_not_null=expr.is_not_null,
        )
    if isinstance(expr, LogicalAnd):
        return LogicalAnd(children=tuple(_map_columns(child, fn) for child in expr.children))
    if isinstance(expr, LogicalOr):
        return LogicalOr(children=tuple(_map_columns(child, fn) for child in expr.children))
    return LogicalNot(child=_map_columns(expr.child, fn))


def _column_to_dsl(col: ColumnRef) -> str:
    """Format a ``ColumnRef`` in offload predicate DSL notation."""
    if col.alias:
        return f"column({col.alias}.{col.name})"
    return f"column({col.name})"


def _literal_to_dsl(lit: LiteralValue) -> str:
    """Format a ``LiteralValue`` in offload predicate DSL notation."""
    val = lit.value
    if val.kind in ("integer", "decimal"):
        return f"numeric({val.text})"
    if val.kind in ("date", "datetime"):
        return f"datetime({val.text})"
    if val.kind == "raw_sql":
        return f'literal("{val.text}")'
    return f'string("{val.text}")'
