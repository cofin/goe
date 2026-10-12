# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Oracle offload predicate rendering via PredicateDialectEngineProtocol."""

from typing import TYPE_CHECKING, Any

from goe.offload.predicate_offload import (
    GenericPredicate,
    GenericPredicateToTyped,
    get_predicate_dialect_engine,
    handle_parse_errors,
)

if TYPE_CHECKING:
    from goe.offload.column_metadata import ColumnMetadataInterface


def predicate_to_where_clause(
    oracle_columns: list["ColumnMetadataInterface"],
    predicate: GenericPredicate,
) -> str:
    """Render a GenericPredicate into an Oracle SQL WHERE clause with inline literals."""
    with handle_parse_errors():
        typed_ast = GenericPredicateToTyped(oracle_columns).transform(predicate.ast)
        return get_predicate_dialect_engine("oracle").render_literal_sql(typed_ast, oracle_columns)


def predicate_to_where_clause_with_binds(
    oracle_columns: list["ColumnMetadataInterface"],
    predicate: GenericPredicate,
) -> tuple[str, dict[str, Any]]:
    """Render a GenericPredicate into an Oracle SQL WHERE clause and named bind dictionary."""
    with handle_parse_errors():
        typed_ast = GenericPredicateToTyped(oracle_columns).transform(predicate.ast)
        rendered = get_predicate_dialect_engine("oracle").render_bind_sql(typed_ast, oracle_columns)
        return rendered.sql, rendered.params
