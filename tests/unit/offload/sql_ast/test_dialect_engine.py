# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for DialectSqlEngine on native sqlglot generation."""

import pytest
import sqlglot
from sqlglot import exp

from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
)
from goe.offload.sql_ast.dialect_engine import (
    DialectNotSupportedError,
    DialectSqlEngine,
    TableRef,
    get_dialect_engine,
)


def test_get_dialect_engine_returns_cached_engine_per_dialect() -> None:
    """Verify get_dialect_engine returns cached singleton instances per dialect."""
    assert isinstance(get_dialect_engine("oracle"), DialectSqlEngine)
    assert get_dialect_engine("oracle") is get_dialect_engine("oracle")
    assert get_dialect_engine("oracle").dialect == "oracle"
    assert get_dialect_engine("bigquery") is not get_dialect_engine("oracle")


def test_native_oracle_round_trip_partition_and_scn_bind() -> None:
    """Verify native sqlglot parses and renders Oracle PARTITION and AS OF SCN with bind variables."""
    sql = 'SELECT "A" FROM "OWN"."T" PARTITION ("P1") AS OF SCN :scn t_alias'
    expected = 'SELECT "A" FROM "OWN"."T" PARTITION("P1") AS OF SCN :scn t_alias'
    assert get_dialect_engine("oracle").parse_and_render(sql) == expected

    parsed = sqlglot.parse_one(sql, read="oracle")
    table = parsed.find(exp.Table)
    assert table is not None
    assert isinstance(table.args["partition"], exp.Partition)
    assert isinstance(table.args["version"], exp.Version)


def test_native_oracle_round_trip_subpartition() -> None:
    """Verify native sqlglot parses and renders Oracle SUBPARTITION and AS OF SCN."""
    engine = get_dialect_engine("oracle")
    sql_bind = 'SELECT "A" FROM "OWN"."T" SUBPARTITION ("SP1") AS OF SCN :scn t_alias'
    assert engine.parse_and_render(sql_bind) == 'SELECT "A" FROM "OWN"."T" SUBPARTITION("SP1") AS OF SCN :scn t_alias'

    sql_lit = 'SELECT a FROM "SH"."SALES" SUBPARTITION ("SP1") AS OF SCN 123456 s WHERE a > :b1'
    assert (
        engine.parse_and_render(sql_lit)
        == 'SELECT a FROM "SH"."SALES" SUBPARTITION("SP1") AS OF SCN 123456 s WHERE a > :b1'
    )

    parsed = sqlglot.parse_one(sql_bind, read="oracle")
    table = parsed.find(exp.Table)
    assert table is not None
    partition = table.args["partition"]
    assert isinstance(partition, exp.Partition)
    assert partition.args["subpartition"] is True


def test_native_oracle_round_trip_as_of_timestamp() -> None:
    """Verify native sqlglot parses and renders Oracle AS OF TIMESTAMP flashback clauses."""
    engine = get_dialect_engine("oracle")
    ts_sql = (
        'SELECT "A" FROM "OWN"."T" AS OF TIMESTAMP '
        "TO_TIMESTAMP('2024-01-01 10:11:12.123456789', 'YYYY-MM-DD HH24:MI:SS.FF9') g"
    )
    assert engine.parse_and_render(ts_sql) == ts_sql

    interval_sql = 'SELECT "A" FROM "OWN"."T" AS OF TIMESTAMP SYSTIMESTAMP - INTERVAL \'1\' HOUR g'
    assert engine.parse_and_render(interval_sql) == interval_sql


def test_oracle_extraction_queries_match_current_output() -> None:
    """Verify Oracle extraction query builders match legacy OracleSqlEngine outputs byte-for-byte."""
    engine = get_dialect_engine("oracle")
    assert engine.snapshot_scn_clause(987654) == "AS OF SCN 987654"
    assert engine.snapshot_scn_clause(None) == ""
    assert engine.iot_partition_clause("P_2025") == 'PARTITION("P_2025")'
    assert engine.iot_partition_clause(None) == ""
    assert (
        engine.table_from_clause(
            owner="SH",
            table_name="SALES",
            alias="g",
            partition_names=["P_2025"],
            is_subpartition=True,
            transport_scn=987654,
        )
        == '"SH"."SALES" SUBPARTITION("P_2025") AS OF SCN 987654 g'
    )
    assert engine.table_from_clause(owner="SH", table_name="SALES", alias=None) == '"SH"."SALES"'
    assert (
        engine.id_range_query(
            owner="SH",
            table_name="SALES",
            id_col_name="PROD_ID",
            iot_partition_name="P_2025",
            where_clause='"X" = 1',
        )
        == 'SELECT min_v.val, max_v.val FROM (SELECT MIN(PROD_ID) AS val FROM "SH"."SALES" PARTITION("P_2025") WHERE "X" = 1) min_v, (SELECT MAX(PROD_ID) AS val FROM "SH"."SALES" PARTITION("P_2025") WHERE "X" = 1) max_v'
    )
    assert (
        engine.partition_split_branch_query(
            owner="SH",
            table_name="SALES",
            partition_name="P_2025",
            is_subpartition=False,
            transport_scn=987654,
            batch=1,
            batch_col="goe_batch",
        )
        == 'SELECT g.*, 1 AS goe_batch FROM "SH"."SALES" PARTITION("P_2025") AS OF SCN 987654 g'
    )
    assert (
        engine.extent_split_branch_query(
            owner="SH",
            table_name="SALES",
            transport_scn=987654,
            partition_param="offload_vc2_ntt('P1')",
            subpartition_param="NULL",
            degree=4,
            batch=0,
            batch_col="goe_batch",
            where_clause='"PROD_ID" = 10',
        )
        == "SELECT /*+ NO_INDEX(g) USE_NL(g) LEADING(r) */ g.*, 0 AS goe_batch FROM \"SH\".\"SALES\" AS OF SCN 987654 g, TABLE(offload.offload_rowid_ranges('SH', 'SALES', offload_vc2_ntt('P1'), NULL, 4, 0)) r WHERE g.rowid BETWEEN CHARTOROWID(r.min_rowid_vc) and CHARTOROWID(r.max_rowid_vc) AND (\"PROD_ID\" = 10)"
    )
    assert (
        engine.mod_split_query(
            owner="SH",
            table_name="SALES",
            mod_column="PROD_ID",
            degree=4,
            batch_col="goe_batch",
            iot_partition_name="P1",
            transport_scn=5,
            where_clause='"X" > 1',
        )
        == 'SELECT g.*, MOD(ORA_HASH(PROD_ID), 4) AS goe_batch FROM "SH"."SALES" PARTITION("P1") AS OF SCN 5 g WHERE ("X" > 1)'
    )
    assert (
        engine.native_range_split_query(
            owner="SH",
            table_name="SALES",
            id_col_sql="TRUNC(ID/100)",
            batch_col="goe_batch",
            transport_scn=5,
            where_clause='"X" > 1',
        )
        == 'SELECT g.*, TRUNC(ID/100) AS goe_batch FROM "SH"."SALES" AS OF SCN 5 g WHERE ("X" > 1)'
    )
    assert (
        engine.id_range_split_branch_query(
            owner="SH",
            table_name="SALES",
            id_col_name="PROD_ID",
            low_val=1,
            high_val=100,
            batch=2,
            batch_col="goe_batch",
            transport_scn=5,
            where_clause='"X" > 1',
        )
        == 'SELECT g.*, 2 AS goe_batch FROM "SH"."SALES" AS OF SCN 5 g WHERE PROD_ID >= 1 AND PROD_ID < 100 AND ("X" > 1)'
    )


def test_bigquery_ddl_and_dml_match_current_output() -> None:
    """Verify BigQuery DDL and DML builders match legacy BigQuerySqlEngine outputs byte-for-byte."""
    engine = get_dialect_engine("bigquery")
    cols = [
        ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64, nullable=False),
        ColumnSpec(
            ColumnDialect.BIGQUERY, "AMT", BIGQUERY_TYPE_BIGNUMERIC, data_precision=38, data_scale=0, nullable=True
        ),
        ColumnSpec(
            ColumnDialect.BIGQUERY, "PRICE", BIGQUERY_TYPE_NUMERIC, data_precision=38, data_scale=9, nullable=True
        ),
        ColumnSpec(
            ColumnDialect.BIGQUERY,
            "SALE_DATE",
            BIGQUERY_TYPE_DATE,
            nullable=True,
            partition_info=ColumnPartitionSpec(position=1, granularity="M"),
        ),
    ]
    options = {"kms_key_name": "projects/p/locations/l/keyRings/r/cryptoKeys/k", "description": "o'brien"}

    assert engine.partition_by_clause(cols[3]) == "DATE_TRUNC(`SALE_DATE`, MONTH)"
    assert (
        engine.properties_clause(
            partition_expr_sql="DATE_TRUNC(`SALE_DATE`, MONTH)",
            cluster_cols=["ID", "AMT"],
            options=options,
        )
        == "PARTITION BY DATE_TRUNC(`SALE_DATE`, MONTH) CLUSTER BY `ID`, `AMT` OPTIONS (kms_key_name='projects/p/locations/l/keyRings/r/cryptoKeys/k', description='o\\'brien')"
    )
    assert (
        engine.properties_clause(options={"kms_key_name": "k1", "labels": [("a", "b")]})
        == "OPTIONS (kms_key_name='k1', labels=[['a', 'b']])"
    )
    assert (
        engine.create_table(
            project="my-proj",
            db_name="sh_ds",
            table_name="sales",
            columns=cols,
            partition_expr_sql="DATE_TRUNC(`SALE_DATE`, MONTH)",
            cluster_cols=["ID", "AMT"],
            options=options,
            replace=True,
        )
        == "CREATE OR REPLACE TABLE `my-proj`.`sh_ds`.`sales` (`ID` INT64 NOT NULL, `AMT` BIGNUMERIC(38, 0), `PRICE` NUMERIC(38, 9), `SALE_DATE` DATE) PARTITION BY DATE_TRUNC(`SALE_DATE`, MONTH) CLUSTER BY `ID`, `AMT` OPTIONS (kms_key_name='projects/p/locations/l/keyRings/r/cryptoKeys/k', description='o\\'brien')"
    )
    assert (
        engine.create_table(project=None, db_name="d", table_name="t", columns=cols[:2])
        == "CREATE TABLE `d`.`t` (`ID` INT64 NOT NULL, `AMT` BIGNUMERIC(38, 0))"
    )
    assert (
        engine.create_external_table(
            project="my-proj",
            db_name="sh_stage",
            table_name="sales_ext",
            columns=[
                ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64),
                ColumnSpec(ColumnDialect.BIGQUERY, "NAME", BIGQUERY_TYPE_STRING),
            ],
            storage_format="PARQUET",
            uris=["gs://bucket/path/*.parquet"],
            extra_options={"enable_list_inference": True},
            replace=True,
        )
        == "CREATE OR REPLACE EXTERNAL TABLE `my-proj`.`sh_stage`.`sales_ext` (`ID` INT64, `NAME` STRING) OPTIONS (format='PARQUET', enable_list_inference=TRUE, uris=['gs://bucket/path/*.parquet'])"
    )
    assert (
        engine.create_external_table(
            project="my-proj",
            db_name="sh_stage",
            table_name="sales_ext_schemaless",
            columns=None,
            storage_format="AVRO",
            uris=["gs://bucket/path/*.avro"],
            extra_options={"description": "GOE staging table"},
        )
        == "CREATE EXTERNAL TABLE `my-proj`.`sh_stage`.`sales_ext_schemaless` OPTIONS (format='AVRO', description='GOE staging table', uris=['gs://bucket/path/*.avro'])"
    )
    assert (
        engine.create_or_replace_ddl("create table `p.d.t` (\n  x INT64 OPTIONS(description='CREATE TABLE inner')\n)")
        == "CREATE OR REPLACE TABLE `p.d.t` (\n  x INT64 OPTIONS(description='CREATE TABLE inner')\n)"
    )
    assert (
        engine.ctas(
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
        == "CREATE TABLE `my-proj`.`sh_ds`.`sales_copy` OPTIONS (kms_key_name='projects/p/locations/l/keyRings/r/cryptoKeys/k') AS SELECT CAST(`ID` AS INT64) AS `ID`, DATETIME '2020-01-01 00:00:00' AS `DT` FROM `my-proj`.`sh_stage`.`sales_ext` LIMIT 10"
    )
    assert (
        engine.insert_select(
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
        == "INSERT INTO `my-proj`.`sh_ds`.`sales` (`ID`, `NAME`) SELECT CAST(`ID` AS INT64) AS `ID`, `NAME` AS `NAME` FROM `my-proj`.`sh_stage`.`sales_ext` WHERE (`ID` > 100) AND (`DT` >= DATETIME '2020-01-01 00:00:00')"
    )
    assert (
        engine.insert_select(
            project=None,
            db_name="d",
            table_name="t",
            select_expr_tuples=[("1", "A")],
            from_object_override="UNNEST([1]) AS u",
        )
        == "INSERT INTO `d`.`t` SELECT 1 AS `A` FROM UNNEST([1]) AS u"
    )
    assert (
        engine.create_view(
            project="my-proj",
            db_name="sh_ds",
            view_name="sales_v",
            select_expr_tuples=[("`ID`", "ID"), ("`NAME`", "NAME")],
            from_tables="`my-proj`.`sh_ds`.`sales`",
            where_clauses=["`ID` IS NOT NULL"],
            replace=True,
        )
        == "CREATE OR REPLACE VIEW `my-proj`.`sh_ds`.`sales_v` AS SELECT `ID` AS `ID`, `NAME` AS `NAME` FROM `my-proj`.`sh_ds`.`sales` WHERE (`ID` IS NOT NULL)"
    )


def test_alter_add_columns_per_dialect() -> None:
    """Verify alter_add_columns renders dialect-specific DDL and rejects unsupported dialects."""
    assert (
        get_dialect_engine("bigquery").alter_add_columns(
            table=TableRef(name="sales", schema="sh_ds", catalog="my-proj"),
            columns=[("NEW_COL", "STRING"), ("AMT", "BIGNUMERIC(38, 0)")],
            if_not_exists=True,
        )
        == "ALTER TABLE `my-proj`.`sh_ds`.`sales` ADD COLUMN IF NOT EXISTS `NEW_COL` STRING, ADD COLUMN IF NOT EXISTS `AMT` BIGNUMERIC(38, 0)"
    )
    assert (
        get_dialect_engine("bigquery").alter_add_columns(
            table=TableRef(name="SALES", schema="SH", catalog="proj"),
            columns=[("NEW_COL", "STRING(20)"), ("AMT", "NUMERIC(38, 9)")],
        )
        == "ALTER TABLE `proj`.`SH`.`SALES` ADD COLUMN `NEW_COL` STRING(20), ADD COLUMN `AMT` NUMERIC(38, 9)"
    )
    assert (
        get_dialect_engine("snowflake").alter_add_columns(
            table=TableRef(name="SALES", schema="SH"),
            columns=[("NEW_COL", "VARCHAR(20)"), ("AMT", "DECIMAL(38, 9)")],
        )
        == 'ALTER TABLE "SH"."SALES" ADD "NEW_COL" VARCHAR(20), "AMT" DECIMAL(38, 9)'
    )
    assert (
        get_dialect_engine("snowflake").alter_add_columns(
            table=TableRef(name="SALES", schema="SH"),
            columns=[("NEW_COL", "VARCHAR(20)")],
            if_not_exists=True,
        )
        == 'ALTER TABLE "SH"."SALES" ADD IF NOT EXISTS "NEW_COL" VARCHAR(20)'
    )
    assert (
        get_dialect_engine("tsql").alter_add_columns(
            table=TableRef(name="SALES", schema="SH"),
            columns=[("NEW_COL", "VARCHAR(20)"), ("AMT", "NUMERIC(38, 9)")],
        )
        == "ALTER TABLE [SH].[SALES] ADD [NEW_COL] VARCHAR(20), [AMT] NUMERIC(38, 9)"
    )
    with pytest.raises(
        DialectNotSupportedError,
        match="alter_add_columns with if_not_exists is not supported for dialect tsql",
    ):
        get_dialect_engine("tsql").alter_add_columns(
            table=TableRef(name="SALES", schema="SH"),
            columns=[("NEW_COL", "VARCHAR(20)")],
            if_not_exists=True,
        )
    for unsupported_dialect in ("oracle", "hive", "spark"):
        with pytest.raises(
            DialectNotSupportedError,
            match=f"alter_add_columns is not supported for dialect {unsupported_dialect}",
        ):
            get_dialect_engine(unsupported_dialect).alter_add_columns(
                table=TableRef(name="SALES", schema="SH"),
                columns=[("NEW_COL", "VARCHAR(20)")],
            )


def test_alter_column_set_data_type_and_drop_not_null() -> None:
    """Verify alter_column_set_data_type and alter_column_drop_not_null across dialects."""
    assert (
        get_dialect_engine("bigquery").alter_column_set_data_type(
            table=TableRef(name="SALES", schema="SH", catalog="proj"),
            column="AMT",
            data_type="NUMERIC(38, 9)",
        )
        == "ALTER TABLE `proj`.`SH`.`SALES` ALTER COLUMN `AMT` SET DATA TYPE NUMERIC(38, 9)"
    )
    assert (
        get_dialect_engine("snowflake").alter_column_set_data_type(
            table=TableRef(name="SALES", schema="SH"),
            column="AMT",
            data_type="DECIMAL(38, 9)",
        )
        == 'ALTER TABLE "SH"."SALES" ALTER COLUMN "AMT" SET DATA TYPE DECIMAL(38, 9)'
    )
    assert (
        get_dialect_engine("bigquery").alter_column_drop_not_null(
            table=TableRef(name="SALES", schema="SH", catalog="proj"),
            column="AMT",
        )
        == "ALTER TABLE `proj`.`SH`.`SALES` ALTER COLUMN `AMT` DROP NOT NULL"
    )
    assert (
        get_dialect_engine("snowflake").alter_column_drop_not_null(
            table=TableRef(name="SALES", schema="SH"),
            column="AMT",
        )
        == 'ALTER TABLE "SH"."SALES" ALTER COLUMN "AMT" DROP NOT NULL'
    )
    for unsupported_dialect in ("oracle", "tsql", "hive", "spark"):
        with pytest.raises(
            DialectNotSupportedError,
            match=f"alter_column_set_data_type is not supported for dialect {unsupported_dialect}",
        ):
            get_dialect_engine(unsupported_dialect).alter_column_set_data_type(
                table=TableRef(name="SALES", schema="SH"),
                column="AMT",
                data_type="DECIMAL(38, 9)",
            )
        with pytest.raises(
            DialectNotSupportedError,
            match=f"alter_column_drop_not_null is not supported for dialect {unsupported_dialect}",
        ):
            get_dialect_engine(unsupported_dialect).alter_column_drop_not_null(
                table=TableRef(name="SALES", schema="SH"),
                column="AMT",
            )


def test_dialect_specific_methods_reject_other_dialects() -> None:
    """Verify Oracle-only and BigQuery-only methods reject other dialects."""
    with pytest.raises(
        DialectNotSupportedError,
        match="create_table is not supported for dialect snowflake",
    ):
        get_dialect_engine("snowflake").create_table(project=None, db_name="d", table_name="t", columns=[])
    with pytest.raises(
        DialectNotSupportedError,
        match="table_from_clause is not supported for dialect bigquery",
    ):
        get_dialect_engine("bigquery").table_from_clause(owner="SH", table_name="SALES")
