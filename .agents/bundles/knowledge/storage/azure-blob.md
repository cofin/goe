---
type: Reference
title: Azure Blob & ADLS Gen2 Storage Adapter
description: BlobServiceClient, ADLS Gen2 hierarchical namespace, and token authentication
tags:
  - reference
  - storage
  - azure
  - adls
  - blob
---

# Azure Blob & ADLS Gen2 Storage Adapter

The Azure Blob adapter (`src/goe/filesystem/goe_azure.py`) provides staging storage integration for Azure Synapse and Snowflake on Microsoft Azure.

## Key Features

- **Class**: `GOEAzure` (inherits from `GOEDfs`).
- **Driver / Library**: `azure-storage-blob` (`BlobServiceClient`, `ContainerClient`).
- **Scheme**: `abfss://<container>@<account>.dfs.core.windows.net/<prefix>/<load_db>/<load_table>/part*` or `wasbs://`.
- **Authentication**:
  1. Storage Account Key (`azure_storage_account_key`).
  2. SAS (Shared Access Signature) Token.
  3. Connection String (`azure_storage_connection_string`).
  4. Azure Managed Identity / Service Principal via `DefaultAzureCredential`.
- **Hierarchical Namespace Deletion**: In ADLS Gen2, deep child paths are sorted in reverse order to ensure clean recursive deletion without race conditions.
