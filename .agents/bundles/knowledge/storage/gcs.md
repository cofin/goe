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
- **Authentication**:
  1. Application Default Credentials (ADC).
  2. Service account key file via `GOOGLE_APPLICATION_CREDENTIALS`.
  3. GCE / Dataproc instance metadata token.
- **Eventual Consistency Retries**: Uses `@retry.Retry(GOEDfsFilesNotVisible)` to ensure files written by Spark are visible in GCS before executing BigQuery load queries.
- **Batch Deletions**: `pragmatic_delete()` efficiently purges staging blobs matching prefix paths.
