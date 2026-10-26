---
type: Reference
title: Google Cloud Storage (GCS) & StagingStorageService Adapter
description: StagingStorageService and CloudStorageDfsAdapter over sqlspec.storage, keyless ADC authentication, atomic precondition uploads, bounded stat_uri, 1,000-key batch deletes, and OpenTelemetry spans
tags:
  - reference
  - storage
  - gcs
  - gcp
  - sqlspec
  - opentelemetry
updated_at: "2026-10-26T18:05:00Z"
---

# Google Cloud Storage (GCS) & `StagingStorageService` Adapter

GCS, S3, Azure Blob/ADLS, and local file staging operations are unified in `StagingStorageService` (`src/goe/filesystem/storage_service.py`) and `CloudStorageDfsAdapter` (`src/goe/filesystem/goe_dfs.py`), replacing the legacy per-cloud `goe_gcs.py`, `goe_s3.py`, and `goe_azure.py` modules.

## Key Features

- **Classes**: `StagingStorageService` (`src/goe/filesystem/storage_service.py`) and `CloudStorageDfsAdapter(GOEDfs)` (`src/goe/filesystem/goe_dfs.py`), instantiated via `get_dfs_from_options()` (`src/goe/filesystem/goe_dfs_factory.py`).
- **Driver / Library**: `sqlspec.storage` (`storage_registry`, `LocalStore`, `FSSpecBackend`, `ObStoreBackend`), `google-cloud-storage`, `google-auth`.
- **Scheme**: `gs://<bucket>/<prefix>/<dataset>/<load_table>/part*`.
- **Authentication (`src/goe/util/gcp_credentials.py`)**:
  1. Keyless Application Default Credentials (ADC) resolved centrally via `resolve_gcp_credentials(config)`.
  2. Service account impersonation via `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` (`google.auth.impersonated_credentials.Credentials`).
  3. Explicit `token=bundle.credentials` passed into `fsspec.filesystem("gs", project=bundle.project, token=bundle.credentials)` in `GOELogFileHandle` (`src/goe/util/goe_log_fh.py`) so `gcsfs` never silently falls back to anonymous access.
  4. Standalone Spark (`spark-submit` / Livy) bundles `gcs-connector-3.0.20-shaded.jar` with `spark.hadoop.fs.gs.auth.type=APPLICATION_DEFAULT` (and `spark.hadoop.fs.gs.auth.impersonation.service.account` when `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set).
- **Atomic Upload Preconditions (`if_generation_match`)**:
  - `upload_file()` / `copy_from_local()` and `write_bytes()` / `write()` pass `if_generation_match = None if overwrite else 0` directly to `blob.upload_from_filename(..., if_generation_match=...)` and `blob.upload_from_string(..., if_generation_match=...)`, enforcing atomic create-only semantics on `overwrite=False` without a preceding `stat()` / `blob.exists()` round-trip.
- **Bounded `stat_uri` (`max_results=2`)**:
  - When a direct blob lookup misses, `StagingStorageService._gcs_stat()` queries `bucket.list_blobs(prefix=..., max_results=2)` to detect virtual directory prefixes in `O(1)` time without materializing unbounded object listings.
- **Chunked Batch Deletions (`DELETE_BATCH_LIMIT = 1000`)**:
  - `delete_prefix()` / `delete()` materializes matching blobs (`bucket.list_blobs(prefix=prefix)` when `recursive=True` or exact key match) and calls `bucket.delete_blobs(batch, on_error=lambda _blob: None)` in chunks of at most `DELETE_BATCH_LIMIT = 1000` objects.
- **Eventual Consistency Retries**: Uses `@retry.Retry(GOEDfsFilesNotVisible)` when verifying files written by external distributed jobs.

## OpenTelemetry Storage Spans (`src/goe/observability/storage.py`)

All 7 data-plane methods on `CloudStorageDfsAdapter` (`copy_from_local`, `copy_to_local`, `delete`, `list_dir`, `read`, `stat`, `write`) and `StagingStorageService` (`upload_file`, `download_file`, `delete_prefix`, `list_uris`, `read_bytes`, `stat_uri`, `write_bytes`) are decorated with `@traced_storage_call("<operation>", "<uri_param>")`:
- When `GOE_OTEL_ENABLED=false`, `@traced_storage_call` executes the wrapped method directly without span creation.
- When `GOE_OTEL_ENABLED=true`, it starts a `SpanKind.CLIENT` span named `goe.storage.<scheme>.<operation>` with attributes `goe.storage.scheme`, `goe.storage.container`, `goe.storage.uri`, `goe.storage.operation`, and `goe.storage.bytes`, and increments `GOEMetrics.storage_bytes_transferred` (`goe.storage.bytes_transferred`) on `copy_from_local`, `copy_to_local`, `write`, and `read`.
