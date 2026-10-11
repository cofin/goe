---
type: Reference
title: Google Cloud Storage (GCS) Adapter
description: Client lifecycle, ADC authentication, bucket path generation, and eventual consistency retry policies
tags:
  - reference
  - storage
  - gcs
  - gcp
---

# Google Cloud Storage (GCS) Adapter

The GCS adapter (`src/goe/filesystem/goe_gcs.py`) provides staging storage integration for Google BigQuery and Dataproc offload operations.

## Key Features

- **Class**: `GOEGcs` (inherits from `GOEDfs`).
- **Driver / Library**: `google-cloud-storage`, `google-auth`.
- **Scheme**: `gs://<bucket>/<prefix>/<dataset>/<load_table>/part*`.
- **Authentication (`src/goe/util/gcp_credentials.py`)**:
  1. Keyless Application Default Credentials (ADC) resolved centrally via `resolve_gcp_credentials(config, component="gcs")`.
  2. Service account impersonation via `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` (`google.auth.impersonated_credentials.Credentials`).
  3. Explicit `token=bundle.credentials` passed into `fsspec.filesystem("gs", project=bundle.project, token=bundle.credentials)` in `GOELogFileHandle` (`src/goe/util/goe_log_fh.py`) so `gcsfs` never silently falls back to anonymous access.
  4. Standalone Spark (`spark-submit` / Livy) bundles `gcs-connector-3.0.20-shaded.jar` with `spark.hadoop.fs.gs.auth.type=APPLICATION_DEFAULT` (and `spark.hadoop.fs.gs.auth.impersonation.service.account` when `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` is set).
- **Eventual Consistency Retries**: Uses `@retry.Retry(GOEDfsFilesNotVisible)` to ensure files written by Spark are visible in GCS before executing BigQuery load queries.
- **Batch Deletions**: `pragmatic_delete()` efficiently purges staging blobs matching prefix paths.
