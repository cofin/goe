# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Hadoop (Hive, Impala) and Spark Thrift backend APIs, catalog cache, and table operations."""

from __future__ import annotations

from unittest.mock import MagicMock

from goe.offload.backend_capabilities import BackendCapabilities
from goe.offload.hadoop.hive_backend_api import HIVE_CAPABILITIES
from goe.offload.hadoop.hive_backend_table import HASH_BUCKET_EXPRESSION
from goe.offload.hadoop.impala_backend_api import IMPALA_CAPABILITIES
from goe.offload.offload_constants import (
    DBTYPE_HIVE,
    DBTYPE_IMPALA,
    DBTYPE_SPARK,
    FILE_STORAGE_FORMAT_ORC,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_backend_api, create_backend_table
from goe.offload.schema.column_spec import (
    GOE_TYPE_DECIMAL,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_VARIABLE_STRING,
    HADOOP_TYPE_BIGINT,
    HADOOP_TYPE_DECIMAL,
    HADOOP_TYPE_STRING,
    HADOOP_TYPE_VARCHAR,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
)
from goe.offload.spark.spark_thrift_backend_api import SPARK_CAPABILITIES
from tests.unit.test_functions import (
    FAKE_ORACLE_HIVE_ENV,
    FAKE_ORACLE_IMPALA_ENV,
    build_mock_options,
)


def test_hive_impala_spark_capabilities_and_type_mappings() -> None:
    hive_api = _make_hive_api()
    impala_api = _make_impala_api()
    spark_api = _make_spark_api()

    assert isinstance(hive_api.capabilities, BackendCapabilities)
    assert hive_api.capabilities == HIVE_CAPABILITIES
    assert isinstance(impala_api.capabilities, BackendCapabilities)
    assert impala_api.capabilities == IMPALA_CAPABILITIES
    assert isinstance(spark_api.capabilities, BackendCapabilities)
    assert spark_api.capabilities == SPARK_CAPABILITIES

    assert hive_api._sql_engine.dialect == "hive"
    assert impala_api._sql_engine.dialect == "hive"
    assert spark_api._sql_engine.dialect == "spark"

    canonical_dec = ColumnSpec(
        ColumnDialect.CANONICAL,
        "AMOUNT",
        GOE_TYPE_DECIMAL,
        data_precision=38,
        data_scale=18,
    )
    for api in (hive_api, impala_api, spark_api):
        backend_col = api.from_canonical_column(canonical_dec)
        assert backend_col.dialect is ColumnDialect.HADOOP
        assert backend_col.data_type == HADOOP_TYPE_DECIMAL
        assert backend_col.data_precision == 38
        assert backend_col.data_scale == 18

        round_trip = api.to_canonical_column(backend_col)
        assert round_trip.dialect is ColumnDialect.CANONICAL
        assert round_trip.data_type == GOE_TYPE_DECIMAL
        assert round_trip.data_precision == 38
        assert round_trip.data_scale == 18


def test_hadoop_and_spark_catalog_cache_and_invalidation() -> None:
    hive_api = _make_hive_api(dry_run=False)
    col = ColumnSpec(ColumnDialect.HADOOP, "id", HADOOP_TYPE_BIGINT)
    part_col = ColumnSpec(ColumnDialect.HADOOP, "goe_part_m_dt", HADOOP_TYPE_STRING)
    hive_api.execute_ddl = MagicMock(return_value=["DDL"])
    hive_api._fetch_table_exists = MagicMock(return_value=True)
    hive_api._fetch_columns = MagicMock(return_value=[col, part_col])
    hive_api._fetch_partition_columns = MagicMock(return_value=[part_col])
    hive_api._fetch_table_size = MagicMock(return_value=4096)

    assert hive_api.table_exists("sh_test", "sales") is True
    assert hive_api.table_exists("sh_test", "sales") is True
    assert hive_api._fetch_table_exists.call_count == 1

    assert hive_api.get_columns("sh_test", "sales") == [col, part_col]
    assert hive_api.get_columns("sh_test", "sales") == [col, part_col]
    assert hive_api._fetch_columns.call_count == 1

    assert hive_api.get_partition_columns("sh_test", "sales") == [part_col]
    assert hive_api.get_partition_columns("sh_test", "sales") == [part_col]
    assert hive_api._fetch_partition_columns.call_count == 1

    assert hive_api.get_table_size("sh_test", "sales") == 4096
    assert hive_api.get_table_size("sh_test", "sales") == 4096
    assert hive_api._fetch_table_size.call_count == 1

    hive_api.add_columns("sh_test", "sales", [("extra", "string")])
    assert hive_api.get_columns("sh_test", "sales") == [col, part_col]
    assert hive_api._fetch_columns.call_count == 2

    hive_api._fetch_table_exists.return_value = False
    hive_api.drop_table("sh_test", "sales", purge=True)
    assert hive_api.table_exists("sh_test", "sales") is False
    assert hive_api._fetch_table_exists.call_count == 2

    spark_api = _make_spark_api(dry_run=False)
    spark_api._fetch_table_exists = MagicMock(return_value=True)
    spark_api._fetch_columns = MagicMock(return_value=[col])
    assert spark_api.table_exists("sh_test", "sales") is True
    assert spark_api.table_exists("sh_test", "sales") is True
    assert spark_api._fetch_table_exists.call_count == 1
    assert spark_api.get_columns("sh_test", "sales") == [col]
    assert spark_api.get_columns("sh_test", "sales") == [col]
    assert spark_api._fetch_columns.call_count == 1


def test_hadoop_warm_schema() -> None:
    hive_api = _make_hive_api(dry_run=False)
    hive_api.list_tables = MagicMock(return_value=["sales", "customers"])
    hive_api._fetch_table_exists = MagicMock(side_effect=AssertionError("Should hit warmed cache"))

    warmed = hive_api.warm_schema("sh_test")
    assert warmed == 2
    assert hive_api.table_exists("sh_test", "sales") is True
    assert hive_api.table_exists("sh_test", "customers") is True


def test_hive_table_create_bucketing_and_staged_load_insert() -> None:
    table = _make_hive_table()
    cols = [
        ColumnSpec(ColumnDialect.HADOOP, "cust_id", HADOOP_TYPE_BIGINT),
        ColumnSpec(ColumnDialect.HADOOP, "name", HADOOP_TYPE_VARCHAR, data_length=100),
        ColumnSpec(
            ColumnDialect.HADOOP,
            "goe_part_10_cust_id",
            HADOOP_TYPE_STRING,
            partition_info=ColumnPartitionSpec(position=1, granularity="10", digits=6, source_column_name="cust_id"),
        ),
    ]
    table.set_columns(cols)
    table._orchestration_config.storage_format = FILE_STORAGE_FORMAT_ORC
    table._get_data_table_hdfs_dir = MagicMock(return_value="hdfs:///data/sh_test/sales")

    ddl_cmds = table.create_backend_table()
    assert any("PARTITIONED BY (`goe_part_10_cust_id` STRING)" in cmd for cmd in ddl_cmds)
    assert any("STORED AS ORC" in cmd for cmd in ddl_cmds)
    assert any("'orc.compress'='ZLIB'" in cmd for cmd in ddl_cmds)
    assert "PMOD(HASH(" in HASH_BUCKET_EXPRESSION

    rdbms_cols = [
        ColumnSpec(ColumnDialect.CANONICAL, "cust_id", GOE_TYPE_INTEGER_8),
        ColumnSpec(ColumnDialect.CANONICAL, "name", GOE_TYPE_VARIABLE_STRING, data_length=100),
    ]
    staging_cols = [
        ColumnSpec(ColumnDialect.HADOOP, "cust_id", HADOOP_TYPE_BIGINT),
        ColumnSpec(ColumnDialect.HADOOP, "name", HADOOP_TYPE_VARCHAR, data_length=100),
    ]
    table.set_final_table_casts(rdbms_cols, staging_cols)
    table._db_api.get_session_option = MagicMock(return_value="true")
    executed_dml: list = []
    table._execute_dml = lambda sqls, **kwargs: executed_dml.extend(sqls) or sqls
    table.load_final_table()
    assert len(executed_dml) == 1
    assert "INSERT INTO `sh_test`.`sales` PARTITION (`goe_part_10_cust_id`)" in executed_dml[0]


def test_impala_table_create_sort_by_and_incremental_stats() -> None:
    table = _make_impala_table()
    cols = [
        ColumnSpec(ColumnDialect.HADOOP, "cust_id", HADOOP_TYPE_BIGINT),
        ColumnSpec(ColumnDialect.HADOOP, "order_ts", HADOOP_TYPE_STRING),
    ]
    table.set_columns(cols)
    table._sort_columns = ["order_ts"]
    table._user_requested_storage_format = FILE_STORAGE_FORMAT_PARQUET
    table._get_data_table_hdfs_dir = MagicMock(return_value="hdfs:///data/sh_test/sales")
    table._db_api.transactional_tables_default = MagicMock(return_value=True)
    table.target_version = MagicMock(return_value="3.4.0")

    ddl_cmds = table.create_backend_table()
    assert any("CREATE EXTERNAL TABLE `sh_test`.`sales`" in cmd for cmd in ddl_cmds)
    assert any("SORT BY (`order_ts`)" in cmd for cmd in ddl_cmds)
    assert any("'external.table.purge'='TRUE'" in cmd for cmd in ddl_cmds)

    rdbms_cols = [
        ColumnSpec(ColumnDialect.CANONICAL, "cust_id", GOE_TYPE_INTEGER_8),
        ColumnSpec(ColumnDialect.CANONICAL, "order_ts", GOE_TYPE_VARIABLE_STRING, data_length=30),
    ]
    staging_cols = [
        ColumnSpec(ColumnDialect.HADOOP, "cust_id", HADOOP_TYPE_BIGINT),
        ColumnSpec(ColumnDialect.HADOOP, "order_ts", HADOOP_TYPE_STRING),
    ]
    table.set_final_table_casts(rdbms_cols, staging_cols)
    executed_dml: list = []
    table._execute_dml = lambda sqls, **kwargs: executed_dml.extend(sqls) or sqls
    table.load_final_table()
    assert len(executed_dml) == 1
    assert "INSERT INTO `sh_test`.`sales`" in executed_dml[0]


def _make_hive_api(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_HIVE_ENV)
    return create_backend_api(
        DBTYPE_HIVE,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )


def _make_impala_api(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_IMPALA_ENV)
    return create_backend_api(
        DBTYPE_IMPALA,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )


def _make_spark_api(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_HIVE_ENV)
    config.offload_transport_spark_thrift_host = "spark-thrift-host"
    config.offload_transport_spark_thrift_port = 10016
    return create_backend_api(
        DBTYPE_SPARK,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )


def _make_hive_table(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_HIVE_ENV)
    return create_backend_table(
        "sh_test",
        "sales",
        DBTYPE_HIVE,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )


def _make_impala_table(dry_run: bool = True):
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_IMPALA_ENV)
    return create_backend_table(
        "sh_test",
        "sales",
        DBTYPE_IMPALA,
        config,
        messages,
        dry_run=dry_run,
        do_not_connect=True,
    )
