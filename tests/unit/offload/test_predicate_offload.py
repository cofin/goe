# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Offload predicate test code."""

import ast
from decimal import Decimal
from pathlib import Path
from unittest import TestCase, main

import numpy as np

from goe.exceptions import OptionValueError
from goe.offload import predicate_offload
from goe.offload.bigquery import bigquery_predicate
from goe.offload.hadoop import hadoop_predicate
from goe.offload.microsoft import synapse_predicate
from goe.offload.oracle import oracle_predicate
from goe.offload.predicate_offload import (
    GenericPredicate,
    PredicateOffloadException,
    get_predicate_dialect_engine,
    parse_predicate_dsl,
)
from goe.offload.predicates.ast import BinaryComparison, TypedValue
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    HADOOP_TYPE_DECIMAL,
    HADOOP_TYPE_INT,
    HADOOP_TYPE_STRING,
    HADOOP_TYPE_TIMESTAMP,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_VARCHAR2,
    SNOWFLAKE_TYPE_NUMBER,
    SNOWFLAKE_TYPE_TEXT,
    SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
    SYNAPSE_TYPE_BIGINT,
    SYNAPSE_TYPE_DATETIME2,
    SYNAPSE_TYPE_DECIMAL,
    SYNAPSE_TYPE_VARCHAR,
    ColumnDialect,
    ColumnSpec,
)
from goe.offload.snowflake import snowflake_predicate
from goe.offload.sql_engine import PredicateDialectEngineProtocol

BIGQUERY_COLUMNS = [
    ColumnSpec(ColumnDialect.BIGQUERY, "COL_INT", BIGQUERY_TYPE_INT64),
    ColumnSpec(ColumnDialect.BIGQUERY, "COL_STRING", BIGQUERY_TYPE_STRING),
    ColumnSpec(ColumnDialect.BIGQUERY, "COL_DATE", BIGQUERY_TYPE_DATETIME),
    ColumnSpec(
        ColumnDialect.BIGQUERY,
        "COL_DECIMAL",
        BIGQUERY_TYPE_NUMERIC,
        data_precision=10,
        data_scale=2,
    ),
]
HADOOP_COLUMNS = [
    ColumnSpec(ColumnDialect.HADOOP, "COL_INT", HADOOP_TYPE_INT),
    ColumnSpec(ColumnDialect.HADOOP, "COL_STRING", HADOOP_TYPE_STRING),
    ColumnSpec(ColumnDialect.HADOOP, "COL_DATE", HADOOP_TYPE_TIMESTAMP),
    ColumnSpec(
        ColumnDialect.HADOOP,
        "COL_DECIMAL",
        HADOOP_TYPE_DECIMAL,
        data_precision=10,
        data_scale=2,
    ),
]
ORACLE_COLUMNS = [
    ColumnSpec(ColumnDialect.ORACLE, "COL_INT", ORACLE_TYPE_NUMBER, data_precision=5, data_scale=0),
    ColumnSpec(ColumnDialect.ORACLE, "COL_STRING", ORACLE_TYPE_VARCHAR2),
    ColumnSpec(ColumnDialect.ORACLE, "COL_DATE", ORACLE_TYPE_DATE),
    ColumnSpec(ColumnDialect.ORACLE, "COL_DECIMAL", ORACLE_TYPE_NUMBER, data_precision=10, data_scale=2),
]
SNOWFLAKE_COLUMNS = [
    ColumnSpec(
        ColumnDialect.SNOWFLAKE,
        "COL_INT",
        SNOWFLAKE_TYPE_NUMBER,
        data_precision=5,
        data_scale=0,
    ),
    ColumnSpec(ColumnDialect.SNOWFLAKE, "COL_STRING", SNOWFLAKE_TYPE_TEXT),
    ColumnSpec(ColumnDialect.SNOWFLAKE, "COL_DATE", SNOWFLAKE_TYPE_TIMESTAMP_NTZ),
    ColumnSpec(
        ColumnDialect.SNOWFLAKE,
        "COL_DECIMAL",
        SNOWFLAKE_TYPE_NUMBER,
        data_precision=10,
        data_scale=2,
    ),
]
SYNAPSE_COLUMNS = [
    ColumnSpec(ColumnDialect.SYNAPSE, "COL_INT", SYNAPSE_TYPE_BIGINT),
    ColumnSpec(ColumnDialect.SYNAPSE, "COL_STRING", SYNAPSE_TYPE_VARCHAR),
    ColumnSpec(ColumnDialect.SYNAPSE, "COL_DATE", SYNAPSE_TYPE_DATETIME2),
    ColumnSpec(
        ColumnDialect.SYNAPSE,
        "COL_DECIMAL",
        SYNAPSE_TYPE_DECIMAL,
        data_precision=10,
        data_scale=2,
    ),
]


class TestIdaPredicateParse(TestCase):
    def test_parse_numeric(self):
        self._test_parse_single_numeric("3.141", ("decimal", Decimal("3.141")))
        self._test_parse_single_numeric("+3.141", ("decimal", Decimal("3.141")))
        self._test_parse_single_numeric("-3.141", ("decimal", Decimal("-3.141")))
        self._test_parse_single_numeric(" 3.141", ("decimal", Decimal("3.141")))
        self._test_parse_single_numeric(" 3.141 ", ("decimal", Decimal("3.141")))
        self._test_parse_single_numeric("3.", ("decimal", Decimal("3.0")))

        self._test_parse_single_numeric("3", ("integer", 3))
        self._test_parse_single_numeric("+3", ("integer", 3))
        self._test_parse_single_numeric("-3", ("integer", -3))

        self._test_parse_single_numeric(" 3", ("integer", 3))
        self._test_parse_single_numeric("3 ", ("integer", 3))
        self._test_parse_single_numeric(" 3 ", ("integer", 3))

    def test_parse_datetime(self):
        self._test_parse_single_datetime("2012-01-01", np.datetime64("2012-01-01"))
        self.assertRaises(OptionValueError, self._test_parse_single_datetime, "2012-01-0", None)
        self.assertRaises(OptionValueError, self._test_parse_single_datetime, "2012-0101", None)
        self.assertRaises(OptionValueError, self._test_parse_single_datetime, "", None)

        self._test_parse_single_datetime("2001-01-01 12:00:01", np.datetime64("2001-01-01 12:00:01"))
        self._test_parse_single_datetime("2001-01-01 06:00:01", np.datetime64("2001-01-01 06:00:01"))
        self.assertRaises(
            OptionValueError,
            self._test_parse_single_datetime,
            "2012-01-01 6:00:01",
            np.datetime64("2012-01-01 06:00:01"),
        )

        self._test_parse_single_datetime(
            "2001-01-01 12:00:01.050",
            np.datetime64("2001-01-01 12:00:01.050"),
        )
        self._test_parse_single_datetime(
            "2001-01-01 06:00:01.000090",
            np.datetime64("2001-01-01 06:00:01.000090"),
        )
        self._test_parse_single_datetime(
            "2001-01-01 06:00:01.000000123",
            np.datetime64("2001-01-01 06:00:01.000000123"),
        )
        self.assertRaises(
            OptionValueError,
            self._test_parse_single_datetime,
            "2012-01-01 06:00:01.",
            np.datetime64("2012-01-01 06:00:01.000"),
        )
        self.assertRaises(
            OptionValueError,
            self._test_parse_single_datetime,
            "2012-01-01 06:00:01.0000000000",
            np.datetime64("2012-01-01 06:00:01.000"),
        )

    def test_parse_string(self):
        self._test_parse_single_string("test string")
        self._test_parse_single_string("test' string")
        self._test_parse_single_string('test \\" string')
        self._test_parse_single_string("")
        self._test_parse_single_string("`~!@#$%^&*()_+-={}[]|:;?/>.<,0987654321")
        self._test_parse_single_string("\u00f6")

    def test_column_names(self):
        expect_col_names = [
            ("column(baz) = numeric(1)", ["BAZ"]),
            ("column(sh.baz) = numeric(1)", ["BAZ"]),
            ("(column(baz) = numeric(1)) and (column(baz) != numeric(1))", ["BAZ"]),
            (
                "(column(baz) = numeric(1)) and (column(bar) != numeric(1))",
                ["BAR", "BAZ"],
            ),
            (
                '(column(baz) = numeric(1)) and ((column(zip) = string("hey")) or (column(bar) != numeric(1)))',
                ["BAR", "BAZ", "ZIP"],
            ),
            ("column(_baz_123) = numeric(1)", ["_BAZ_123"]),
        ]
        for dsl, col_names in expect_col_names:
            self.assertEqual(set(GenericPredicate(dsl).column_names()), set(col_names))

    def test_parse_errors(self):
        self.assertRaises(OptionValueError, parse_predicate_dsl, "")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "column(hi)")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "column(hi) >")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "column(hi) > numeric()")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "column(hi) > numeric(+-23)")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "column(hi) == numeric(23)")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "(column(hi) = numeric(23)")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "Column(hi) = numeric(23)")
        self.assertRaises(OptionValueError, parse_predicate_dsl, "column(hi) = column(there)")

    def test_parse_complex_dsl(self):
        parse_dsl = [
            "column(YEAR) < numeric(2012) OR (column(YEAR) = numeric(2012) AND column(MONTH) < numeric(6))",
            "(column(YEAR) < numeric(2012) OR (column(YEAR) = numeric(2012) AND column(MONTH) < numeric(6)))",
            "((column(YEAR) < numeric(2012)) OR ((column(YEAR) = numeric(2012)) AND (column(MONTH) < numeric(6))))",
            "(((column(YEAR) < numeric(2012)) "
            "OR ((column(YEAR) = numeric(2012)) AND (column(MONTH) < numeric(6)))) "
            "OR (((column(YEAR) = numeric(2012)) AND (column(MONTH) = numeric(6))) AND (column(DAY) < numeric(30))))",
        ]

        for predicate_dsl in parse_dsl:
            GenericPredicate(predicate_dsl)

    def _test_parse_single_numeric(self, dsl_value_str, expected_kind_and_raw):
        expected_kind, expected_raw = expected_kind_and_raw
        expr = parse_predicate_dsl(f"column(c) = numeric({dsl_value_str})")
        self.assertIsInstance(expr, BinaryComparison)
        self.assertEqual(expr.literal.value.kind, expected_kind)
        self.assertEqual(expr.literal.value.raw, expected_raw)

    def _test_parse_single_datetime(self, dsl_value_str, expected_raw):
        expr = parse_predicate_dsl(f"column(c) = datetime({dsl_value_str})")
        self.assertIsInstance(expr, BinaryComparison)
        self.assertEqual(expr.literal.value.kind, "datetime")
        self.assertEqual(expr.literal.value.raw, expected_raw)

    def _test_parse_single_string(self, dsl_value_str, ast_value_str=None):
        ast_value_str = dsl_value_str if ast_value_str is None else ast_value_str
        expr = parse_predicate_dsl(f'column(c) = string("{dsl_value_str}")')
        self.assertIsInstance(expr, BinaryComparison)
        self.assertEqual(
            expr.literal.value,
            TypedValue(kind="string", text=ast_value_str.replace('\\"', '"')),
        )


class TestIdaPredicateMethods(TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def test_rename_column(self):
        pred = GenericPredicate("column(original_name) IS NOT NULL")
        self.assertEqual(pred.column_names(), ["ORIGINAL_NAME"])
        pred.rename_column("original_name", "new_name")
        self.assertEqual(pred.column_names(), ["NEW_NAME"])
        self.assertEqual(pred.dsl, "column(NEW_NAME) IS NOT NULL")

        pred = GenericPredicate("column(original_name) = numeric(3)")
        self.assertEqual(pred.column_names(), ["ORIGINAL_NAME"])
        pred.rename_column("original_name", "new_name")
        self.assertEqual(pred.column_names(), ["NEW_NAME"])
        self.assertEqual(pred.dsl, "column(NEW_NAME) = numeric(3)")

        dsl = "((column(original_name) = numeric(3) AND column(original_name) != datetime(2001-01-01)) OR (column(new_name) IN (numeric(7)) OR column(other_name) NOT IN (numeric(12))))"
        pred = GenericPredicate(dsl)
        self.assertEqual(set(pred.column_names()), set(["ORIGINAL_NAME", "NEW_NAME", "OTHER_NAME"]))
        pred.rename_column("original_name", "new_name")
        self.assertEqual(set(pred.column_names()), set(["NEW_NAME", "OTHER_NAME"]))
        self.assertEqual(
            pred.ast,
            GenericPredicate(pred.dsl.replace("ORIGINAL_NAME", "NEW_NAME")).ast,
        )
        self.assertEqual(
            pred.dsl,
            dsl.replace("original_name", "NEW_NAME")
            .replace("new_name", "NEW_NAME")
            .replace("other_name", "OTHER_NAME"),
        )

    def test_set_column_alias(self):
        pred = GenericPredicate("column(col) = numeric(1)")
        pred.set_column_alias("test_alias")
        self.assertEqual(pred.column_names(), ["COL"])
        self.assertEqual(pred.alias_column_names(), [("TEST_ALIAS", "COL")])

        pred = GenericPredicate("column(alias.col) = numeric(1)")
        self.assertEqual(pred.alias_column_names(), [("ALIAS", "COL")])
        pred.set_column_alias("test_alias")
        self.assertEqual(pred.alias_column_names(), [("TEST_ALIAS", "COL")])

        pred = GenericPredicate("column(alias.col) IS NULL")
        self.assertEqual(pred.alias_column_names(), [("ALIAS", "COL")])
        pred.set_column_alias("test_alias")
        self.assertEqual(pred.alias_column_names(), [("TEST_ALIAS", "COL")])

        pred = GenericPredicate("column(alias.col) = numeric(1)")
        self.assertEqual(pred.alias_column_names(), [("ALIAS", "COL")])
        pred.set_column_alias(None)
        self.assertEqual(pred.alias_column_names(), [(None, "COL")])


class TestIdaPredicateRenderToDSL(TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def test_render_dsl(self):
        expect_dsl = [
            ("column(col) = numeric(1)", "column(COL) = numeric(1)"),
            ("column(col) = numeric(1.1)", "column(COL) = numeric(1.1)"),
            (
                'column(alias.column) IN (string("hi there"))',
                'column(ALIAS.COLUMN) IN (string("hi there"))',
            ),
            (
                'column(COLUMN) IN (string("1"), string("2"))',
                'column(COLUMN) IN (string("1"), string("2"))',
            ),
            (
                '(column(c1) not in (numeric(1))) and ((column(c2) <= string("c2")) or (column(c3) IS NOT NULL))',
                '(column(C1) NOT IN (numeric(1)) AND (column(C2) <= string("c2") OR column(C3) IS NOT NULL))',
            ),
        ]
        for input_dsl, render_dsl in expect_dsl:
            self.assertEqual(GenericPredicate(input_dsl).dsl, render_dsl)


class TestIdaPredicateDataTypes(TestCase):
    def test_data_type_errors(self):
        expect_data_type_error = [
            "column(COL_STRING) = numeric(34)",
            "column(COL_STRING) = datetime(2012-01-01)",
            "column(COL_STRING) = datetime(2012-01-01 00:00:00.123456789)",
            "column(COL_STRING) IN (numeric(34))",
            "column(COL_STRING) NOT IN (numeric(34))",
            'column(COL_STRING) IN (string("NYC"), numeric(34))',
            "numeric(34) > column(COL_STRING)",
            "column(COL_INT) = datetime(2020-12-30)",
            'column(COL_INT) = string("2020-12-30")',
            'column(COL_DECIMAL) < string("nan")',
            "column(COL_DATE) = numeric(34)",
            'column(COL_DATE) = string("34")',
        ]

        for predicate_dsl in expect_data_type_error:
            self.assertRaisesRegex(
                OptionValueError,
                "cannot be compared to",
                oracle_predicate.predicate_to_where_clause,
                ORACLE_COLUMNS,
                GenericPredicate(predicate_dsl),
            )
            self.assertRaisesRegex(
                OptionValueError,
                "cannot be compared to",
                hadoop_predicate.predicate_to_where_clause,
                HADOOP_COLUMNS,
                GenericPredicate(predicate_dsl),
            )
            self.assertRaisesRegex(
                OptionValueError,
                "cannot be compared to",
                bigquery_predicate.predicate_to_where_clause,
                BIGQUERY_COLUMNS,
                GenericPredicate(predicate_dsl),
            )
            self.assertRaisesRegex(
                OptionValueError,
                "cannot be compared to",
                snowflake_predicate.predicate_to_where_clause,
                SNOWFLAKE_COLUMNS,
                GenericPredicate(predicate_dsl),
            )
            self.assertRaisesRegex(
                OptionValueError,
                "cannot be compared to",
                synapse_predicate.predicate_to_where_clause,
                SYNAPSE_COLUMNS,
                GenericPredicate(predicate_dsl),
            )


def test_predicate_modules_have_zero_lark_or_sqlglot_imports() -> None:
    """Verify predicate_offload and dialect predicate modules do not import lark or sqlglot."""
    dialect_mods = (
        oracle_predicate,
        bigquery_predicate,
        snowflake_predicate,
        synapse_predicate,
        hadoop_predicate,
    )
    for mod in (predicate_offload, *dialect_mods):
        assert mod.__file__ is not None
        source = Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.append(node.module)
        assert not any("lark" in name for name in imported_names)
        assert not any("sqlglot" in name for name in imported_names)


def test_multi_dialect_predicate_sql_and_bind_rendering_with_nanoseconds() -> None:
    """Verify Oracle, BigQuery, Snowflake, Synapse, and Hadoop predicate rendering."""
    engine = get_predicate_dialect_engine("oracle")
    bq_engine = get_predicate_dialect_engine("bigquery")
    assert isinstance(engine, PredicateDialectEngineProtocol)
    assert isinstance(bq_engine, PredicateDialectEngineProtocol)

    cols = ORACLE_COLUMNS + [
        ColumnSpec(ColumnDialect.ORACLE, "COL_TS", ORACLE_TYPE_TIMESTAMP, data_scale=9),
    ]
    pred_ts = GenericPredicate("column(COL_TS) = datetime(2011-01-01 05:06:07.123456789)")
    assert (
        oracle_predicate.predicate_to_where_clause(cols, pred_ts)
        == "\"COL_TS\" = TIMESTAMP '2011-01-01 05:06:07.123456789'"
    )
    bind_sql, binds = oracle_predicate.predicate_to_where_clause_with_binds(cols, pred_ts)
    assert bind_sql == "\"COL_TS\" = TO_TIMESTAMP(:bind_0, 'YYYY-MM-DD HH24:MI:SS.FF9')"
    assert binds == {"bind_0": "2011-01-01 05:06:07.123456789"}

    pred_date = GenericPredicate("column(COL_DATE) = datetime(2011-01-01)")
    assert (
        oracle_predicate.predicate_to_where_clause(cols, pred_date)
        == "\"COL_DATE\" = TO_DATE('2011-01-01 00:00:00', 'YYYY-MM-DD HH24:MI:SS')"
    )
    date_bind_sql, date_binds = oracle_predicate.predicate_to_where_clause_with_binds(cols, pred_date)
    assert date_bind_sql == "\"COL_DATE\" = TO_DATE(:bind_0, 'YYYY-MM-DD HH24:MI:SS')"
    assert date_binds == {"bind_0": "2011-01-01 00:00:00"}

    pred_dec = GenericPredicate("column(COL_DECIMAL) = numeric(-0.00000000000000000001)")
    assert oracle_predicate.predicate_to_where_clause(cols, pred_dec) == '"COL_DECIMAL" = -0.00000000000000000001'

    pred_38_dec = GenericPredicate("column(COL_DECIMAL) = numeric(123456789012345678901234567890.12345678)")
    assert (
        oracle_predicate.predicate_to_where_clause(cols, pred_38_dec)
        == '"COL_DECIMAL" = 123456789012345678901234567890.12345678'
    )

    pred_big_int = GenericPredicate("column(COL_INT) = numeric(1234567890123456789012345)")
    assert oracle_predicate.predicate_to_where_clause(cols, pred_big_int) == '"COL_INT" = 1234567890123456789012345'

    pred_not_in = GenericPredicate('column(COL_STRING) NOT IN (string("A"), string("B"))')
    assert oracle_predicate.predicate_to_where_clause(cols, pred_not_in) == "\"COL_STRING\" NOT IN ('A', 'B')"

    pred_neq = GenericPredicate('column(COL_STRING) != string("A")')
    assert oracle_predicate.predicate_to_where_clause(cols, pred_neq) == "\"COL_STRING\" != 'A'"

    pred_nulls = GenericPredicate("(column(COL_INT) IS NULL) AND (column(COL_INT) IS NOT NULL)")
    assert (
        oracle_predicate.predicate_to_where_clause(cols, pred_nulls) == '("COL_INT" IS NULL AND "COL_INT" IS NOT NULL)'
    )

    pred_lit = GenericPredicate(
        "column(COL_DATE) < literal(\"TO_DATE(' 2012-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')\")"
    )
    assert (
        oracle_predicate.predicate_to_where_clause(cols, pred_lit)
        == "\"COL_DATE\" < TO_DATE(' 2012-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')"
    )

    bq_dt = GenericPredicate("column(COL_DATE) = datetime(1970-01-01 12:13:14)")
    assert (
        bigquery_predicate.predicate_to_where_clause(BIGQUERY_COLUMNS, bq_dt)
        == "`COL_DATE` = DATETIME '1970-01-01 12:13:14'"
    )
    bq_not_in = GenericPredicate('column(COL_STRING) NOT IN (string("A"), string("B"))')
    assert bigquery_predicate.predicate_to_where_clause(BIGQUERY_COLUMNS, bq_not_in) == "`COL_STRING` NOT IN ('A', 'B')"
    bq_neq = GenericPredicate("column(COL_INT) != numeric(4)")
    assert bigquery_predicate.predicate_to_where_clause(BIGQUERY_COLUMNS, bq_neq) == "`COL_INT` != 4"
    bq_bind_sql, bq_binds = bigquery_predicate.predicate_to_where_clause_with_binds(BIGQUERY_COLUMNS, bq_neq)
    assert bq_bind_sql == "`COL_INT` != @bind_0"
    assert bq_binds == {"bind_0": 4}

    assert (
        snowflake_predicate.predicate_to_where_clause(SNOWFLAKE_COLUMNS, bq_dt)
        == "\"COL_DATE\" = '1970-01-01 12:13:14'::TIMESTAMP_NTZ"
    )
    assert synapse_predicate.predicate_to_where_clause(SYNAPSE_COLUMNS, bq_dt) == "[COL_DATE] = '1970-01-01 12:13:14'"
    assert hadoop_predicate.predicate_to_where_clause(HADOOP_COLUMNS, bq_dt) == "COL_DATE = '1970-01-01 12:13:14'"
    hadoop_bind_sql, hadoop_binds = hadoop_predicate.predicate_to_where_clause_with_binds(HADOOP_COLUMNS, bq_dt)
    assert hadoop_bind_sql == "COL_DATE = :bind_0"
    assert hadoop_binds == {"bind_0": np.datetime64("1970-01-01T12:13:14")}

    assert (
        engine.validate_where_clause(
            "\"COL_TS\" = TIMESTAMP '2011-01-01 05:06:07.123456789' AND \"COL_DATE\" < TO_DATE(' 2012-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')",
            "oracle",
        )
        != ""
    )
    assert bq_engine.validate_where_clause("`COL_DATE` = DATETIME '1970-01-01 12:13:14'", "bigquery") != ""

    for bad_sql in (
        "ID = 1 OR (SELECT COUNT(*) FROM user_tables) > 0",
        "EXISTS (SELECT 1 FROM dual)",
        "ID = 1; DROP TABLE sales",
        "DBMS_LOCK.SLEEP(5) = 0",
    ):
        try:
            engine.validate_where_clause(bad_sql, "oracle")
            raise AssertionError(f"Expected PredicateOffloadException for {bad_sql}")
        except PredicateOffloadException:
            pass


if __name__ == "__main__":
    main()
