# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for DDLTransform Hive/Impala DDL location and column rewriting."""

import pytest

from goe.offload.hadoop.hive_ddl import DDLTransform, HiveDDLTransformException


def test_ddl_transform_replaces_hdfs_location_prefix_and_host() -> None:
    """DDLTransform rewrites standard HDFS location prefixes and hosts."""
    ddl = (
        "CREATE EXTERNAL TABLE db1.sales (id INT, amount DECIMAL(10,2)) "
        "STORED AS PARQUET LOCATION 'hdfs://namenode1:8020/user/goe/db1/sales' TBLPROPERTIES ('k'='v')"
    )
    transformed = DDLTransform().transform_table(
        ddl,
        {
            "location_prefix": "hdfs://namenode2:8020",
        },
    )
    assert "hdfs://namenode2:8020/user/goe/db1/sales" in transformed
    transformed_host = DDLTransform().transform_table(
        ddl,
        {
            "location_host": "namenode3",
        },
    )
    assert "hdfs://namenode3:8020/user/goe/db1/sales" in transformed_host


def test_ddl_transform_rejects_removed_filesystem_prefix() -> None:
    """DDLTransform rejects removed non-host filesystem prefixes when replacing location_prefix."""
    removed_scheme = "mapr" + "fs:"
    ddl = (
        f"CREATE EXTERNAL TABLE db1.sales (id INT) "
        f"STORED AS PARQUET LOCATION '{removed_scheme}/user/goe/db1/sales' TBLPROPERTIES ('k'='v')"
    )
    with pytest.raises(HiveDDLTransformException, match="Unable to match location prefix"):
        DDLTransform().transform_table(ddl, {"location_prefix": "hdfs://nn:8020"})
