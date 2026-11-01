---
type: concept
title: Google Cloud Storage (GCS) & StagingStorageService Adapter
description: StagingStorageService and CloudStorageDfsAdapter over sqlspec.storage, keyless ADC authentication, atomic precondition uploads, bounded stat_uri, and OpenTelemetry spans.
status: stable
tags:
  - storage
  - gcs
  - gcp
  - sqlspec
  - opentelemetry
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: storage-svc
    resource: src/goe/filesystem/storage_service.py::StagingStorageService
    title: Unified Multi-Cloud Staging Storage Service
  - id: goe-dfs
    resource: src/goe/filesystem/goe_dfs.py::CloudStorageDfsAdapter
    title: Cloud Storage DFS Adapter
  - id: gcp-creds
    resource: src/goe/config/gcp_credentials.py::resolve_gcp_credentials
    title: Keyless GCP ADC and Impersonation Resolver
  - id: storage-otel
    resource: src/goe/observability/storage.py::traced_storage_call
    title: OpenTelemetry Storage Call Decorator
---

# Google Cloud Storage (GCS) & `StagingStorageService` Adapter

<!-- truth: start -->
- GCS, S3, Azure Blob/ADLS, and local file staging operations are unified in `StagingStorageService` (`src/goe/filesystem/storage_service.py`) and `CloudStorageDfsAdapter` (`src/goe/filesystem/goe_dfs.py`).[^storage-svc][^goe-dfs]
- GCP credentials resolve via `resolve_gcp_credentials` (`src/goe/config/gcp_credentials.py`), passing explicit `token=bundle.credentials` to `fsspec.filesystem("gs", ...)` so `gcsfs` never silently falls back to anonymous access.[^gcp-creds]
- GCS uploads enforce atomic create-only semantics via `if_generation_match = None if overwrite else 0`, `stat_uri` bounds prefix checks with `max_results=2`, and `delete_prefix` batches deletions at `DELETE_BATCH_LIMIT = 1000`.[^storage-svc]
- All 7 data-plane methods are instrumented with `@traced_storage_call` (`src/goe/observability/storage.py`).[^storage-otel]
<!-- truth: end -->

## Key Features

- **Classes**: `StagingStorageService` (`src/goe/filesystem/storage_service.py`) and `CloudStorageDfsAdapter(GOEDfs)` (`src/goe/filesystem/goe_dfs.py`), instantiated via `get_dfs_from_options()` (`src/goe/filesystem/goe_dfs_factory.py`).[^storage-svc][^goe-dfs]
- **Driver / Library**: `sqlspec.storage` (`storage_registry`, `LocalStore`, `FSSpecBackend`, `ObStoreBackend`), `google-cloud-storage`, `google-auth`.
- **Scheme**: `gs://<bucket>/<prefix>/<dataset>/<load_table>/part*`.
- **Authentication (`src/goe/config/gcp_credentials.py`)**:
  1. Keyless Application Default Credentials (ADC) resolved centrally via `resolve_gcp_credentials(config)`.[^gcp-creds]
  2. Service account impersonation via `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` (`google.auth.impersonated_credentials.Credentials`).
  3. Explicit `token=bundle.credentials` passed into `fsspec.filesystem("gs", project=bundle.project, token=bundle.credentials)` in `GOELogFileHandle` (`src/goe/util/goe_log_fh.py`) so `gcsfs` never silently falls back to anonymous access.
  4. Standalone Spark (`spark-submit` / Livy) bundles `gcs-connector-3.0.20-shaded.jar` with `spark.hadoop.fs.gs.auth.type=APPLICATION_DEFAULT` (and `spark.hadoop.fs.gs.auth.impersonation.service.account` when `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set).
- **Atomic Upload Preconditions (`if_generation_match`)**:
  - `upload_file()` / `copy_from_local()` and `write_bytes()` / `write()` pass `if_generation_match = None if overwrite else 0` directly to `blob.upload_from_filename(..., if_generation_match=...)` and `blob.upload_from_string(..., if_generation_match=...)`, enforcing atomic create-only semantics on `overwrite=False` without a preceding `stat()` round-trip.
- **Bounded `stat_uri` (`max_results=2`)**:
  - When a direct blob lookup misses, `StagingStorageService._gcs_stat()` queries `bucket.list_blobs(prefix=..., max_results=2)` to detect virtual directory prefixes in `O(1)` time without materializing unbounded object listings.
- **Chunked Batch Deletions (`DELETE_BATCH_LIMIT = 1000`)**:
  - `delete_prefix()` / `delete()` materializes matching blobs and calls `bucket.delete_blobs(batch, on_error=lambda _blob: None)` in chunks of at most `DELETE_BATCH_LIMIT = 1000` objects.

## OpenTelemetry Storage Spans (`src/goe/observability/storage.py`)

All 7 data-plane methods on `CloudStorageDfsAdapter` (`copy_from_local`, `copy_to_local`, `delete`, `list_dir`, `read`, `stat`, `write`) and `StagingStorageService` (`upload_file`, `download_file`, `delete_prefix`, `list_uris`, `read_bytes`, `stat_uri`, `write_bytes`) are decorated with `@traced_storage_call("<operation>", "<uri_param>")`.[^storage-otel]

[^storage-svc]: `src/goe/filesystem/storage_service.py::StagingStorageService` — Unified multi-cloud staging storage service over `sqlspec.storage`.
[^goe-dfs]: `src/goe/filesystem/goe_dfs.py::CloudStorageDfsAdapter` — `GOEDfs` adapter wrapping `StagingStorageService`.
[^gcp-creds]: `src/goe/config/gcp_credentials.py::resolve_gcp_credentials` — Keyless GCP ADC and impersonation resolver.
[^storage-otel]: `src/goe/observability/storage.py::traced_storage_call` — OpenTelemetry span and byte-transfer metric decorator for storage operations.
