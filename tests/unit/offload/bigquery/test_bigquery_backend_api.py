# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BackendBigQueryApi capabilities, CachedBackendCatalog integration, warm_schema, and execute_ingest."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from goe.offload.backend_cache import BackendTableSnapshot
from goe.offload.backend_capabilities import BackendCapabilities
from goe.offload.bigquery.bigquery_backend_api import BackendBigQueryApi
from goe.offload.bigquery.ingest_strategy import BigQueryLoadRequest, GcsLoadJobStrategy
from goe.offload.offload_constants import DBTYPE_BIGQUERY, FILE_STORAGE_FORMAT_PARQUET
from goe.offload.offload_messages import OffloadMessages
from goe.offload.schema.column_spec import BIGQUERY_TYPE_INT64, BIGQUERY_TYPE_NUMERIC, ColumnDialect, ColumnSpec
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_bigquery_api_uses_backend_capabilities_and_cached_catalog() -> None:
    """BackendBigQueryApi exposes BackendCapabilities.for_bigquery() and caches/evicts native handles via catalog."""
    options = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    api = BackendBigQueryApi(options, DBTYPE_BIGQUERY, messages, dry_run=True, do_not_connect=True)
    api._client = MagicMock(project="bq-project")

    assert api.capabilities == BackendCapabilities.for_bigquery()

    fake_table = MagicMock(
        schema=[SimpleNamespace(name="ID", field_type="INT64", is_nullable=False)],
        clustering_fields=["ID"],
    )
    api._client.get_table.return_value = fake_table

    first = api._get_bq_table("PROD_DS", "ORDERS")
    second = api._get_bq_table("PROD_DS", "ORDERS")
    assert first is fake_table
    assert second is fake_table
    api._client.get_table.assert_called_once_with("bq-project.PROD_DS.ORDERS")
    assert api.catalog.get_snapshot("PROD_DS", "ORDERS") is not None

    api.add_columns("PROD_DS", "ORDERS", [("AMOUNT", "NUMERIC")])
    assert api.catalog.get_snapshot("PROD_DS", "ORDERS") is None

    api._get_bq_table("PROD_DS", "ORDERS")
    assert api.catalog.get_snapshot("PROD_DS", "ORDERS") is not None
    api.alter_sort_columns("PROD_DS", "ORDERS", ["ID", "AMOUNT"])
    assert api.catalog.get_snapshot("PROD_DS", "ORDERS") is None

    api._get_bq_table("PROD_DS", "ORDERS")
    assert api.catalog.get_snapshot("PROD_DS", "ORDERS") is not None
    api.drop_table("PROD_DS", "ORDERS")
    assert api.catalog.get_snapshot("PROD_DS", "ORDERS") is None


def test_bigquery_api_warm_schema_populates_catalog_in_two_queries() -> None:
    """warm_schema batch-loads dataset tables and columns in two INFORMATION_SCHEMA queries."""
    options = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    api = BackendBigQueryApi(options, DBTYPE_BIGQUERY, messages, dry_run=False, do_not_connect=True)
    api._client = MagicMock(project="bq-project")

    tables_rows = [
        ("ORDERS", "BASE TABLE"),
        ("ORDERS_VW", "VIEW"),
    ]
    columns_rows = [
        ("ORDERS", "ID", "INT64", "NO"),
        ("ORDERS", "AMOUNT", "NUMERIC(12, 2)", "YES"),
        ("ORDERS_VW", "ID", "INT64", "YES"),
    ]

    with patch.object(api, "execute_query_fetch_all", side_effect=[tables_rows, columns_rows]) as fetch_mock:
        warmed = api.warm_schema("PROD_DS")

    assert warmed == 2
    assert fetch_mock.call_count == 2
    assert "INFORMATION_SCHEMA.TABLES" in fetch_mock.call_args_list[0].args[0]
    assert "INFORMATION_SCHEMA.COLUMNS" in fetch_mock.call_args_list[1].args[0]

    assert api.table_exists("PROD_DS", "ORDERS") is True
    assert api.table_exists("PROD_DS", "ORDERS_VW") is False
    cols = api.get_columns("PROD_DS", "ORDERS")
    assert len(cols) == 2
    assert cols[0].name == "ID"
    assert cols[0].data_type == BIGQUERY_TYPE_INT64
    assert cols[0].nullable is False
    assert cols[1].name == "AMOUNT"
    assert cols[1].data_type == BIGQUERY_TYPE_NUMERIC
    assert cols[1].data_precision == 12
    assert cols[1].data_scale == 2
    api._client.get_table.assert_not_called()


def test_bigquery_api_execute_ingest_invalidates_table_size_cache() -> None:
    """execute_ingest runs the strategy and resets size_calculated while keeping cached column definitions."""
    options = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    api = BackendBigQueryApi(options, DBTYPE_BIGQUERY, messages, dry_run=False, do_not_connect=True)
    api._client = MagicMock(project="bq-project")
    api._client.load_table_from_uri.return_value = MagicMock(job_id="job-99", output_rows=10, output_bytes=2048)

    cached_col = ColumnSpec(ColumnDialect.BIGQUERY, "ID", data_type=BIGQUERY_TYPE_INT64, nullable=False)
    api.catalog.put_snapshot(
        BackendTableSnapshot(
            db_name="PROD_DS",
            table_name="ORDERS",
            exists=True,
            columns=(cached_col,),
            size_bytes=1024,
            size_calculated=True,
            row_count=5,
            row_count_calculated=True,
            fetched_at=time.monotonic(),
        )
    )

    request = BigQueryLoadRequest(
        project="bq-project",
        dataset="PROD_DS",
        table="ORDERS",
        staging_format=FILE_STORAGE_FORMAT_PARQUET,
        source_uri="gs://b/prod_ds_load/orders/part*",
    )
    result = api.execute_ingest(request, strategy=GcsLoadJobStrategy())
    assert result.job_id == "job-99"
    assert result.output_rows == 10

    snap = api.catalog.get_snapshot("PROD_DS", "ORDERS")
    assert snap is not None
    assert snap.columns == (cached_col,)
    assert snap.size_calculated is False
    assert snap.size_bytes is None
    assert snap.row_count_calculated is False
