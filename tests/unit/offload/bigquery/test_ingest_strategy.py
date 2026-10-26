# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BigQuery ingest strategies (GCS load job, Direct Arrow upload, Storage Write stream)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest
from google.cloud import bigquery

from goe.offload.backend_api import BackendApiException
from goe.offload.bigquery.ingest_strategy import (
    DIRECT_ARROW_UPLOAD_THRESHOLD_BYTES,
    BigQueryIngestStrategyProtocol,
    BigQueryLoadRequest,
    DirectArrowUploadStrategy,
    GcsLoadJobStrategy,
    StorageWriteStreamStrategy,
    select_bigquery_ingest_strategy,
)
from goe.offload.offload_constants import FILE_STORAGE_FORMAT_AVRO, FILE_STORAGE_FORMAT_PARQUET

KMS_KEY = "projects/kms-project/locations/US/keyRings/ring-name/cryptoKeys/key-name"


def test_gcs_load_job_strategy_executes_and_formats_golden_command() -> None:
    """GcsLoadJobStrategy formats the golden command, configures LoadJobConfig, and supports dry_run."""
    strategy = GcsLoadJobStrategy()
    assert isinstance(strategy, BigQueryIngestStrategyProtocol)

    request = BigQueryLoadRequest(
        project="bq-project",
        dataset="target_ds_load",
        table="sales_rbo",
        staging_format=FILE_STORAGE_FORMAT_AVRO,
        source_uri="gs://b/target_ds_load/sales_rbo/part*",
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        kms_key_name=KMS_KEY,
        labels={"goe_version": "2_0"},
        dry_run=True,
    )
    bq_client = MagicMock(project="bq-project")
    logged: list[str] = []
    dry_result = strategy.execute(request, bq_client=bq_client, log_fn=lambda msg, **_kw: logged.append(msg))
    assert dry_result.strategy_name == "GCS_LOAD_JOB"
    assert dry_result.commands == (
        "BigQuery load job: gs://b/target_ds_load/sales_rbo/part* -> "
        "bq-project.target_ds_load.sales_rbo (format=AVRO, write_disposition=WRITE_TRUNCATE)",
    )
    assert logged == list(dry_result.commands)
    bq_client.load_table_from_uri.assert_not_called()

    exec_request = BigQueryLoadRequest(
        project="bq-project",
        dataset="target_ds",
        table="sales_rbo",
        staging_format=FILE_STORAGE_FORMAT_PARQUET,
        source_uri="gs://b/target_ds_load/sales_rbo/part*",
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        kms_key_name=KMS_KEY,
        labels={"goe_version": "2_0"},
        dry_run=False,
    )
    load_job = MagicMock(job_id="job-load-1", output_rows=42, output_bytes=4096)
    bq_client.load_table_from_uri.return_value = load_job
    result = strategy.execute(exec_request, bq_client=bq_client)
    assert result.job_id == "job-load-1"
    assert result.output_rows == 42
    assert result.output_bytes == 4096
    uri, dest = bq_client.load_table_from_uri.call_args.args[:2]
    job_config = bq_client.load_table_from_uri.call_args.kwargs["job_config"]
    assert uri == "gs://b/target_ds_load/sales_rbo/part*"
    assert dest == "bq-project.target_ds.sales_rbo"
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert set(job_config.decimal_target_types) == {"NUMERIC", "BIGNUMERIC", "STRING"}
    assert job_config.destination_encryption_configuration.kms_key_name == KMS_KEY


def test_direct_arrow_upload_strategy_loads_table_and_reader() -> None:
    """DirectArrowUploadStrategy uploads pa.Table and pa.RecordBatchReader via load_table_from_dataframe."""
    strategy = DirectArrowUploadStrategy()
    assert isinstance(strategy, BigQueryIngestStrategyProtocol)

    arrow_table = pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]})
    bq_client = MagicMock(project="bq-project")
    load_job = MagicMock(job_id="job-arrow-1", output_rows=3, output_bytes=128)
    bq_client.load_table_from_dataframe.return_value = load_job

    req_table = BigQueryLoadRequest(
        project="bq-project",
        dataset="target_ds",
        table="orders",
        arrow_source=arrow_table,
        payload_bytes=arrow_table.nbytes,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        kms_key_name=KMS_KEY,
        labels={"goe_command": "offload"},
    )
    res_table = strategy.execute(req_table, bq_client=bq_client)
    assert res_table.strategy_name == "DIRECT_ARROW"
    assert res_table.output_rows == 3
    assert res_table.job_id == "job-arrow-1"
    df_arg, dest_arg = bq_client.load_table_from_dataframe.call_args.args[:2]
    job_cfg = bq_client.load_table_from_dataframe.call_args.kwargs["job_config"]
    assert isinstance(df_arg, pa.Table)
    assert df_arg.num_rows == 3
    assert dest_arg == "bq-project.target_ds.orders"
    assert job_cfg.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert set(job_cfg.decimal_target_types) == {"NUMERIC", "BIGNUMERIC", "STRING"}
    assert job_cfg.destination_encryption_configuration.kms_key_name == KMS_KEY
    bq_client.load_table_from_uri.assert_not_called()

    reader = pa.RecordBatchReader.from_batches(arrow_table.schema, arrow_table.to_batches())
    req_reader = BigQueryLoadRequest(
        project="bq-project",
        dataset="target_ds",
        table="orders",
        arrow_source=reader,
        payload_bytes=arrow_table.nbytes,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    res_reader = strategy.execute(req_reader, bq_client=bq_client)
    assert res_reader.output_rows == 3
    assert bq_client.load_table_from_dataframe.call_count == 2


def test_storage_write_stream_strategy_pending_finalize_commit() -> None:
    """StorageWriteStreamStrategy creates a PENDING stream, appends Arrow IPC batches, finalizes, and commits."""
    strategy = StorageWriteStreamStrategy()
    assert isinstance(strategy, BigQueryIngestStrategyProtocol)

    schema = pa.schema([("id", pa.int64()), ("amount", pa.string())])
    batch1 = pa.record_batch([[1, 2], ["10.00", "20.00"]], schema=schema)
    batch2 = pa.record_batch([[3], ["30.00"]], schema=schema)
    reader = pa.RecordBatchReader.from_batches(schema, [batch1, batch2])

    fake_types = _build_fake_bq_storage_types()
    write_client = MagicMock()
    write_client.create_write_stream.return_value = SimpleNamespace(
        name="projects/bq-project/datasets/target_ds/tables/orders/streams/s1"
    )
    write_client.append_rows.side_effect = lambda req_iter: [
        SimpleNamespace(error=SimpleNamespace(code=0, message="")) for _ in list(req_iter)
    ]
    write_client.batch_commit_write_streams.return_value = SimpleNamespace(stream_errors=[])

    request = BigQueryLoadRequest(
        project="bq-project",
        dataset="target_ds",
        table="orders",
        arrow_source=reader,
    )
    bq_client = MagicMock(project="bq-project")

    with (
        patch("goe.offload.bigquery.ingest_strategy._bq_storage", new=SimpleNamespace(BigQueryWriteClient=MagicMock())),
        patch("goe.offload.bigquery.ingest_strategy._bq_storage_types", new=fake_types),
    ):
        result = strategy.execute(request, bq_client=bq_client, write_client=write_client)

    assert result.strategy_name == "STORAGE_WRITE"
    assert result.output_rows == 3
    assert result.output_bytes is not None and result.output_bytes > 0
    assert result.stream_names == ("projects/bq-project/datasets/target_ds/tables/orders/streams/s1",)
    write_client.create_write_stream.assert_called_once()
    write_client.finalize_write_stream.assert_called_once_with(
        name="projects/bq-project/datasets/target_ds/tables/orders/streams/s1"
    )
    write_client.batch_commit_write_streams.assert_called_once_with(
        parent="projects/bq-project/datasets/target_ds/tables/orders",
        write_streams=["projects/bq-project/datasets/target_ds/tables/orders/streams/s1"],
    )

    write_client.batch_commit_write_streams.return_value = SimpleNamespace(
        stream_errors=[SimpleNamespace(error_message="stream already committed")]
    )
    with (
        patch("goe.offload.bigquery.ingest_strategy._bq_storage", new=SimpleNamespace(BigQueryWriteClient=MagicMock())),
        patch("goe.offload.bigquery.ingest_strategy._bq_storage_types", new=fake_types),
        pytest.raises(BackendApiException, match="stream already committed"),
    ):
        strategy.execute(
            BigQueryLoadRequest(
                project="bq-project",
                dataset="target_ds",
                table="orders",
                arrow_source=pa.Table.from_batches([batch1]),
            ),
            bq_client=bq_client,
            write_client=write_client,
        )


def test_strategy_selection_by_mode_and_payload_size() -> None:
    """select_bigquery_ingest_strategy routes by ingest_mode, Arrow availability, and 10 MiB cutoff."""
    s_small = select_bigquery_ingest_strategy(
        ingest_mode="AUTO",
        payload_bytes=512 * 1024,
        has_arrow_source=True,
    )
    assert isinstance(s_small, DirectArrowUploadStrategy)

    s_exact_threshold = select_bigquery_ingest_strategy(
        ingest_mode="AUTO",
        payload_bytes=DIRECT_ARROW_UPLOAD_THRESHOLD_BYTES,
        has_arrow_source=True,
    )
    assert isinstance(s_exact_threshold, GcsLoadJobStrategy)

    s_large = select_bigquery_ingest_strategy(
        ingest_mode="AUTO",
        payload_bytes=25 * 1024 * 1024,
        has_arrow_source=True,
    )
    assert isinstance(s_large, GcsLoadJobStrategy)

    s_uri_only = select_bigquery_ingest_strategy(
        ingest_mode="AUTO",
        payload_bytes=1024,
        has_arrow_source=False,
    )
    assert isinstance(s_uri_only, GcsLoadJobStrategy)

    s_storage_write = select_bigquery_ingest_strategy(
        ingest_mode="STORAGE_WRITE",
        payload_bytes=50 * 1024 * 1024,
        has_arrow_source=True,
    )
    assert isinstance(s_storage_write, StorageWriteStreamStrategy)


def test_observability_spans_recorded() -> None:
    """All strategies invoke traced_bigquery_job and record metadata."""
    bq_client = MagicMock(project="bq-project")
    bq_client.load_table_from_uri.return_value = MagicMock(job_id="j1", output_rows=5, output_bytes=100)
    with patch("goe.offload.bigquery.ingest_strategy.traced_bigquery_job") as traced_mock:
        GcsLoadJobStrategy().execute(
            BigQueryLoadRequest(
                project="bq-project",
                dataset="ds",
                table="tbl",
                source_uri="gs://b/p/part*",
            ),
            bq_client=bq_client,
        )
    traced_mock.assert_called_once_with("load", "bq-project")


def _build_fake_bq_storage_types() -> SimpleNamespace:
    class FakeWriteStream:
        class Type:
            PENDING = 1

        def __init__(self, *, type_: int) -> None:
            self.type_ = type_

    class FakeArrowSchema:
        def __init__(self, *, serialized_schema: bytes) -> None:
            self.serialized_schema = serialized_schema

    class FakeArrowRecordBatch:
        def __init__(self, *, serialized_record_batch: bytes, row_count: int) -> None:
            self.serialized_record_batch = serialized_record_batch
            self.row_count = row_count

    class FakeArrowData:
        def __init__(self) -> None:
            self.writer_schema: FakeArrowSchema | None = None
            self.rows: FakeArrowRecordBatch | None = None

    class FakeAppendRowsRequest:
        ArrowData = FakeArrowData

        def __init__(self, *, write_stream: str, arrow_rows: FakeArrowData) -> None:
            self.write_stream = write_stream
            self.arrow_rows = arrow_rows

    return SimpleNamespace(
        WriteStream=FakeWriteStream,
        ArrowSchema=FakeArrowSchema,
        ArrowRecordBatch=FakeArrowRecordBatch,
        AppendRowsRequest=FakeAppendRowsRequest,
    )
