# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ValidationSqlEngine and CrossDbValidator filter/query construction."""

import pytest

from goe.offload.offload_validation import (
    CrossDbValidatorException,
    OffloadValidationException,
    combine_validation_filters,
    diff_rows_in_duckdb,
    get_validation_query_engine,
    validate_raw_filter_clause,
)
from goe.offload.predicate_offload import PredicateOffloadException
from goe.offload.sql_engine import ValidationQueryEngineProtocol, ValidationQuerySpec


def test_validation_query_engine_satisfies_protocol() -> None:
    """Verify get_validation_query_engine returns a ValidationQueryEngineProtocol instance."""
    engine = get_validation_query_engine("bigquery")
    assert isinstance(engine, ValidationQueryEngineProtocol)
    assert OffloadValidationException is CrossDbValidatorException


def test_validate_raw_filter_clause_accepts_valid_conditions() -> None:
    """Verify safe SQL filter strings (including binds and 3-arg TO_DATE) pass AST allowlist validation."""
    cleaned = validate_raw_filter_clause("ID >= 100 AND REGION IN ('US', 'EU')", dialect="oracle")
    assert cleaned == "ID >= 100 AND REGION IN ('US', 'EU')"

    to_date_filter = "TIME_ID < TO_DATE(' 2012-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')"
    assert validate_raw_filter_clause(to_date_filter, dialect="oracle") == to_date_filter

    bind_filter = "((col1 <= :year and col2 < :month) or (col1 < :year))"
    assert validate_raw_filter_clause(bind_filter, dialect="oracle") == bind_filter


def test_validate_raw_filter_clause_rejects_subquery_and_stacked_sql() -> None:
    """Verify subquery injection, EXISTS, stacked statements, and disallowed functions are rejected."""
    for bad_filter in (
        "ID = 1 OR (SELECT COUNT(*) FROM user_tables) > 0",
        "ID = 1 OR EXISTS (SELECT 1 FROM dual)",
        "1 = 1; DROP TABLE sales",
        "DBMS_LOCK.SLEEP(5) = 0",
    ):
        with pytest.raises((CrossDbValidatorException, PredicateOffloadException)):
            validate_raw_filter_clause(bad_filter, dialect="oracle")


def test_build_aggregate_query_preserves_hints_scn_and_aliases() -> None:
    """Verify build_aggregate_query preserves Oracle hints, AS OF SCN, and projection aliases."""
    engine = get_validation_query_engine("oracle")
    spec = ValidationQuerySpec(
        table_identifier='"SH"."SALES"',
        select_items=["COUNT(*) AS CNT", 'MIN("ID") AS "ID_MIN"'],
        where_clauses=["1 = 1", '"ID" > 10', "\"REGION\" = 'US'"],
        group_by_cols=['"REGION"'],
        order_by_cols=["1"],
        query_hints="/*+ PARALLEL(t, 4) */",
        prior_to_where="AS OF SCN 987654",
        dialect="oracle",
    )
    sql = engine.build_aggregate_query(spec)
    assert sql.startswith('SELECT /*+ PARALLEL(t, 4) */ COUNT(*) AS CNT, MIN("ID") AS "ID_MIN"')
    assert 'FROM "SH"."SALES" AS OF SCN 987654' in sql
    assert 'WHERE ("ID" > 10) AND ("REGION" = \'US\')' in sql
    assert 'GROUP BY "REGION"' in sql
    assert "ORDER BY 1" in sql


def test_combine_validation_filters_wraps_and_simplifies() -> None:
    """Verify multiple filter clauses are combined into a parenthesized conjunction dropping 1=1."""
    where_sql = combine_validation_filters(["1 = 1", "ID > 10", "REGION = 'US'"], dialect="bigquery")
    assert where_sql == "(ID > 10) AND (REGION = 'US')"


def test_diff_rows_in_duckdb_returns_differing_source_rows() -> None:
    """Verify diff_rows_in_duckdb computes in-memory DuckDB EXCEPT diffs over row dicts."""
    source_rows = [{"P1": "2026-01", "CNT": 100}, {"P1": "2026-02", "CNT": 250}]
    target_rows = [{"p1": "2026-01", "cnt": 100}, {"p1": "2026-02", "cnt": 249}]
    diffs = diff_rows_in_duckdb(source_rows, target_rows)
    assert diffs == [{"P1": "2026-02", "CNT": "250"}]
