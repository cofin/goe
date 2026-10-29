# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Offline golden unit test suite for Oracle-to-BigQuery offload SQL and DDL generation."""

from unittest import mock

import pytest

from goe.offload.bigquery import bigquery_predicate
from goe.offload.bigquery.bigquery_backend_api import BackendBigQueryApi
from goe.offload.bigquery.bigquery_backend_table import BackendBigQueryTable
from goe.offload.offload_constants import (
    DBTYPE_BIGQUERY,
    FILE_STORAGE_FORMAT_AVRO,
)
from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_source_data import (
    OFFLOAD_SOURCE_CLIENT_OFFLOAD,
    OffloadSourceDataIpaRange,
    OffloadSourcePartitions,
)
from goe.offload.oracle import oracle_predicate
from goe.offload.predicate_offload import GenericPredicate
from goe.offload.registry import create_staging_file
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    GOE_TYPE_DATE,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_TIMESTAMP,
    GOE_TYPE_VARIABLE_STRING,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_VARCHAR2,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
)
from tests.unit.test_functions import (
    FAKE_ORACLE_BQ_ENV,
    build_fake_oracle_subpartitioned_table,
    build_fake_oracle_table,
    build_mock_offload_operation,
    build_mock_options,
)


@pytest.fixture
def bq_config():
    return build_mock_options(FAKE_ORACLE_BQ_ENV)


@pytest.fixture
def messages():
    return OffloadMessages()


@pytest.fixture
def bq_dry_run_api(bq_config, messages):
    return BackendBigQueryApi(
        bq_config,
        DBTYPE_BIGQUERY,
        messages,
        dry_run=True,
        do_not_connect=True,
    )


def test_golden_rbo_bigquery_ddl_staging_and_final_insert_sql(bq_config, messages):
    """Verify RBO canonical conversion, CREATE TABLE DDL, external staging DDL, and INSERT/SELECT SQL."""
    bq_table = _build_bq_table(
        bq_config,
        messages,
        db_name="target_ds",
        table_name="sales_rbo",
        sort_columns=["ID", "STATUS"],
    )
    rdbms_cols = [
        ColumnSpec(ColumnDialect.ORACLE, "ID", ORACLE_TYPE_NUMBER, data_precision=18, data_scale=0, nullable=False),
        ColumnSpec(ColumnDialect.ORACLE, "STATUS", ORACLE_TYPE_VARCHAR2, data_length=32, nullable=True),
        ColumnSpec(ColumnDialect.ORACLE, "AMOUNT", ORACLE_TYPE_NUMBER, data_precision=12, data_scale=2, nullable=True),
        ColumnSpec(ColumnDialect.ORACLE, "ORDER_DATE", ORACLE_TYPE_DATE, nullable=True),
    ]
    canonical_cols = [
        ColumnSpec(ColumnDialect.CANONICAL, "ID", GOE_TYPE_INTEGER_8, nullable=False),
        ColumnSpec(ColumnDialect.CANONICAL, "STATUS", GOE_TYPE_VARIABLE_STRING, data_length=32, nullable=True),
        ColumnSpec(ColumnDialect.CANONICAL, "AMOUNT", GOE_TYPE_DECIMAL, data_precision=12, data_scale=2, nullable=True),
        ColumnSpec(ColumnDialect.CANONICAL, "ORDER_DATE", GOE_TYPE_DATE, nullable=True),
    ]
    bq_cols = bq_table.convert_canonical_columns_to_backend(canonical_cols)
    bq_table.set_columns(bq_cols)

    assert [col.data_type for col in bq_cols] == [
        BIGQUERY_TYPE_INT64,
        BIGQUERY_TYPE_STRING,
        BIGQUERY_TYPE_NUMERIC,
        BIGQUERY_TYPE_DATE,
    ]

    create_ddl = bq_table.create_backend_table(with_terminator=True)
    assert len(create_ddl) == 1
    assert create_ddl[0] == (
        "CREATE TABLE `bq-project`.`target_ds`.`sales_rbo` "
        "(`ID` INT64 NOT NULL, `STATUS` STRING(32), `AMOUNT` NUMERIC(12, 2), `ORDER_DATE` DATE) "
        "CLUSTER BY `ID`, `STATUS`;"
    )

    staging_file = create_staging_file(
        bq_table.get_load_db_name(),
        bq_table.get_load_table_name(),
        FILE_STORAGE_FORMAT_AVRO,
        canonical_cols,
        bq_config,
        bq_table.transport_binary_data_in_base64(),
        messages,
        dry_run=True,
    )
    native_load = bq_table._create_load_table(staging_file, with_terminator=True)
    assert native_load == [
        "BigQuery load job: gs://b/target_ds_load/sales_rbo/part* -> "
        "bq-project.target_ds_load.sales_rbo (format=AVRO, write_disposition=WRITE_TRUNCATE)"
    ]
    bq_config.bigquery_load_table_mode = "EXTERNAL"
    try:
        load_ddl = bq_table._create_load_table(staging_file, with_terminator=True)
    finally:
        bq_config.bigquery_load_table_mode = "NATIVE"
    assert len(load_ddl) == 1
    assert "CREATE EXTERNAL TABLE `bq-project`.`target_ds_load`.`sales_rbo`" in load_ddl[0]
    assert "format='AVRO'" in load_ddl[0]
    assert "uris=['gs://b/target_ds_load/sales_rbo/part*']" in load_ddl[0]

    bq_table.set_final_table_casts(rdbms_cols, staging_file.get_staging_columns())
    select_exprs = [(bq_table.get_final_table_cast(col), col.name.upper()) for col in bq_table.get_columns()]
    insert_sqls, query_options = bq_table._gen_final_insert_sqls(select_exprs)
    assert len(insert_sqls) == 1
    assert insert_sqls[0] == (
        "INSERT INTO `bq-project`.`target_ds`.`sales_rbo` "
        "SELECT `ID` AS `ID`, "
        "`STATUS` AS `STATUS`, "
        "CAST(`AMOUNT` AS NUMERIC(12,2)) AS `AMOUNT`, "
        "CAST(PARSE_DATETIME('%F %H:%M:%E*S', `ORDER_DATE`) AS DATE) AS `ORDER_DATE` "
        "FROM `bq-project`.`target_ds_load`.`sales_rbo`"
    )
    assert query_options is None


def test_golden_ipa_range_partitioning_and_chunking(bq_config, messages):
    """Verify IPA RANGE native datetime partitioning, synthetic numeric partitioning, and chunking."""
    bq_table = _build_bq_table(bq_config, messages, db_name="target_ds", table_name="sales_ipa_range")
    canonical_cols = [
        ColumnSpec(ColumnDialect.CANONICAL, "ID", GOE_TYPE_INTEGER_8, nullable=False),
        ColumnSpec(
            ColumnDialect.CANONICAL,
            "CREATED_TS",
            GOE_TYPE_TIMESTAMP,
            data_scale=6,
            nullable=True,
            partition_info=ColumnPartitionSpec(
                position=0,
                source_column_name="CREATED_TS",
                granularity="M",
            ),
        ),
    ]
    bq_cols = bq_table.convert_canonical_columns_to_backend(canonical_cols)
    bq_table.set_columns(bq_cols)
    assert bq_cols[1].data_type == BIGQUERY_TYPE_DATETIME

    create_ddl = bq_table.create_backend_table(with_terminator=True)
    assert len(create_ddl) == 1
    assert "PARTITION BY DATETIME_TRUNC(`CREATED_TS`, MONTH)" in create_ddl[0]

    synth_table = _build_bq_table(bq_config, messages, db_name="target_ds", table_name="sales_ipa_decimal")
    synth_rdbms_cols = [
        ColumnSpec(
            ColumnDialect.ORACLE, "ACCOUNT_NUM", ORACLE_TYPE_NUMBER, data_precision=28, data_scale=0, nullable=False
        ),
    ]
    synth_canonical = [
        ColumnSpec(
            ColumnDialect.CANONICAL,
            "ACCOUNT_NUM",
            GOE_TYPE_DECIMAL,
            data_precision=28,
            data_scale=0,
            nullable=False,
            partition_info=ColumnPartitionSpec(
                position=0,
                source_column_name="ACCOUNT_NUM",
                granularity=100,
                digits=18,
                range_start=0,
                range_end=100000,
            ),
        ),
    ]
    synth_bq_cols = synth_table.convert_canonical_columns_to_backend(synth_canonical)
    synth_table.set_columns(synth_bq_cols)
    synth_cols = synth_table.get_synthetic_columns()
    assert len(synth_cols) == 1
    assert synth_cols[0].name == "GOE_PART_000000000000000100_ACCOUNT_NUM"
    assert synth_cols[0].data_type == BIGQUERY_TYPE_INT64

    synth_ddl = synth_table.create_backend_table(with_terminator=True)
    assert (
        "PARTITION BY RANGE_BUCKET(`GOE_PART_000000000000000100_ACCOUNT_NUM`, GENERATE_ARRAY(0, 100000, 100))"
        in synth_ddl[0]
    )

    staging_file = create_staging_file(
        synth_table.get_load_db_name(),
        synth_table.get_load_table_name(),
        FILE_STORAGE_FORMAT_AVRO,
        synth_canonical,
        bq_config,
        synth_table.transport_binary_data_in_base64(),
        messages,
        dry_run=True,
    )
    synth_table.set_final_table_casts(synth_rdbms_cols, staging_file.get_staging_columns())
    assert synth_table.get_final_table_cast("GOE_PART_000000000000000100_ACCOUNT_NUM") == (
        "CAST(FLOOR(CAST(CAST(`ACCOUNT_NUM` AS NUMERIC(28,0)) AS BIGNUMERIC) / 100) * 100 AS INT64)"
    )

    oracle_table = build_fake_oracle_table(bq_config, messages)
    fake_op = build_mock_offload_operation()
    fake_op.max_offload_chunk_count = 2
    fake_op.max_offload_chunk_size = 1_000_000_000
    ipa_client = OffloadSourceDataIpaRange(
        oracle_table,
        bq_table,
        fake_op,
        {},
        messages,
        OFFLOAD_SOURCE_CLIENT_OFFLOAD,
    )
    partitions = OffloadSourcePartitions.from_source_table(oracle_table, True)
    ipa_client._override_partitions_to_offload(partitions)
    chunks = list(ipa_client.get_partitions_to_offload_chunks())
    assert len(chunks) == 2
    assert [p.partition_name for p in chunks[0][0].get_partitions()] == ["P2", "P1"]
    assert [p.partition_name for p in chunks[1][0].get_partitions()] == ["P4", "P3"]


def test_golden_ipa_list_subpartition_tracking(bq_config, messages):
    """Verify LIST/RANGE subpartitioned source table partition discovery and subpartition metadata."""
    oracle_subpart_table = build_fake_oracle_subpartitioned_table(bq_config, messages)
    assert oracle_subpart_table.partition_type == "LIST"
    assert oracle_subpart_table.subpartition_type == "RANGE"
    partitions = OffloadSourcePartitions.from_source_table(oracle_subpart_table, True)
    assert partitions.count() == 2
    assert [p.partition_name for p in partitions.get_partitions()] == ["P3", "P4"]
    assert partitions.get_partitions()[0].subpartitions == [
        "P3_201201",
        "P3_201202",
        "P3_201204",
        "P3_201205",
    ]
    assert partitions.get_partitions()[0].partition_values_python == (3,)
    assert partitions.get_partitions()[1].partition_values_python == (4,)


def test_golden_pbo_predicate_pushdown_oracle_and_bigquery_rendering(bq_config, messages):
    """Verify GenericPredicate AST renders identical semantic filters for Oracle and BigQuery."""
    ora_cols = [
        ColumnSpec(ColumnDialect.ORACLE, "ID", ORACLE_TYPE_NUMBER, data_precision=18, data_scale=0),
        ColumnSpec(ColumnDialect.ORACLE, "STATUS", ORACLE_TYPE_VARCHAR2, data_length=32),
        ColumnSpec(ColumnDialect.ORACLE, "AMOUNT", ORACLE_TYPE_NUMBER, data_precision=12, data_scale=2),
    ]
    bq_cols = [
        ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64),
        ColumnSpec(ColumnDialect.BIGQUERY, "STATUS", BIGQUERY_TYPE_STRING),
        ColumnSpec(ColumnDialect.BIGQUERY, "AMOUNT", BIGQUERY_TYPE_NUMERIC, data_precision=38, data_scale=9),
    ]
    bq_table = _build_bq_table(bq_config, messages, db_name="target_ds", table_name="sales_pbo")
    bq_table.set_columns(bq_cols)

    pred_simple = GenericPredicate("column(ID) > numeric(1000)")
    ora_where_simple = oracle_predicate.predicate_to_where_clause(ora_cols, pred_simple)
    bq_where_simple = bq_table.predicate_to_where_clause(pred_simple)
    assert ora_where_simple == '"ID" > 1000'
    assert bq_where_simple == "`ID` > 1000"

    pred_compound = GenericPredicate('(column(STATUS) = string("CLOSED")) and (column(AMOUNT) >= numeric(50.25))')
    ora_where_compound = oracle_predicate.predicate_to_where_clause(ora_cols, pred_compound)
    bq_where_compound = bigquery_predicate.predicate_to_where_clause(bq_cols, pred_compound)
    assert ora_where_compound == '("STATUS" = \'CLOSED\' AND "AMOUNT" >= 50.25)'
    assert bq_where_compound == "(`STATUS` = 'CLOSED' AND `AMOUNT` >= NUMERIC '50.25')"


def test_golden_bigquery_schema_evolution_add_columns_ddl(bq_dry_run_api):
    """Verify BigQuery schema evolution emits ALTER TABLE ADD COLUMN IF NOT EXISTS DDL."""
    new_cols = [
        ("DISCOUNT_RATE", BIGQUERY_TYPE_NUMERIC),
        ("NOTES", BIGQUERY_TYPE_STRING),
    ]
    with mock.patch.object(bq_dry_run_api, "_get_bq_table", return_value=mock.MagicMock()):
        ddl_list = bq_dry_run_api.add_columns("target_ds", "sales_rbo", new_cols, sync=True)
    assert ddl_list == [
        "ALTER TABLE `bq-project`.`target_ds`.`sales_rbo` "
        "ADD COLUMN IF NOT EXISTS `DISCOUNT_RATE` NUMERIC, "
        "ADD COLUMN IF NOT EXISTS `NOTES` STRING"
    ]


def _build_bq_table(
    bq_config,
    messages,
    db_name: str = "target_ds",
    table_name: str = "sales_rbo",
    sort_columns: list[str] | None = None,
) -> BackendBigQueryTable:
    operation = build_mock_offload_operation()
    operation.target_owner = db_name
    operation.offload_chunk_column = None
    operation.impala_insert_hint = None
    operation.bucket_hash_col = None
    operation.ipa_predicate_type = None
    operation.offload_partition_functions = None
    operation.offload_distribute_enabled = False
    operation.offload_stats_method = None
    operation.sort_columns = sort_columns
    return BackendBigQueryTable(
        db_name,
        table_name,
        DBTYPE_BIGQUERY,
        bq_config,
        messages,
        orchestration_operation=operation,
        dry_run=True,
        do_not_connect=True,
    )
