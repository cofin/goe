# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Offload predicate specialisation for Synapse T-SQL."""

from typing import Any

from goe.offload.predicate_offload import (
    GenericPredicate,
    get_predicate_dialect_engine,
    resolve_predicate_types,
)


def predicate_to_where_clause(
    synapse_columns: list[Any],
    predicate: GenericPredicate,
) -> str:
    """Render a GenericPredicate into a Synapse T-SQL WHERE clause with synthetic partition clauses."""
    resolved = resolve_predicate_types(predicate.ast, synapse_columns, include_synthetic=True)
    return get_predicate_dialect_engine("tsql").render_literal_sql(resolved, synapse_columns)


def predicate_to_where_clause_with_binds(
    synapse_columns: list[Any],
    predicate: GenericPredicate,
) -> tuple[str, dict[str, Any]]:
    """Render a GenericPredicate into a Synapse T-SQL WHERE clause and named bind dictionary."""
    resolved = resolve_predicate_types(predicate.ast, synapse_columns, include_synthetic=True)
    rendered = get_predicate_dialect_engine("tsql").render_bind_sql(resolved, synapse_columns)
    return rendered.sql, rendered.params
