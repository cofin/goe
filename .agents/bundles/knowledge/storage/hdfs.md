---
type: concept
title: HDFS & WebHDFS Storage Adapter
description: Consolidated HdfsClient supporting CLI and WebHDFS modes, optional hdfs/requests_kerberos loading, and active NameNode discovery.
status: stable
tags:
  - reference
  - storage
  - hdfs
  - hadoop
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: hdfs-client
    resource: src/goe/filesystem/hdfs_client.py::HdfsClient
    title: HDFS and WebHDFS Storage Client
  - id: web-hdfs
    resource: src/goe/filesystem/web_hdfs.py::WebHdfs
    title: WebHDFS Adapter with Optional Kerberos Guard
---

# HDFS & WebHDFS Storage Adapter

<!-- truth: start -->
- `HdfsClient` (`src/goe/filesystem/hdfs_client.py`) and `WebHdfs` (`src/goe/filesystem/web_hdfs.py`) manage `hdfs://` and `webhdfs://` staging files with optional `hdfs`/`requests_kerberos` import guards.[^hdfs-client][^web-hdfs]
<!-- truth: end -->

The unified `HdfsClient` adapter (`src/goe/filesystem/hdfs_client.py`) consolidates the retired `cli_hdfs.py` and `web_hdfs.py` modules into a single `GOEDfs` implementation for on-premises Hadoop clusters (with all legacy `maprfs` code removed).

## Key Features

- **Class**: `HdfsClient(GOEDfs)` (`mode="cli"` for subprocess/SSH `hdfs dfs` commands or `mode="webhdfs"` for REST WebHDFS via `hdfs.InsecureClient` / `hdfs.ext.kerberos.KerberosClient`).
- **Optional Dependency Isolation**: Loads `hdfs`, `hdfs.ext.kerberos`, and `requests_kerberos` on demand via `goe.util.module_loader.import_optional()` so GCP/Snowflake/Synapse installations never require Hadoop client packages at import time.
- **Scheme**: `hdfs://<namenode>:8020/<prefix>/<load_db>/<load_table>/part*`.
- **Security**: Kerberos SPNEGO ticket authentication via keytab or ticket cache (`KRB5CCNAME`).
- **High Availability**: Automatic discovery of active NameNode across semicolon-delimited NameNode hosts (`webhdfs_Client.list("/")` health check).

[^hdfs-client]: `src/goe/filesystem/hdfs_client.py::HdfsClient` — HDFS and WebHDFS Storage Client.
[^web-hdfs]: `src/goe/filesystem/web_hdfs.py::WebHdfs` — WebHDFS Adapter with Optional Kerberos Guard.
