# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BackendTableInterface composition with load, merge, and catalog services."""

from goe.offload.backend_load import FinalTableMerger, StagingLoadService
from goe.offload.offload_constants import DBTYPE_BIGQUERY
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_backend_table
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_STRING,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
)
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_backend_table_composes_staging_and_merge_services() -> None:
    table = _make_bq_table()
    assert isinstance(table._staging_service, StagingLoadService)
    assert isinstance(table._final_merger, FinalTableMerger)


def test_backend_table_drop_state_invalidates_catalog_table() -> None:
    table = _make_bq_table()
    col = ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64)
    loads = 0

    def _load(db_name: str, table_name: str):
        nonlocal loads
        loads += 1
        return [col]

    table._db_api.catalog.get_columns("test_db", "test_tbl", _load)
    assert loads == 1

    table._drop_state()
    table._db_api.catalog.get_columns("test_db", "test_tbl", _load)
    assert loads == 2


def test_backend_table_synthetic_date_as_string_delegates_to_ddl_compiler() -> None:
    table = _make_bq_table()
    expr = table._gen_synthetic_part_date_as_string_sql_expr("dt_col", "M", "CAST(`dt_col` AS DATE)")
    assert "CONCAT(" in expr
    assert "'-'" in expr


def test_backend_table_final_insert_sqls_delegates_to_final_merger() -> None:
    table = _make_bq_table()
    col = ColumnSpec(
        ColumnDialect.BIGQUERY,
        "ID",
        BIGQUERY_TYPE_INT64,
        partition_info=ColumnPartitionSpec(position=0, granularity=10, range_start=0, range_end=100),
    )
    table.set_columns([col])
    sqls, query_options = table._gen_final_insert_sqls(
        [("`ID`", "ID")],
        threshold_clauses=["`ID` < 50"],
    )
    assert len(sqls) == 1
    assert "WHERE" in sqls[0]
    assert "`ID` < 50" in sqls[0]
    assert query_options is None or isinstance(query_options, dict)


def test_backend_table_verification_sql_delegates_to_staging_service() -> None:
    table = _make_bq_table()
    sql = table._validate_final_table_casts_verification_sql(
        ["`ID`"],
        ["(`ID` IS NOT NULL AND SAFE_CAST(`ID` AS INT64) IS NULL)"],
        limit=25,
    )
    assert sql.startswith("SELECT `ID`\nFROM   ")
    assert sql.endswith("\nLIMIT 25")
    col = ColumnSpec(ColumnDialect.BIGQUERY, "NAME", BIGQUERY_TYPE_STRING, nullable=False)
    table.set_columns([col])
    rules = table._validate_staged_data_rules([], [col], [col])
    assert any(rule.column_name == "NAME" and rule.fatal for rule in rules)


def _make_bq_table():
    messages = OffloadMessages()
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    return create_backend_table(
        "test_db",
        "test_tbl",
        DBTYPE_BIGQUERY,
        config,
        messages,
        dry_run=True,
        do_not_connect=True,
    )
