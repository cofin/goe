---
type: Reference
title: Azure Blob & ADLS Gen2 Storage Adapter
description: StagingStorageService Azure backend via BlobServiceClient and sqlspec.storage, ADLS Gen2 hierarchical namespace, and reverse-depth deletion
tags:
  - reference
  - storage
  - azure
  - adls
  - blob
  - sqlspec
updated_at: "2026-10-26T18:05:00Z"
---

# Azure Blob & ADLS Gen2 Storage Adapter

Azure Blob and ADLS Gen2 staging storage is handled by `StagingStorageService` (`src/goe/filesystem/storage_service.py`) and `CloudStorageDfsAdapter` (`src/goe/filesystem/goe_dfs.py`), replacing the legacy `src/goe/filesystem/goe_azure.py` module.

## Key Features

- **Classes**: `StagingStorageService` and `CloudStorageDfsAdapter(GOEDfs)` (`backend_dfs="AZURE"`).
- **Driver / Library**: `azure-storage-blob` (`BlobServiceClient`), `sqlspec.storage`.
- **Scheme**: `abfss://<container>@<account>.dfs.core.windows.net/<prefix>/<load_db>/<load_table>/part*` or `wasb://` / `wasbs://` (`azure_fq_container_name` formats `container@account.endpoint`).
- **Authentication**:
  1. Storage Account Key (`offload_fs_azure_account_key`) and Account Name (`offload_fs_azure_account_name`) over `offload_fs_azure_account_domain`.
- **Hierarchical Namespace Deletion**: In ADLS Gen2 (`_azure_delete()`), matching blob names are sorted by path depth (`key.count("/")`) in reverse order and deleted in batches of `DELETE_BATCH_LIMIT = 1000` so child paths are removed before parent directories.
