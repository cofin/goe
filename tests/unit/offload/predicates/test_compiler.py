# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the multi-dialect PredicateCompiler and render_predicate."""

from decimal import Decimal

import numpy as np
from sqlglot import exp

from goe.offload.bigquery.bigquery_column import (
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_DATETIME,
    BigQueryColumn,
)
from goe.offload.hadoop.hadoop_column import (
    HADOOP_TYPE_DECIMAL,
    HADOOP_TYPE_INT,
    HADOOP_TYPE_STRING,
    HADOOP_TYPE_TIMESTAMP,
    HadoopColumn,
)
from goe.offload.microsoft.synapse_column import (
    SYNAPSE_TYPE_BIGINT,
    SYNAPSE_TYPE_DATETIME2,
    SYNAPSE_TYPE_DECIMAL,
    SYNAPSE_TYPE_VARCHAR,
    SynapseColumn,
)
from goe.offload.oracle.oracle_column import (
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_TIMESTAMP,
    OracleColumn,
)
from goe.offload.predicates.compiler import (
    PredicateCompiler,
    render_predicate,
)
from goe.offload.predicates.parser import (
    parse_predicate_dsl,
    resolve_predicate_types,
)
from goe.offload.snowflake.snowflake_column import (
    SNOWFLAKE_TYPE_NUMBER,
    SNOWFLAKE_TYPE_TEXT,
    SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
    SnowflakeColumn,
)


def test_oracle_literal_and_bind_compilation() -> None:
    """Verify Oracle literal and bind compilation for NUMBER, DATE, and TIMESTAMP(9) columns."""
    ora_cols = [
        OracleColumn("PROD_ID", ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0),
        OracleColumn("TIME_ID", ORACLE_TYPE_DATE),
        OracleColumn("EVENT_TS", ORACLE_TYPE_TIMESTAMP, data_scale=9),
    ]
    dsl = "(column(SH.PROD_ID) = numeric(42)) AND (column(SH.TIME_ID) >= datetime(2024-01-15 08:30:00))"
    resolved = resolve_predicate_types(parse_predicate_dsl(dsl), ora_cols)

    lit_res = render_predicate(resolved, "oracle", bind_style=None)
    assert lit_res.sql == (
        '("SH"."PROD_ID" = 42 AND "SH"."TIME_ID" >= TO_DATE(\'2024-01-15 08:30:00\', \'YYYY-MM-DD HH24:MI:SS\'))'
    )
    assert lit_res.params == {}

    bind_res = render_predicate(resolved, "oracle", bind_style="named_colon")
    assert bind_res.sql == (
        '("SH"."PROD_ID" = :bind_0 AND "SH"."TIME_ID" >= TO_DATE(:bind_1, \'YYYY-MM-DD HH24:MI:SS\'))'
    )
    assert bind_res.params == {"bind_0": 42, "bind_1": "2024-01-15 08:30:00"}

    ts_resolved = resolve_predicate_types(
        parse_predicate_dsl("column(EVENT_TS) = datetime(2024-01-15 08:30:00.123456789)"),
        ora_cols,
    )
    assert render_predicate(ts_resolved, "oracle").sql == "\"EVENT_TS\" = TIMESTAMP '2024-01-15 08:30:00.123456789'"
    ts_bind = render_predicate(ts_resolved, "oracle", bind_style="named_colon")
    assert ts_bind.sql == "\"EVENT_TS\" = TO_TIMESTAMP(:bind_0, 'YYYY-MM-DD HH24:MI:SS.FF9')"
    assert ts_bind.params == {"bind_0": "2024-01-15 08:30:00.123456789"}


def test_bigquery_literal_and_bind_compilation_with_38_digit_bignumeric() -> None:
    """Verify BigQuery literal and bind compilation preserves 38-digit BIGNUMERIC precision."""
    bq_cols = [
        BigQueryColumn("AMOUNT", BIGQUERY_TYPE_BIGNUMERIC, data_precision=38, data_scale=9),
        BigQueryColumn("CREATED_AT", BIGQUERY_TYPE_DATETIME),
    ]
    dsl = (
        "(column(AMOUNT) >= numeric(123456789012345678901234567890.12345678)) "
        "AND (column(CREATED_AT) = datetime(2024-09-23 13:01:01))"
    )
    resolved = resolve_predicate_types(parse_predicate_dsl(dsl), bq_cols)

    lit_res = render_predicate(resolved, "bigquery", bind_style=None)
    assert lit_res.sql == (
        "(`AMOUNT` >= BIGNUMERIC '123456789012345678901234567890.12345678' "
        "AND `CREATED_AT` = DATETIME '2024-09-23 13:01:01')"
    )
    assert lit_res.params == {}

    bind_res = render_predicate(resolved, "bigquery", bind_style="named_at")
    assert bind_res.sql == "(`AMOUNT` >= @bind_0 AND `CREATED_AT` = @bind_1)"
    assert bind_res.params == {
        "bind_0": Decimal("123456789012345678901234567890.12345678"),
        "bind_1": "2024-09-23 13:01:01",
    }


def test_snowflake_tsql_hive_spark_and_duckdb_compilation() -> None:
    """Verify Snowflake, T-SQL, Hive, Spark, and DuckDB literal and bind compilation."""
    sf_cols = [
        SnowflakeColumn("COL_INT", SNOWFLAKE_TYPE_NUMBER, data_precision=10, data_scale=0),
        SnowflakeColumn("COL_DEC", SNOWFLAKE_TYPE_NUMBER, data_precision=10, data_scale=2),
        SnowflakeColumn("COL_STR", SNOWFLAKE_TYPE_TEXT),
        SnowflakeColumn("COL_DT", SNOWFLAKE_TYPE_TIMESTAMP_NTZ),
    ]
    sf_dsl = (
        "(column(COL_DEC) = numeric(2.2)) AND (column(COL_DT) = datetime(1970-01-01 12:13:14)) "
        'AND (column(COL_STR) NOT IN (string("A"), string("B"))) AND (column(COL_INT) IS NOT NULL)'
    )
    sf_resolved = resolve_predicate_types(parse_predicate_dsl(sf_dsl), sf_cols)
    assert render_predicate(sf_resolved, "snowflake").sql == (
        '("COL_DEC" = 2.2 AND "COL_DT" = \'1970-01-01 12:13:14\'::TIMESTAMP_NTZ '
        "AND \"COL_STR\" NOT IN ('A', 'B') AND \"COL_INT\" IS NOT NULL)"
    )
    sf_bind = render_predicate(sf_resolved, "snowflake", bind_style="pyformat")
    assert "%(bind_0)s" in sf_bind.sql
    assert sf_bind.params["bind_0"] == Decimal("2.2")

    tsql_cols = [
        SynapseColumn("COL_INT", SYNAPSE_TYPE_BIGINT),
        SynapseColumn("COL_DEC", SYNAPSE_TYPE_DECIMAL, data_precision=10, data_scale=2),
        SynapseColumn("COL_STR", SYNAPSE_TYPE_VARCHAR),
        SynapseColumn("COL_DT", SYNAPSE_TYPE_DATETIME2),
    ]
    tsql_resolved = resolve_predicate_types(
        parse_predicate_dsl("(column(COL_DEC) = numeric(2.2)) AND (column(COL_DT) = datetime(1970-01-01 12:13:14))"),
        tsql_cols,
    )
    assert render_predicate(tsql_resolved, "tsql").sql == "([COL_DEC] = 2.2 AND [COL_DT] = '1970-01-01 12:13:14')"
    tsql_bind = render_predicate(tsql_resolved, "tsql", bind_style="named_colon")
    assert tsql_bind.sql == "([COL_DEC] = :bind_0 AND [COL_DT] = :bind_1)"
    assert tsql_bind.params == {"bind_0": Decimal("2.2"), "bind_1": "1970-01-01 12:13:14"}

    hadoop_cols = [
        HadoopColumn("COL_INT", HADOOP_TYPE_INT),
        HadoopColumn("COL_DEC", HADOOP_TYPE_DECIMAL, data_precision=10, data_scale=2),
        HadoopColumn("COL_STR", HADOOP_TYPE_STRING),
        HadoopColumn("COL_DT", HADOOP_TYPE_TIMESTAMP),
    ]
    hadoop_resolved = resolve_predicate_types(
        parse_predicate_dsl("(column(COL_DEC) = numeric(2.2)) AND (column(COL_DT) = datetime(2010-01-01))"),
        hadoop_cols,
    )
    assert (
        render_predicate(hadoop_resolved, "hive", quote_identifiers=False).sql
        == "(COL_DEC = 2.2 AND COL_DT = '2010-01-01')"
    )
    assert (
        render_predicate(hadoop_resolved, "spark", quote_identifiers=True).sql
        == "(`COL_DEC` = 2.2 AND `COL_DT` = '2010-01-01')"
    )
    hive_bind = render_predicate(
        hadoop_resolved,
        "hive",
        bind_style="named_colon",
        quote_identifiers=False,
    )
    assert hive_bind.sql == "(COL_DEC = :bind_0 AND COL_DT = :bind_1)"
    assert hive_bind.params == {"bind_0": Decimal("2.2"), "bind_1": np.datetime64("2010-01-01")}

    duck_res = render_predicate(hadoop_resolved, "duckdb")
    assert duck_res.sql == '("COL_DEC" = 2.2 AND "COL_DT" = TIMESTAMP \'2010-01-01\')'
    duck_bind = render_predicate(hadoop_resolved, "duckdb", bind_style="dollar")
    assert duck_bind.sql == '("COL_DEC" = $bind_0 AND "COL_DT" = $bind_1)'
    assert duck_bind.params == {"bind_0": Decimal("2.2"), "bind_1": "2010-01-01"}


def test_to_sqlglot_returns_ast_expression_without_mutation() -> None:
    """Verify PredicateCompiler.to_sqlglot returns a sqlglot AST expression and memoizes repeated calls."""
    expr = parse_predicate_dsl("(column(ID) != numeric(10)) AND (column(STATUS) IS NULL)")
    ast_node_1, params_1 = PredicateCompiler.to_sqlglot(expr, "bigquery")
    ast_node_2, params_2 = PredicateCompiler.to_sqlglot(expr, "bigquery")
    assert isinstance(ast_node_1, exp.Expr)
    assert ast_node_1.sql("bigquery") == "(`ID` != 10 AND `STATUS` IS NULL)"
    assert params_1 == {}
    assert params_2 == {}
    assert ast_node_1 == ast_node_2
