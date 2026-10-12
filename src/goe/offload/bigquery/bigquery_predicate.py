# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""BigQuery offload predicate rendering via PredicateDialectEngineProtocol."""

from typing import TYPE_CHECKING, Any

from goe.offload.predicate_offload import (
    GenericPredicate,
    GenericPredicateToTyped,
    InsertSyntheticPartitionClauses,
    get_predicate_dialect_engine,
    handle_parse_errors,
)

if TYPE_CHECKING:
    from goe.offload.column_metadata import ColumnMetadataInterface


def predicate_to_where_clause(
    bigquery_columns: list["ColumnMetadataInterface"],
    predicate: GenericPredicate,
) -> str:
    """Render a GenericPredicate into a BigQuery SQL WHERE clause with synthetic partition clauses."""
    with handle_parse_errors():
        pipeline = GenericPredicateToTyped(bigquery_columns) * InsertSyntheticPartitionClauses(bigquery_columns)
        typed_ast = pipeline.transform(predicate.ast)
        return get_predicate_dialect_engine("bigquery").render_literal_sql(typed_ast, bigquery_columns)


def predicate_to_where_clause_with_binds(
    bigquery_columns: list["ColumnMetadataInterface"],
    predicate: GenericPredicate,
) -> tuple[str, dict[str, Any]]:
    """Render a GenericPredicate into a BigQuery SQL WHERE clause and named bind dictionary."""
    with handle_parse_errors():
        pipeline = GenericPredicateToTyped(bigquery_columns) * InsertSyntheticPartitionClauses(bigquery_columns)
        typed_ast = pipeline.transform(predicate.ast)
        rendered = get_predicate_dialect_engine("bigquery").render_bind_sql(typed_ast, bigquery_columns)
        return rendered.sql, rendered.params
