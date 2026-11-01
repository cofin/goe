---
type: concept
title: Azure Blob & ADLS Gen2 Storage Adapter
description: StagingStorageService Azure backend via BlobServiceClient and sqlspec.storage, ADLS Gen2 hierarchical namespace, and reverse-depth deletion.
status: stable
tags:
  - reference
  - storage
  - azure
  - adls
  - blob
  - sqlspec
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
  - id: goe-azure
    resource: src/goe/filesystem/goe_azure.py::GOEAzure
    title: Azure Blob and ADLS Gen2 DFS Adapter
---

# Azure Blob & ADLS Gen2 Storage Adapter

<!-- truth: start -->
- `StagingStorageService` (`src/goe/filesystem/storage_service.py`) and `GOEAzure` (`src/goe/filesystem/goe_azure.py`) manage `abfss://`, `abfs://`, `wasbs://`, and `wasb://` staging paths with `azure.core.exceptions.ResourceNotFoundError` handling.[^storage-svc][^goe-azure]
- All 7 storage operations emit `@traced_storage_call` OpenTelemetry spans (`src/goe/observability/storage.py`).
<!-- truth: end -->

Azure Blob and ADLS Gen2 staging storage is handled by `StagingStorageService` (`src/goe/filesystem/storage_service.py`) and `CloudStorageDfsAdapter` (`src/goe/filesystem/goe_dfs.py`), replacing the legacy `src/goe/filesystem/goe_azure.py` module.

## Key Features

- **Classes**: `StagingStorageService` and `CloudStorageDfsAdapter(GOEDfs)` (`backend_dfs="AZURE"`).
- **Driver / Library**: `azure-storage-blob` (`BlobServiceClient`), `sqlspec.storage`.
- **Scheme**: `abfss://<container>@<account>.dfs.core.windows.net/<prefix>/<load_db>/<load_table>/part*` or `wasb://` / `wasbs://` (`azure_fq_container_name` formats `container@account.endpoint`).
- **Authentication**:
  1. Storage Account Key (`offload_fs_azure_account_key`) and Account Name (`offload_fs_azure_account_name`) over `offload_fs_azure_account_domain`.
- **Hierarchical Namespace Deletion**: In ADLS Gen2 (`_azure_delete()`), matching blob names are sorted by path depth (`key.count("/")`) in reverse order and deleted in batches of `DELETE_BATCH_LIMIT = 1000` so child paths are removed before parent directories.

[^storage-svc]: `src/goe/filesystem/storage_service.py::StagingStorageService` — Unified Multi-Cloud Staging Storage Service.
[^goe-azure]: `src/goe/filesystem/goe_azure.py::GOEAzure` — Azure Blob and ADLS Gen2 DFS Adapter.
