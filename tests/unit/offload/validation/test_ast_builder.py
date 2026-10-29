# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for CrossDbValidationBuilder."""

import pytest

from goe.exceptions import GOEError
from goe.offload.predicates.ast import (
    BinaryComparison,
    ColumnRef,
    LiteralValue,
    LogicalAnd,
    TypedValue,
)
from goe.offload.validation.ast_builder import (
    AggregateQuestion,
    CrossDbValidationBuilder,
)


def test_build_aggregate_batches_chunks_above_64() -> None:
    """Verify questions above max_aggregates are split into multiple batches."""
    builder = CrossDbValidationBuilder(dialect="oracle")
    questions = [AggregateQuestion(column=f"C{i}", func="MIN", alias=f"MIN_C{i}") for i in range(70)]
    batches = builder.build_aggregate_batches(
        schema="SH",
        table="SALES",
        questions=questions,
        group_bys=["P1"],
        as_of_scn=999111,
        parallelism=4,
    )
    assert len(batches) == 2
    assert len(batches[0].aliases) == 64
    assert len(batches[1].aliases) == 6
    assert "AS OF SCN :scn" in batches[0].sql
    assert "NO_INDEX(t) PARALLEL(t, 4)" in batches[0].sql
    assert batches[0].parameters == {"scn": 999111}
    assert 'GROUP BY "P1"' in batches[0].sql
    assert 'ORDER BY "P1" ASC' in batches[0].sql
    assert "NULLS LAST" in batches[0].sql

    bq_builder = CrossDbValidationBuilder(dialect="bigquery")
    bq_batches = bq_builder.build_aggregate_batches(
        schema="sh",
        table="sales",
        questions=questions[:2],
        group_bys=["P1"],
    )
    assert "ORDER BY `P1` ASC" in bq_batches[0].sql
    assert "NULLS LAST" in bq_batches[0].sql


def test_build_aggregate_batches_with_predicate_and_filter() -> None:
    """Verify PredicateExpr AST compiles into the validation WHERE clause."""
    builder = CrossDbValidationBuilder(dialect="oracle")
    pred = LogicalAnd(
        children=(
            BinaryComparison(
                op=">",
                column=ColumnRef(name="AMOUNT"),
                literal=LiteralValue(value=TypedValue(kind="integer", text="0"), data_type="NUMBER"),
            ),
            BinaryComparison(
                op="=",
                column=ColumnRef(name="STATUS"),
                literal=LiteralValue(value=TypedValue(kind="string", text="ACTIVE"), data_type="VARCHAR2"),
            ),
        )
    )
    batches = builder.build_aggregate_batches(
        schema="SH",
        table="SALES",
        questions=[AggregateQuestion(column=None, func="COUNT", alias="CNT")],
        predicate=pred,
    )
    assert len(batches) == 1
    assert 'WHERE ("AMOUNT" > 0 AND "STATUS" = \'ACTIVE\')' in batches[0].sql


def test_build_sample_hash_query_bigquery_and_oracle() -> None:
    """Verify sample hash query generation for BigQuery and Oracle."""
    bq_builder = CrossDbValidationBuilder(dialect="bigquery")
    bq_q = bq_builder.build_sample_hash_query(
        schema="ds",
        table="sales",
        key_columns=["ID"],
        value_columns=["AMOUNT", "NAME"],
        extra_where=("`ID` > 10",),
    )
    assert "BIT_XOR(FARM_FINGERPRINT(" in bq_q.sql
    assert "WHERE `ID` > 10" in bq_q.sql

    ora_builder = CrossDbValidationBuilder(dialect="oracle")
    ora_q = ora_builder.build_sample_hash_query(
        schema="SH",
        table="SALES",
        key_columns=["ID"],
        value_columns=["AMOUNT"],
        as_of_scn=12345,
    )
    assert "SUM(ORA_HASH(" in ora_q.sql
    assert "AS OF SCN :scn" in ora_q.sql
    assert ora_q.parameters == {"scn": 12345}


def test_parse_filter_clause_preserves_quotes_in_strings_and_rejects_unsafe() -> None:
    """Verify filter transpilation preserves double quotes inside string literals and rejects unsafe AST nodes."""
    builder = CrossDbValidationBuilder(dialect="bigquery")
    rendered = builder.parse_filter_clause('"COL_A" = 42 AND "COL_B" = \'quote"inside\'')
    assert rendered == "`COL_A` = 42 AND `COL_B` = 'quote\"inside'"

    with pytest.raises(GOEError, match="Unsafe"):
        builder.parse_filter_clause("1=1; DROP TABLE x")

    with pytest.raises(GOEError, match="Unsafe"):
        builder.parse_filter_clause("ID IN (SELECT id FROM secret)")
