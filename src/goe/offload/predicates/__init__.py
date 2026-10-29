# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Immutable predicate AST, DSL parser, and multi-dialect SQL compiler."""

from goe.offload.predicates.ast import (
    BinaryComparison,
    ColumnRef,
    ComparisonOp,
    InListPredicate,
    LiteralKind,
    LiteralValue,
    LogicalAnd,
    LogicalNot,
    LogicalOr,
    NullCheckPredicate,
    PredicateExpr,
    ScalarValue,
    TypedValue,
    alias_column_names,
    column_names,
    rename_column,
    to_dsl,
    with_column_alias,
)
from goe.offload.predicates.compiler import (
    BindStyle,
    PredicateCompiler,
    PredicateDialect,
    PredicateSqlEngine,
    get_predicate_dialect_engine,
    render_predicate,
)
from goe.offload.predicates.parser import (
    RULE_HINT,
    PredicateOffloadException,
    parse_predicate_dsl,
    parse_safe_sql_predicate,
    resolve_predicate_types,
)

__all__ = (
    "RULE_HINT",
    "BinaryComparison",
    "BindStyle",
    "ColumnRef",
    "ComparisonOp",
    "InListPredicate",
    "LiteralKind",
    "LiteralValue",
    "LogicalAnd",
    "LogicalNot",
    "LogicalOr",
    "NullCheckPredicate",
    "PredicateCompiler",
    "PredicateDialect",
    "PredicateExpr",
    "PredicateOffloadException",
    "PredicateSqlEngine",
    "ScalarValue",
    "TypedValue",
    "alias_column_names",
    "column_names",
    "get_predicate_dialect_engine",
    "parse_predicate_dsl",
    "parse_safe_sql_predicate",
    "rename_column",
    "render_predicate",
    "resolve_predicate_types",
    "to_dsl",
    "with_column_alias",
)
