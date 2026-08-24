---
type: Reference
title: Multi-Cloud Storage Abstraction
description: Unified DFS abstraction layer supporting GCS, S3, Azure Blob / ADLS Gen2, and HDFS
tags:
  - reference
  - storage
  - dfs
  - multi-cloud
  - index
---

# Multi-Cloud Storage Abstraction

The GOE filesystem abstraction layer (`src/goe/filesystem/`) provides a unified object-oriented interface (`GOEDfs`) for multi-cloud and on-premises storage operations.

## Storage Backends

- [Google Cloud Storage (GCS)](gcs.md) - `GOEGcs`, Application Default Credentials, prefix operations, and consistency retries.
- [Amazon AWS S3](s3.md) - `GOES3`, IAM credentials, bucket operations, and multipart cleanup.
- [Azure Blob & ADLS Gen2](azure-blob.md) - `GOEAzure`, hierarchical namespace deletion, and token auth.
- [Apache HDFS & WebHDFS](hdfs.md) - `CliHdfs`, `WebHdfs`, Kerberos authentication, and active NameNode discovery.
