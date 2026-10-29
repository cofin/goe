# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Offload predicate specialisation for Oracle SQL."""

from typing import Any

from goe.offload.predicate_offload import (
    GenericPredicate,
    get_predicate_dialect_engine,
    resolve_predicate_types,
)


def predicate_to_where_clause(
    oracle_columns: list[Any],
    predicate: GenericPredicate,
) -> str:
    """Render a GenericPredicate into an Oracle SQL WHERE clause with inline literals."""
    resolved = resolve_predicate_types(predicate.ast, oracle_columns, include_synthetic=False)
    return get_predicate_dialect_engine("oracle").render_literal_sql(resolved, oracle_columns)


def predicate_to_where_clause_with_binds(
    oracle_columns: list[Any],
    predicate: GenericPredicate,
) -> tuple[str, dict[str, Any]]:
    """Render a GenericPredicate into an Oracle SQL WHERE clause and named bind dictionary."""
    resolved = resolve_predicate_types(predicate.ast, oracle_columns, include_synthetic=False)
    rendered = get_predicate_dialect_engine("oracle").render_bind_sql(resolved, oracle_columns)
    return rendered.sql, rendered.params
