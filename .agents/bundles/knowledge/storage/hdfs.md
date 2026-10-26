---
type: Reference
title: HDFS & WebHDFS Storage Adapter
description: Consolidated HdfsClient supporting CLI and WebHDFS modes, optional hdfs/requests_kerberos loading, and active NameNode discovery
tags:
  - reference
  - storage
  - hdfs
  - hadoop
updated_at: "2026-10-26T18:05:00Z"
---

# HDFS & WebHDFS Storage Adapter

The unified `HdfsClient` adapter (`src/goe/filesystem/hdfs_client.py`) consolidates the retired `cli_hdfs.py` and `web_hdfs.py` modules into a single `GOEDfs` implementation for on-premises Hadoop clusters (with all legacy `maprfs` code removed).

## Key Features

- **Class**: `HdfsClient(GOEDfs)` (`mode="cli"` for subprocess/SSH `hdfs dfs` commands or `mode="webhdfs"` for REST WebHDFS via `hdfs.InsecureClient` / `hdfs.ext.kerberos.KerberosClient`).
- **Optional Dependency Isolation**: Loads `hdfs`, `hdfs.ext.kerberos`, and `requests_kerberos` on demand via `goe.util.module_loader.import_optional()` so GCP/Snowflake/Synapse installations never require Hadoop client packages at import time.
- **Scheme**: `hdfs://<namenode>:8020/<prefix>/<load_db>/<load_table>/part*`.
- **Security**: Kerberos SPNEGO ticket authentication via keytab or ticket cache (`KRB5CCNAME`).
- **High Availability**: Automatic discovery of active NameNode across semicolon-delimited NameNode hosts (`webhdfs_Client.list("/")` health check).
