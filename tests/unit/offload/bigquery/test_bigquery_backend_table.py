# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BackendBigQueryTable ingest strategy selection and direct-to-target eligibility."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyarrow as pa
from google.cloud import bigquery

from goe.offload.bigquery.bigquery_backend_table import BackendBigQueryTable
from goe.offload.bigquery.ingest_strategy import (
    DirectArrowUploadStrategy,
    GcsLoadJobStrategy,
    StorageWriteStreamStrategy,
)
from goe.offload.offload_constants import (
    DBTYPE_BIGQUERY,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.offload_messages import OffloadMessages
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_STRING,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
)
from tests.unit.test_functions import (
    FAKE_ORACLE_BQ_ENV,
    build_mock_offload_operation,
    build_mock_options,
)


def test_load_native_load_table_delegates_to_gcs_load_job_strategy() -> None:
    """_create_load_table in NATIVE mode constructs a WRITE_TRUNCATE request and delegates to execute_ingest."""
    table = _build_table(dry_run=True)
    staging_file = SimpleNamespace(file_format=FILE_STORAGE_FORMAT_PARQUET)
    with patch.object(table._db_api, "execute_ingest", wraps=table._db_api.execute_ingest) as exec_ingest:
        cmds = table._create_load_table(staging_file)
    assert exec_ingest.call_count == 1
    request = exec_ingest.call_args.args[0]
    strategy = exec_ingest.call_args.kwargs.get("strategy") or exec_ingest.call_args.args[1]
    assert isinstance(strategy, GcsLoadJobStrategy)
    assert request.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    assert request.dataset == "target_ds_load"
    assert request.table == "sales"
    assert cmds == [
        "BigQuery load job: gs://b/target_ds_load/sales/part* -> "
        "bq-project.target_ds_load.sales (format=PARQUET, write_disposition=WRITE_TRUNCATE)"
    ]


def test_direct_target_ingest_selects_direct_arrow_below_10mb() -> None:
    """ingest_direct_to_final_table selects DirectArrowUploadStrategy for < 10 MiB Arrow payloads."""
    table = _build_table(dry_run=True)
    arrow_table = pa.table({"ID": [1, 2], "STATUS": ["OPEN", "CLOSED"]})
    staging_file = SimpleNamespace(file_format=FILE_STORAGE_FORMAT_PARQUET)

    with patch.object(table._db_api, "execute_ingest", wraps=table._db_api.execute_ingest) as exec_ingest:
        result = table.ingest_direct_to_final_table(
            staging_file,
            arrow_source=arrow_table,
            payload_bytes=512_000,
        )

    strategy = exec_ingest.call_args.kwargs["strategy"]
    request = exec_ingest.call_args.args[0]
    assert isinstance(strategy, DirectArrowUploadStrategy)
    assert request.dataset == "target_ds"
    assert request.table == "sales"
    assert request.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert result.strategy_name == "DIRECT_ARROW"


def test_direct_target_ingest_selects_gcs_load_job_above_10mb() -> None:
    """ingest_direct_to_final_table selects GcsLoadJobStrategy when payload_bytes >= 10 MiB."""
    table = _build_table(dry_run=True)
    arrow_table = pa.table({"ID": [1, 2]})
    staging_file = SimpleNamespace(file_format=FILE_STORAGE_FORMAT_PARQUET)

    with patch.object(table._db_api, "execute_ingest", wraps=table._db_api.execute_ingest) as exec_ingest:
        result = table.ingest_direct_to_final_table(
            staging_file,
            arrow_source=arrow_table,
            payload_bytes=25 * 1024 * 1024,
        )

    strategy = exec_ingest.call_args.kwargs["strategy"]
    request = exec_ingest.call_args.args[0]
    assert isinstance(strategy, GcsLoadJobStrategy)
    assert request.dataset == "target_ds"
    assert request.table == "sales"
    assert request.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert result.strategy_name == "GCS_LOAD_JOB"


def test_direct_target_ingest_selects_storage_write_when_configured() -> None:
    """ingest_direct_to_final_table selects StorageWriteStreamStrategy when ingest_mode is STORAGE_WRITE."""
    table = _build_table(dry_run=True)
    table._orchestration_config.bigquery_ingest_mode = "STORAGE_WRITE"
    batch = pa.record_batch([[1, 2]], names=["ID"])
    reader = pa.RecordBatchReader.from_batches(batch.schema, [batch])

    with patch.object(table._db_api, "execute_ingest", wraps=table._db_api.execute_ingest) as exec_ingest:
        result = table.ingest_direct_to_final_table(
            SimpleNamespace(file_format=FILE_STORAGE_FORMAT_PARQUET),
            arrow_source=reader,
            payload_bytes=128 * 1024 * 1024,
        )

    strategy = exec_ingest.call_args.kwargs["strategy"]
    assert isinstance(strategy, StorageWriteStreamStrategy)
    assert result.strategy_name == "STORAGE_WRITE"


def test_can_ingest_direct_to_target_false_for_udf_or_subchunk_or_avro() -> None:
    """can_ingest_direct_to_target returns False when Avro, subchunking, or partition UDFs are active."""
    table = _build_table(dry_run=True)
    base_cols = [
        ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64, nullable=False),
        ColumnSpec(ColumnDialect.BIGQUERY, "STATUS", BIGQUERY_TYPE_STRING, nullable=True),
    ]
    table.set_columns(base_cols)

    parquet_staging = SimpleNamespace(file_format=FILE_STORAGE_FORMAT_PARQUET)
    avro_staging = SimpleNamespace(file_format=FILE_STORAGE_FORMAT_AVRO)

    assert table.can_ingest_direct_to_target(parquet_staging) is True
    assert table.can_ingest_direct_to_target(avro_staging) is False

    table._user_requested_offload_chunk_column = "ID"
    assert table.can_ingest_direct_to_target(parquet_staging) is False
    table._user_requested_offload_chunk_column = None

    udf_cols = [
        ColumnSpec(
            ColumnDialect.BIGQUERY,
            "ID",
            BIGQUERY_TYPE_INT64,
            partition_info=ColumnPartitionSpec(position=0, source_column_name="ID", function="my_ds.part_udf"),
        ),
    ]
    table.set_columns(udf_cols)
    assert table.can_ingest_direct_to_target(parquet_staging) is False


def _build_table(*, dry_run: bool = True) -> BackendBigQueryTable:
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    operation = build_mock_offload_operation()
    operation.target_owner = "target_ds"
    operation.offload_chunk_column = None
    operation.impala_insert_hint = None
    operation.bucket_hash_col = None
    operation.ipa_predicate_type = None
    operation.offload_partition_functions = None
    operation.offload_distribute_enabled = False
    operation.offload_stats_method = None
    operation.sort_columns = None
    table = BackendBigQueryTable(
        "target_ds",
        "sales",
        DBTYPE_BIGQUERY,
        config,
        messages,
        orchestration_operation=operation,
        dry_run=dry_run,
        do_not_connect=True,
    )
    table._db_api._client = MagicMock(project="bq-project")
    return table
