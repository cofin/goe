# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BigQuerySqlEngine and BackendBigQueryApi SQL generation."""

import ast
from pathlib import Path

import sqlglot
from sqlglot import exp

import goe.offload.bigquery.bigquery_backend_api as bq_backend_api_mod
from goe.offload.bigquery.bigquery_column import (
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    BIGQUERY_TYPE_TIMESTAMP,
    BigQueryColumn,
)
from goe.offload.bigquery.bigquery_sql import (
    BigQuerySqlEngine,
    get_bigquery_dialect_engine,
)
from goe.offload.column_metadata import ColumnPartitionInfo
from goe.offload.sql_engine import BigQueryDialectEngineProtocol


def test_bigquery_backend_api_has_zero_sqlglot_imports() -> None:
    """Verify bigquery_backend_api.py does not import sqlglot directly."""
    source = Path(bq_backend_api_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)
    assert not any("sqlglot" in name for name in imported_names)


def test_bigquery_dialect_engine_satisfies_protocol() -> None:
    """Verify BigQuerySqlEngine satisfies BigQueryDialectEngineProtocol."""
    engine = get_bigquery_dialect_engine()
    assert isinstance(engine, BigQueryDialectEngineProtocol)
    assert isinstance(engine, BigQuerySqlEngine)


def test_partition_by_clause_date_datetime_timestamp_and_range_bucket() -> None:
    """Verify partition_by_clause supports DATE, DATETIME, TIMESTAMP, and INT64 range buckets."""
    engine = get_bigquery_dialect_engine()
    date_col = BigQueryColumn(
        "SALE_DATE",
        BIGQUERY_TYPE_DATE,
        partition_info=ColumnPartitionInfo(position=1, granularity="M"),
    )
    assert engine.partition_by_clause(date_col) == "DATE_TRUNC(`SALE_DATE`, MONTH)"

    dt_col = BigQueryColumn(
        "SALE_DT",
        BIGQUERY_TYPE_DATETIME,
        partition_info=ColumnPartitionInfo(position=1, granularity="Y"),
    )
    assert engine.partition_by_clause(dt_col) == "DATETIME_TRUNC(`SALE_DT`, YEAR)"

    ts_col = BigQueryColumn(
        "SALE_TS",
        BIGQUERY_TYPE_TIMESTAMP,
        partition_info=ColumnPartitionInfo(position=1, granularity="D"),
    )
    assert engine.partition_by_clause(ts_col) == "TIMESTAMP_TRUNC(`SALE_TS`, DAY)"

    range_col = BigQueryColumn(
        "ID",
        BIGQUERY_TYPE_INT64,
        partition_info=ColumnPartitionInfo(
            position=1,
            granularity="1000",
            range_start=0,
            range_end=1000000,
        ),
    )
    assert engine.partition_by_clause(range_col) == "RANGE_BUCKET(`ID`, GENERATE_ARRAY(0, 1000000, 1000))"


def test_create_table_with_partition_cluster_and_options_parity() -> None:
    """Verify create_table returns BigQuery DDL string matching legacy semantics and escaping options."""
    engine = get_bigquery_dialect_engine()
    cols = [
        BigQueryColumn("ID", BIGQUERY_TYPE_INT64, nullable=False),
        BigQueryColumn("AMT", BIGQUERY_TYPE_BIGNUMERIC, data_precision=38, data_scale=0, nullable=True),
        BigQueryColumn("PRICE", BIGQUERY_TYPE_NUMERIC, data_precision=38, data_scale=9, nullable=True),
        BigQueryColumn(
            "SALE_DATE",
            BIGQUERY_TYPE_DATE,
            nullable=True,
            partition_info=ColumnPartitionInfo(position=1, granularity="M"),
        ),
    ]
    part_clause = engine.partition_by_clause(cols[3])
    rendered = engine.create_table(
        project="my-proj",
        db_name="sh_ds",
        table_name="sales",
        columns=cols,
        partition_expr_sql=part_clause,
        cluster_cols=["ID", "AMT"],
        options={"kms_key_name": "projects/p/locations/l/keyRings/r/cryptoKeys/k", "description": "o'brien"},
        replace=True,
    )
    assert rendered.startswith("CREATE OR REPLACE TABLE `my-proj`.`sh_ds`.`sales`")
    assert "`ID` INT64 NOT NULL" in rendered
    assert "`AMT` BIGNUMERIC(38, 0)" in rendered
    assert "`PRICE` NUMERIC(38, 9)" in rendered
    assert "PARTITION BY DATE_TRUNC(`SALE_DATE`, MONTH)" in rendered
    assert "CLUSTER BY `ID`, `AMT`" in rendered
    assert "kms_key_name='projects/p/locations/l/keyRings/r/cryptoKeys/k'" in rendered
    parsed = sqlglot.parse_one(rendered, read="bigquery")
    assert isinstance(parsed, exp.Create)


def test_create_external_table_escapes_uris_and_format() -> None:
    """Verify create_external_table builds safe OPTIONS literals and supports optional columns."""
    engine = get_bigquery_dialect_engine()
    cols = [BigQueryColumn("ID", BIGQUERY_TYPE_INT64), BigQueryColumn("NAME", BIGQUERY_TYPE_STRING)]
    rendered = engine.create_external_table(
        project="my-proj",
        db_name="sh_stage",
        table_name="sales_ext",
        columns=cols,
        storage_format="PARQUET",
        uris=["gs://bucket/path/*.parquet"],
        extra_options={"enable_list_inference": True},
        replace=True,
    )
    assert "CREATE OR REPLACE EXTERNAL TABLE `my-proj`.`sh_stage`.`sales_ext`" in rendered
    assert "format='PARQUET'" in rendered
    assert "uris=['gs://bucket/path/*.parquet']" in rendered
    assert "enable_list_inference=TRUE" in rendered

    schemaless = engine.create_external_table(
        project="my-proj",
        db_name="sh_stage",
        table_name="sales_ext_schemaless",
        columns=None,
        storage_format="AVRO",
        uris=["gs://bucket/path/*.avro"],
        extra_options={"description": "GOE staging table"},
        replace=False,
    )
    assert schemaless.startswith("CREATE EXTERNAL TABLE `my-proj`.`sh_stage`.`sales_ext_schemaless` OPTIONS")
    assert "description='GOE staging table'" in schemaless


def test_create_or_replace_ddl_rewrites_leading_create_table_tokens() -> None:
    """Verify create_or_replace_ddl uses lexical tokenization without re-rendering body tokens."""
    engine = get_bigquery_dialect_engine()
    ddl = "create table `p.d.t` (\n  x INT64 OPTIONS(description='CREATE TABLE inner')\n)"
    replaced = engine.create_or_replace_ddl(ddl)
    assert replaced.startswith("CREATE OR REPLACE TABLE `p.d.t`")
    assert "description='CREATE TABLE inner'" in replaced


def test_ctas_insert_select_alter_and_create_view_preserve_typed_literals() -> None:
    """Verify ctas, insert_select, alter_add_columns, and create_view preserve caller expressions."""
    engine = get_bigquery_dialect_engine()
    ctas_sql = engine.ctas(
        project="my-proj",
        db_name="sh_ds",
        table_name="sales_copy",
        from_project="my-proj",
        from_db_name="sh_stage",
        from_table_name="sales_ext",
        select_expr_tuples=[("CAST(`ID` AS INT64)", "ID"), ("DATETIME '2020-01-01 00:00:00'", "DT")],
        options={"kms_key_name": "projects/p/locations/l/keyRings/r/cryptoKeys/k"},
        row_limit=10,
    )
    assert "CREATE TABLE `my-proj`.`sh_ds`.`sales_copy`" in ctas_sql
    assert "DATETIME '2020-01-01 00:00:00' AS `DT`" in ctas_sql
    assert "LIMIT 10" in ctas_sql

    ins_sql = engine.insert_select(
        project="my-proj",
        db_name="sh_ds",
        table_name="sales",
        insert_col_names=["ID", "NAME"],
        select_expr_tuples=[("CAST(`ID` AS INT64)", "ID"), ("`NAME`", "NAME")],
        from_project="my-proj",
        from_db_name="sh_stage",
        from_table_name="sales_ext",
        where_clauses=["`ID` > 100", "`DT` >= DATETIME '2020-01-01 00:00:00'"],
    )
    assert ins_sql.startswith("INSERT INTO `my-proj`.`sh_ds`.`sales` (`ID`, `NAME`) SELECT")
    assert "WHERE (`ID` > 100) AND (`DT` >= DATETIME '2020-01-01 00:00:00')" in ins_sql

    alter_sql = engine.alter_add_columns(
        project="my-proj",
        db_name="sh_ds",
        table_name="sales",
        column_name_type_pairs=[("NEW_COL", "STRING"), ("AMT", "BIGNUMERIC(38, 0)")],
    )
    assert alter_sql == (
        "ALTER TABLE `my-proj`.`sh_ds`.`sales` "
        "ADD COLUMN IF NOT EXISTS `NEW_COL` STRING, ADD COLUMN IF NOT EXISTS `AMT` BIGNUMERIC(38, 0)"
    )

    view_sql = engine.create_view(
        project="my-proj",
        db_name="sh_ds",
        view_name="sales_v",
        select_expr_tuples=[("`ID`", "ID"), ("`NAME`", "NAME")],
        from_tables="`my-proj`.`sh_ds`.`sales`",
        where_clauses=["`ID` IS NOT NULL"],
        replace=False,
    )
    assert view_sql == (
        "CREATE VIEW `my-proj`.`sh_ds`.`sales_v` AS "
        "SELECT `ID` AS `ID`, `NAME` AS `NAME` FROM `my-proj`.`sh_ds`.`sales` WHERE (`ID` IS NOT NULL)"
    )
