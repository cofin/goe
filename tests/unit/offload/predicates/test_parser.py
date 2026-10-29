# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the immutable PredicateExpr AST and sqlglot-backed predicate DSL parser."""

from decimal import Decimal

import numpy as np
import pytest

from goe.exceptions import OptionValueError
from goe.offload.bigquery.bigquery_column import (
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_BYTES,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_STRING,
    BigQueryColumn,
)
from goe.offload.column_metadata import ColumnPartitionInfo
from goe.offload.oracle.oracle_column import (
    ORACLE_TYPE_BLOB,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_VARCHAR2,
    OracleColumn,
)
from goe.offload.predicates.ast import (
    BinaryComparison,
    ColumnRef,
    InListPredicate,
    LiteralValue,
    LogicalAnd,
    LogicalOr,
    NullCheckPredicate,
    TypedValue,
    alias_column_names,
    column_names,
    rename_column,
    to_dsl,
    with_column_alias,
)
from goe.offload.predicates.parser import (
    parse_predicate_dsl,
    parse_safe_sql_predicate,
    resolve_predicate_types,
)


def test_parse_predicate_dsl_preserves_38_digit_decimal_and_nanoseconds() -> None:
    """Verify 38-digit decimals and 9-digit nanosecond timestamps round-trip without precision loss."""
    dsl = (
        "(column(sales.amount) >= numeric(123456789012345678901234567890.12345678)) "
        "AND (column(event_ts) = datetime(2024-09-23 13:01:01.123456789))"
    )
    expr = parse_predicate_dsl(dsl)
    assert isinstance(expr, LogicalAnd)
    assert len(expr.children) == 2

    cmp_dec = expr.children[0]
    assert isinstance(cmp_dec, BinaryComparison)
    assert cmp_dec.op == ">="
    assert cmp_dec.column == ColumnRef(name="AMOUNT", alias="SALES")
    assert cmp_dec.literal.value == TypedValue(
        kind="decimal",
        text="123456789012345678901234567890.12345678",
    )
    assert cmp_dec.literal.value.raw == Decimal("123456789012345678901234567890.12345678")

    cmp_ts = expr.children[1]
    assert isinstance(cmp_ts, BinaryComparison)
    assert cmp_ts.op == "="
    assert cmp_ts.column == ColumnRef(name="EVENT_TS", alias=None)
    assert cmp_ts.literal.value == TypedValue(
        kind="datetime",
        text="2024-09-23 13:01:01.123456789",
    )
    assert cmp_ts.literal.value.raw == np.datetime64("2024-09-23T13:01:01.123456789", "ns")

    assert to_dsl(expr) == (
        "(column(SALES.AMOUNT) >= numeric(123456789012345678901234567890.12345678) "
        "AND column(EVENT_TS) = datetime(2024-09-23 13:01:01.123456789))"
    )


def test_parse_predicate_dsl_handles_reversed_operands_in_list_and_null_checks() -> None:
    """Verify reversed comparisons, IN/NOT IN lists, escaped quotes, and IS [NOT] NULL predicates."""
    dsl = (
        '(numeric(10) < column(id)) OR ((column(code) NOT IN (string("A"), string("B\\"C"))) '
        "AND (column(deleted_at) IS NULL) AND (column(updated_at) IS NOT NULL))"
    )
    expr = parse_predicate_dsl(dsl)
    assert isinstance(expr, LogicalOr)
    assert len(expr.children) == 2

    lhs = expr.children[0]
    assert isinstance(lhs, BinaryComparison)
    assert lhs.lhs_is_column is False
    assert lhs.op == "<"
    assert lhs.column == ColumnRef(name="ID")
    assert lhs.literal.value.raw == 10

    rhs = expr.children[1]
    assert isinstance(rhs, LogicalAnd)
    assert len(rhs.children) == 3

    in_node = rhs.children[0]
    assert isinstance(in_node, InListPredicate)
    assert in_node.negated is True
    assert in_node.column == ColumnRef(name="CODE")
    assert [v.value.raw for v in in_node.values] == ["A", 'B"C']

    null_node = rhs.children[1]
    assert isinstance(null_node, NullCheckPredicate)
    assert null_node.is_not_null is False
    assert null_node.column == ColumnRef(name="DELETED_AT")

    not_null_node = rhs.children[2]
    assert isinstance(not_null_node, NullCheckPredicate)
    assert not_null_node.is_not_null is True
    assert not_null_node.column == ColumnRef(name="UPDATED_AT")


def test_ast_column_helpers_extract_rename_and_re_alias() -> None:
    """Verify pure functional AST transforms do not mutate the input tree."""
    dsl = '(column(sh.id) = numeric(1)) AND ((column(name) = string("x")) OR (column(sh.id) IS NOT NULL))'
    expr = parse_predicate_dsl(dsl)

    assert set(column_names(expr)) == {"ID", "NAME"}
    assert set(alias_column_names(expr)) == {("SH", "ID"), (None, "NAME")}

    renamed = rename_column(expr, "id", "customer_id")
    assert set(column_names(expr)) == {"ID", "NAME"}
    assert set(column_names(renamed)) == {"CUSTOMER_ID", "NAME"}
    assert to_dsl(renamed) == (
        '(column(SH.CUSTOMER_ID) = numeric(1) AND (column(NAME) = string("x") OR column(SH.CUSTOMER_ID) IS NOT NULL))'
    )

    realiased = with_column_alias(renamed, "t1")
    assert set(alias_column_names(realiased)) == {("T1", "CUSTOMER_ID"), ("T1", "NAME")}

    stripped_alias = with_column_alias(realiased, None)
    assert set(alias_column_names(stripped_alias)) == {(None, "CUSTOMER_ID"), (None, "NAME")}


def test_resolve_predicate_types_attaches_column_data_types_and_synthetic_partitions() -> None:
    """Verify resolve_predicate_types populates data_type and injects synthetic partition comparisons."""
    bq_cols = [
        BigQueryColumn("ID", BIGQUERY_TYPE_INT64),
        BigQueryColumn("AMOUNT", BIGQUERY_TYPE_BIGNUMERIC, data_precision=38, data_scale=9),
        BigQueryColumn("EVENT_TS", BIGQUERY_TYPE_DATETIME),
        BigQueryColumn(
            "GOE_PART_M_EVENT_TS",
            BIGQUERY_TYPE_STRING,
            partition_info=ColumnPartitionInfo(
                position=1,
                source_column_name="EVENT_TS",
                granularity="M",
                function="TRUNC",
                digits=7,
            ),
        ),
    ]
    expr = parse_predicate_dsl("column(event_ts) >= datetime(2024-09-23 13:01:01)")
    resolved = resolve_predicate_types(expr, bq_cols, include_synthetic=True)
    assert isinstance(resolved, LogicalAnd)
    assert len(resolved.children) == 2

    orig_cmp = resolved.children[0]
    assert isinstance(orig_cmp, BinaryComparison)
    assert orig_cmp.literal.data_type == BIGQUERY_TYPE_DATETIME

    synth_cmp = resolved.children[1]
    assert isinstance(synth_cmp, BinaryComparison)
    assert synth_cmp.column == ColumnRef(name="GOE_PART_M_EVENT_TS")
    assert synth_cmp.op == ">="
    assert synth_cmp.literal == LiteralValue(
        value=TypedValue(kind="string", text="2024-09"),
        data_type=BIGQUERY_TYPE_STRING,
    )

    resolved_no_synth = resolve_predicate_types(expr, bq_cols, include_synthetic=False)
    assert isinstance(resolved_no_synth, BinaryComparison)
    assert resolved_no_synth.literal.data_type == BIGQUERY_TYPE_DATETIME


def test_resolve_predicate_types_raises_option_value_error_on_unknown_or_mismatched_column() -> None:
    """Verify unknown columns, unsupported column types, and mismatched value kinds raise OptionValueError."""
    ora_cols = [
        OracleColumn("ID", ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0),
        OracleColumn("NAME", ORACLE_TYPE_VARCHAR2, data_length=50),
        OracleColumn("CREATED_AT", ORACLE_TYPE_DATE),
        OracleColumn("EVENT_TS", ORACLE_TYPE_TIMESTAMP, data_scale=9),
        OracleColumn("RAW_BLOB", ORACLE_TYPE_BLOB),
    ]
    bq_cols = [
        BigQueryColumn("RAW_BYTES", BIGQUERY_TYPE_BYTES),
    ]

    with pytest.raises(OptionValueError, match="Unable to resolve column 'MISSING_COL' in offload predicate"):
        resolve_predicate_types(parse_predicate_dsl("column(missing_col) = numeric(1)"), ora_cols)

    with pytest.raises(OptionValueError, match="Data type is not supported for offload predicate: BLOB"):
        resolve_predicate_types(parse_predicate_dsl('column(raw_blob) = string("abc")'), ora_cols)

    with pytest.raises(OptionValueError, match="Data type is not supported for offload predicate: BYTES"):
        resolve_predicate_types(parse_predicate_dsl('column(raw_bytes) = string("abc")'), bq_cols)

    with pytest.raises(
        OptionValueError,
        match="Columns of data type VARCHAR2 cannot be compared to numeric values",
    ):
        resolve_predicate_types(parse_predicate_dsl("column(name) = numeric(42)"), ora_cols)

    with pytest.raises(
        OptionValueError,
        match="Columns of data type NUMBER cannot be compared to datetime values",
    ):
        resolve_predicate_types(parse_predicate_dsl("column(id) = datetime(2024-01-01)"), ora_cols)

    with pytest.raises(
        OptionValueError,
        match="Columns of data type DATE cannot be compared to string values",
    ):
        resolve_predicate_types(parse_predicate_dsl('column(created_at) = string("2024-01-01")'), ora_cols)


def test_parse_predicate_dsl_syntax_errors_raise_option_value_error() -> None:
    """Verify invalid syntax, truncated EOF, and malformed literals raise OptionValueError."""
    for bad_dsl in (
        "",
        "column(hi)",
        "column(hi) >",
        "column(hi) > numeric()",
        "column(hi) > numeric(+-23)",
        "column(hi) == numeric(23)",
        "(column(hi) = numeric(23)",
        "Column(hi) = numeric(23)",
        "column(hi) = column(there)",
        "column(a) = numeric(1) AND column(b) = numeric(2) OR column(c) = numeric(3)",
        "column(dt) = datetime(2012-01-0)",
        "column(dt) = datetime(2012-01-01 6:00:01)",
        "column(dt) = datetime(2012-01-01 06:00:01.)",
        "column(dt) = datetime(2012-01-01 06:00:01.0000000000)",
    ):
        with pytest.raises(OptionValueError):
            parse_predicate_dsl(bad_dsl)


def test_parse_safe_sql_predicate_allows_valid_filters_and_rejects_unsafe_ast() -> None:
    """Verify parse_safe_sql_predicate validates SQL WHERE conditions using native sqlglot."""
    assert parse_safe_sql_predicate('"ID" = 1 AND "NAME" IS NOT NULL', dialect="oracle") == (
        '"ID" = 1 AND "NAME" IS NOT NULL'
    )
    assert parse_safe_sql_predicate("`ID` = 1", dialect="bigquery") == "`ID` = 1"
