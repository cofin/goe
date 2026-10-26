# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Facade for offload-predicate DSL parsing, AST manipulation, and SQL rendering."""

import datetime
from collections.abc import Sequence
from typing import Literal

import numpy as np

from goe.offload.predicates import (
    RULE_HINT,
    LogicalAnd,
    LogicalOr,
    PredicateExpr,
    PredicateOffloadException,
    PredicateSqlEngine,
    alias_column_names,
    column_names,
    get_predicate_dialect_engine,
    parse_predicate_dsl,
    parse_safe_sql_predicate,
    rename_column,
    resolve_predicate_types,
    to_dsl,
    with_column_alias,
)

__all__ = (
    "RULE_HINT",
    "GenericPredicate",
    "PredicateOffloadException",
    "PredicateSqlEngine",
    "create_and_relation_predicate",
    "create_or_relation_predicate",
    "get_predicate_dialect_engine",
    "parse_predicate_dsl",
    "parse_safe_sql_predicate",
    "python_timestamp_to_string",
    "resolve_predicate_types",
)


def python_timestamp_to_string(
    python_ts: np.datetime64 | datetime.date | None,
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
    if isinstance(python_ts, datetime.date):
        if with_time and subsecond:
            return python_ts.strftime("%Y-%m-%d %H:%M:%S.%f")
        if with_time:
            return python_ts.strftime("%Y-%m-%d %H:%M:%S")
        return python_ts.strftime("%Y-%m-%d")
    return None


class GenericPredicate:
    """Offload predicate wrapper backed by an immutable ``PredicateExpr`` AST."""

    def __init__(self, raw_dsl: str | None = None, ast: PredicateExpr | None = None) -> None:
        self.ast: PredicateExpr = ast if ast is not None else parse_predicate_dsl(raw_dsl or "")

    @property
    def expr(self) -> PredicateExpr:
        """Return the underlying immutable ``PredicateExpr`` node."""
        return self.ast

    @property
    def dsl(self) -> str:
        """Render the predicate AST into canonical offload predicate DSL format."""
        return to_dsl(self.ast)

    def __str__(self) -> str:
        return self.dsl

    def __repr__(self) -> str:
        return f"<GenericPredicate: {self.dsl}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GenericPredicate) and self.ast == other.ast

    def alias_column_names(self) -> list[tuple[str | None, str]]:
        """Return unique ``(alias, column_name)`` pairs referenced in the predicate."""
        return alias_column_names(self.ast)

    def column_names(self) -> list[str]:
        """Return unique uppercase column names referenced in the predicate."""
        return column_names(self.ast)

    def rename_column(self, original_name: str, new_name: str) -> None:
        """Replace ``original_name`` with ``new_name`` across all column references."""
        self.ast = rename_column(self.ast, original_name, new_name)

    def set_column_alias(self, new_alias: str | None) -> None:
        """Set or clear the table alias across all column references."""
        self.ast = with_column_alias(self.ast, new_alias)


def create_or_relation_predicate(children_predicates: Sequence[GenericPredicate]) -> GenericPredicate:
    """Return a ``GenericPredicate`` combining ``children_predicates`` with ``LogicalOr``."""
    assert all(isinstance(p, GenericPredicate) for p in children_predicates)
    return GenericPredicate(ast=LogicalOr(children=tuple(p.ast for p in children_predicates)))


def create_and_relation_predicate(children_predicates: Sequence[GenericPredicate]) -> GenericPredicate:
    """Return a ``GenericPredicate`` combining ``children_predicates`` with ``LogicalAnd``."""
    assert all(isinstance(p, GenericPredicate) for p in children_predicates)
    return GenericPredicate(ast=LogicalAnd(children=tuple(p.ast for p in children_predicates)))
