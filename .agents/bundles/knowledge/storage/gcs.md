---
type: Reference
title: Google Cloud Storage (GCS) Adapter
description: GOEGcs client lifecycle, keyless ADC authentication, atomic precondition uploads, single-pass batch deletes, and OpenTelemetry spans
tags:
  - reference
  - storage
  - gcs
  - gcp
  - opentelemetry
---

# Google Cloud Storage (GCS) Adapter

The GCS adapter (`src/goe/filesystem/goe_gcs.py`) provides staging storage integration for Google BigQuery, Dataproc, Query Import, and DuckDB offload operations.

## Key Features

- **Class**: `GOEGcs` (inherits from `GOEDfs`).
- **Driver / Library**: `google-cloud-storage`, `google-auth`.
- **Scheme**: `gs://<bucket>/<prefix>/<dataset>/<load_table>/part*`.
- **Authentication (`src/goe/util/gcp_credentials.py`)**:
  1. Keyless Application Default Credentials (ADC) resolved centrally via `resolve_gcp_credentials(config, component="gcs")`.
  2. Service account impersonation via `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` (`google.auth.impersonated_credentials.Credentials`).
  3. Explicit `token=bundle.credentials` passed into `fsspec.filesystem("gs", project=bundle.project, token=bundle.credentials)` in `GOELogFileHandle` (`src/goe/util/goe_log_fh.py`) so `gcsfs` never silently falls back to anonymous access.
  4. Standalone Spark (`spark-submit` / Livy) bundles `gcs-connector-3.0.20-shaded.jar` with `spark.hadoop.fs.gs.auth.type=APPLICATION_DEFAULT` (and `spark.hadoop.fs.gs.auth.impersonation.service.account` when `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set).
- **Atomic Upload Preconditions (`if_generation_match`)**:
  - `copy_from_local()` and `write()` pass `if_generation_match = None if overwrite else 0` directly to `blob.upload_from_filename(..., if_generation_match=...)` and `blob.upload_from_string(..., if_generation_match=...)`, enforcing atomic create-only semantics on `overwrite=False` without a preceding `stat()` / `blob.exists()` round-trip.
- **Single-Pass Batch Deletions (`delete_blobs`)**:
  - `delete()` materializes `blobs = list(bucket.list_blobs(prefix=prefix))` when `recursive=True` (or checks a single blob) and calls `bucket.delete_blobs(blobs, on_error=lambda _blob: None)` in a single pass instead of issuing redundant pre/post listing loops.
- **Eventual Consistency Retries**: Uses `@retry.Retry(GOEDfsFilesNotVisible)` when verifying files written by external distributed jobs.

## OpenTelemetry Storage Spans (`src/goe/observability/storage.py`)

All 7 data-plane methods on `GOEGcs` (`copy_from_local`, `copy_to_local`, `delete`, `list_dir`, `read`, `stat`, `write`) are decorated with `@traced_storage_call("<operation>")`:
- When `GOE_OTEL_ENABLED=false`, `@traced_storage_call` executes the wrapped method directly without span creation.
- When `GOE_OTEL_ENABLED=true`, it starts a `SpanKind.CLIENT` span named `goe.storage.gs.<operation>` with attributes `goe.storage.scheme="gs"`, `goe.storage.container`, `goe.storage.uri`, `goe.storage.operation`, and `goe.storage.bytes` (derived from local file size on `copy_from_local`, downloaded file size on `copy_to_local`, payload length on `write`/`read`, or `stat()["length"]`), and increments `GOEMetrics.storage_bytes_transferred` (`goe.storage.bytes_transferred`) on `copy_from_local`, `copy_to_local`, `write`, and `read`.
