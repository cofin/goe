# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Pluggable BigQuery data ingestion strategies (GCS Load Job, Direct Arrow Upload, Storage Write API)."""

from collections.abc import Callable
from typing import Any, Literal, Protocol, runtime_checkable

import pyarrow as pa
from google.cloud import bigquery

from goe.observability.bigquery import (
    record_bigquery_job_metadata,
    record_bigquery_stream_metadata,
    traced_bigquery_job,
)
from goe.offload.backend_api import BackendApiException
from goe.offload.bigquery.bigquery_load_job import (
    PARQUET_DECIMAL_TARGET_TYPES,
    build_staging_load_job_config,
)
from goe.offload.offload_constants import FILE_STORAGE_FORMAT_PARQUET
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.typing import FrozenBaseStruct
from goe.util.module_loader import import_optional

__all__ = [
    "DIRECT_ARROW_UPLOAD_THRESHOLD_BYTES",
    "BigQueryIngestMode",
    "BigQueryIngestStrategyProtocol",
    "BigQueryLoadRequest",
    "BigQueryLoadResult",
    "DirectArrowUploadStrategy",
    "GcsLoadJobStrategy",
    "StorageWriteStreamStrategy",
    "select_bigquery_ingest_strategy",
]

DIRECT_ARROW_UPLOAD_THRESHOLD_BYTES = 10 * 1024 * 1024

type BigQueryIngestMode = Literal["AUTO", "GCS_LOAD_JOB", "DIRECT_ARROW", "STORAGE_WRITE"]

_bq_storage = import_optional("google.cloud.bigquery_storage_v1")
_bq_storage_types = import_optional("google.cloud.bigquery_storage_v1.types")


class BigQueryLoadRequest(FrozenBaseStruct, frozen=True):
    """Immutable parameters describing a BigQuery load operation."""

    project: str
    dataset: str
    table: str
    staging_format: str = FILE_STORAGE_FORMAT_PARQUET
    source_uri: str | None = None
    arrow_source: Any = None
    payload_bytes: int | None = None
    write_disposition: str = bigquery.WriteDisposition.WRITE_TRUNCATE
    kms_key_name: str | None = None
    labels: dict[str, str] = {}
    dry_run: bool = False

    @property
    def destination(self) -> str:
        """Return the fully qualified project.dataset.table identifier."""
        return f"{self.project}.{self.dataset}.{self.table}"

    @property
    def table_path(self) -> str:
        """Return the Storage Write API resource path for the destination table."""
        return f"projects/{self.project}/datasets/{self.dataset}/tables/{self.table}"


class BigQueryLoadResult(FrozenBaseStruct, frozen=True):
    """Immutable execution summary returned by a BigQueryIngestStrategyProtocol."""

    strategy_name: str
    destination: str
    commands: tuple[str, ...]
    job_id: str | None = None
    output_rows: int | None = None
    output_bytes: int | None = None
    stream_names: tuple[str, ...] = ()


@runtime_checkable
class BigQueryIngestStrategyProtocol(Protocol):
    """Protocol implemented by all BigQuery data ingestion strategies."""

    strategy_name: str

    def execute(
        self,
        request: BigQueryLoadRequest,
        *,
        bq_client: Any,
        log_fn: Callable[..., None] | None = None,
        write_client: Any = None,
    ) -> BigQueryLoadResult:
        """Execute or dry-run the BigQuery ingestion request and return a BigQueryLoadResult."""


class GcsLoadJobStrategy:
    """Loads >= 10 MiB multi-file GCS Parquet or Avro objects via BigQuery batch load_table_from_uri."""

    strategy_name = "GCS_LOAD_JOB"

    @staticmethod
    def format_log_command(request: BigQueryLoadRequest) -> str:
        """Return the canonical log message for a GCS batch load job."""
        return (
            f"BigQuery load job: {request.source_uri} -> {request.destination} "
            f"(format={request.staging_format}, write_disposition={request.write_disposition})"
        )

    def execute(
        self,
        request: BigQueryLoadRequest,
        *,
        bq_client: Any,
        log_fn: Callable[..., None] | None = None,
        write_client: Any = None,
    ) -> BigQueryLoadResult:
        """Run a BigQuery load_table_from_uri job for staged GCS files."""
        if not request.source_uri:
            raise BackendApiException("GcsLoadJobStrategy requires a non-empty source_uri")
        job_config = build_staging_load_job_config(
            request.staging_format,
            request.kms_key_name,
            dict(request.labels),
            write_disposition=request.write_disposition,
        )
        cmd = self.format_log_command(request)
        if log_fn is not None:
            log_fn(cmd, detail=VERBOSE)
        if request.dry_run:
            return BigQueryLoadResult(
                strategy_name=self.strategy_name,
                destination=request.destination,
                commands=(cmd,),
            )
        assert bq_client is not None
        with traced_bigquery_job("load", bq_client.project) as bq_job:
            load_job = bq_client.load_table_from_uri(
                request.source_uri,
                request.destination,
                job_config=job_config,
            )
            load_job.result()
            record_bigquery_job_metadata(bq_job, load_job, "load")
            if log_fn is not None:
                log_fn(
                    f"BigQuery load job {load_job.job_id} loaded {load_job.output_rows} rows",
                    detail=VVERBOSE,
                )
            return BigQueryLoadResult(
                strategy_name=self.strategy_name,
                destination=request.destination,
                commands=(cmd,),
                job_id=getattr(load_job, "job_id", None),
                output_rows=getattr(load_job, "output_rows", None),
                output_bytes=getattr(load_job, "output_bytes", None),
            )


class DirectArrowUploadStrategy:
    """Uploads < 10 MiB Arrow tables or RecordBatchReaders directly without a GCS staging round-trip."""

    strategy_name = "DIRECT_ARROW"

    @staticmethod
    def format_log_command(request: BigQueryLoadRequest) -> str:
        """Return the canonical log message for a direct Arrow upload job."""
        return (
            f"BigQuery direct Arrow load: arrow_stream -> {request.destination} "
            f"(write_disposition={request.write_disposition})"
        )

    def execute(
        self,
        request: BigQueryLoadRequest,
        *,
        bq_client: Any,
        log_fn: Callable[..., None] | None = None,
        write_client: Any = None,
    ) -> BigQueryLoadResult:
        """Upload an in-memory Arrow Table or RecordBatchReader via load_table_from_dataframe."""
        if request.arrow_source is None:
            raise BackendApiException("DirectArrowUploadStrategy requires a non-None arrow_source")
        cmd = self.format_log_command(request)
        if log_fn is not None:
            log_fn(cmd, detail=VERBOSE)
        if request.dry_run:
            return BigQueryLoadResult(
                strategy_name=self.strategy_name,
                destination=request.destination,
                commands=(cmd,),
            )
        assert bq_client is not None
        arrow_table = self._coerce_arrow_table(request.arrow_source)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=request.write_disposition,
            decimal_target_types=PARQUET_DECIMAL_TARGET_TYPES,
            labels=dict(request.labels),
        )
        if request.kms_key_name:
            job_config.destination_encryption_configuration = bigquery.EncryptionConfiguration(
                kms_key_name=request.kms_key_name
            )
        with traced_bigquery_job("direct_arrow_load", bq_client.project) as bq_job:
            load_job = bq_client.load_table_from_dataframe(
                arrow_table,
                request.destination,
                job_config=job_config,
            )
            load_job.result()
            record_bigquery_job_metadata(bq_job, load_job, "direct_arrow_load")
            output_rows = getattr(load_job, "output_rows", arrow_table.num_rows)
            if log_fn is not None:
                log_fn(
                    f"BigQuery direct Arrow load job {load_job.job_id} loaded {output_rows} rows",
                    detail=VVERBOSE,
                )
            return BigQueryLoadResult(
                strategy_name=self.strategy_name,
                destination=request.destination,
                commands=(cmd,),
                job_id=getattr(load_job, "job_id", None),
                output_rows=output_rows,
                output_bytes=getattr(load_job, "output_bytes", arrow_table.nbytes),
            )

    @staticmethod
    def _coerce_arrow_table(source: Any) -> pa.Table:
        if isinstance(source, pa.Table):
            return source
        if isinstance(source, pa.RecordBatchReader):
            return source.read_all()
        if isinstance(source, pa.RecordBatch):
            return pa.Table.from_batches([source])
        raise BackendApiException(f"Unsupported Arrow source type: {type(source)}")


class StorageWriteStreamStrategy:
    """Streams Arrow IPC batches via BigQuery Storage Write API PENDING streams with atomic commit."""

    strategy_name = "STORAGE_WRITE"

    @staticmethod
    def format_log_command(request: BigQueryLoadRequest) -> str:
        """Return the canonical log message for a Storage Write API stream commit."""
        return f"BigQuery Storage Write PENDING stream: arrow_ipc -> {request.destination}"

    def execute(
        self,
        request: BigQueryLoadRequest,
        *,
        bq_client: Any,
        log_fn: Callable[..., None] | None = None,
        write_client: Any = None,
    ) -> BigQueryLoadResult:
        """Stream Arrow RecordBatches into a PENDING stream, finalize, and atomically commit."""
        if request.arrow_source is None:
            raise BackendApiException("StorageWriteStreamStrategy requires a non-None arrow_source")
        cmd = self.format_log_command(request)
        if log_fn is not None:
            log_fn(cmd, detail=VERBOSE)
        if request.dry_run:
            return BigQueryLoadResult(
                strategy_name=self.strategy_name,
                destination=request.destination,
                commands=(cmd,),
            )
        bq_storage = _bq_storage or import_optional("google.cloud.bigquery_storage_v1")
        bq_storage_types = _bq_storage_types or import_optional("google.cloud.bigquery_storage_v1.types")
        if bq_storage is None or bq_storage_types is None:
            raise BackendApiException("google-cloud-bigquery-storage is required for StorageWriteStreamStrategy")
        client = write_client or bq_storage.BigQueryWriteClient(credentials=getattr(bq_client, "_credentials", None))
        schema, batches = self._iter_arrow_batches(request.arrow_source)
        with traced_bigquery_job("storage_write", request.project) as bq_job:
            write_stream = client.create_write_stream(
                parent=request.table_path,
                write_stream=bq_storage_types.WriteStream(type_=bq_storage_types.WriteStream.Type.PENDING),
            )
            stream_name = str(write_stream.name)
            total_rows = 0
            total_bytes = 0
            requests = self._build_append_requests(
                bq_storage_types,
                stream_name,
                schema,
                batches,
            )
            responses = client.append_rows(iter(requests))
            for response in responses:
                error = getattr(response, "error", None)
                if error is not None and getattr(error, "code", 0) != 0:
                    raise BackendApiException(
                        f"BigQuery Storage Write append_rows error on {stream_name}: {error.message}"
                    )
            for req in requests:
                batch_rows = getattr(req.arrow_rows.rows, "row_count", 0)
                batch_bytes = len(getattr(req.arrow_rows.rows, "serialized_record_batch", b""))
                total_rows += int(batch_rows)
                total_bytes += int(batch_bytes)
            client.finalize_write_stream(name=stream_name)
            commit_resp = client.batch_commit_write_streams(
                parent=request.table_path,
                write_streams=[stream_name],
            )
            stream_errors = list(getattr(commit_resp, "stream_errors", None) or ())
            if stream_errors:
                messages = ", ".join(str(getattr(err, "error_message", err)) for err in stream_errors)
                raise BackendApiException(f"BigQuery Storage Write batch_commit_write_streams failed: {messages}")
            record_bigquery_stream_metadata(
                bq_job,
                request.project,
                stream_name,
                total_rows,
                total_bytes,
            )
            if log_fn is not None:
                log_fn(
                    f"BigQuery Storage Write stream {stream_name} committed {total_rows} rows",
                    detail=VVERBOSE,
                )
            return BigQueryLoadResult(
                strategy_name=self.strategy_name,
                destination=request.destination,
                commands=(cmd,),
                output_rows=total_rows,
                output_bytes=total_bytes,
                stream_names=(stream_name,),
            )

    @staticmethod
    def _iter_arrow_batches(source: Any) -> tuple[pa.Schema, list[pa.RecordBatch]]:
        if isinstance(source, pa.Table):
            return source.schema, source.to_batches()
        if isinstance(source, pa.RecordBatchReader):
            return source.schema, list(source)
        if isinstance(source, pa.RecordBatch):
            return source.schema, [source]
        raise BackendApiException(f"Unsupported Arrow source type for Storage Write: {type(source)}")

    @staticmethod
    def _build_append_requests(
        bq_storage_types: Any,
        stream_name: str,
        schema: pa.Schema,
        batches: list[pa.RecordBatch],
    ) -> list[Any]:
        serialized_schema = schema.serialize().to_pybytes()
        requests: list[Any] = []
        for idx, batch in enumerate(batches):
            if batch.num_rows == 0:
                continue
            arrow_rows = bq_storage_types.AppendRowsRequest.ArrowData()
            if idx == 0 or not requests:
                arrow_rows.writer_schema = bq_storage_types.ArrowSchema(serialized_schema=serialized_schema)
            arrow_rows.rows = bq_storage_types.ArrowRecordBatch(
                serialized_record_batch=batch.serialize().to_pybytes(),
                row_count=batch.num_rows,
            )
            req = bq_storage_types.AppendRowsRequest(
                write_stream=stream_name if (idx == 0 or not requests) else "",
                arrow_rows=arrow_rows,
            )
            requests.append(req)
        return requests


def select_bigquery_ingest_strategy(
    *,
    ingest_mode: str = "AUTO",
    payload_bytes: int | None = None,
    has_arrow_source: bool = False,
    threshold_bytes: int = DIRECT_ARROW_UPLOAD_THRESHOLD_BYTES,
) -> BigQueryIngestStrategyProtocol:
    """Select the BigQuery ingest strategy based on configured mode, Arrow availability, and payload size."""
    normalized_mode = (ingest_mode or "AUTO").upper()
    if normalized_mode == "STORAGE_WRITE" and has_arrow_source:
        return StorageWriteStreamStrategy()
    if normalized_mode == "DIRECT_ARROW" and has_arrow_source:
        return DirectArrowUploadStrategy()
    if normalized_mode == "GCS_LOAD_JOB":
        return GcsLoadJobStrategy()
    if has_arrow_source and payload_bytes is not None and 0 <= payload_bytes < threshold_bytes:
        return DirectArrowUploadStrategy()
    return GcsLoadJobStrategy()
