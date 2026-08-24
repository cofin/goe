---
type: Reference
title: HDFS & WebHDFS Storage Adapter
description: CLI and WebHDFS operations, Kerberos ticket management, and active NameNode discovery
tags:
  - reference
  - storage
  - hdfs
  - hadoop
---

# HDFS & WebHDFS Storage Adapter

The HDFS adapters (`src/goe/filesystem/cli_hdfs.py` and `web_hdfs.py`) provide storage integration for on-premises Hadoop clusters.

## Key Features

- **Classes**: `CliHdfs` (Subprocess / SSH) and `WebHdfs` (`hdfs.ext.kerberos.KerberosClient`).
- **Scheme**: `hdfs://<namenode>:8020/<prefix>/<load_db>/<load_table>/part*`.
- **Security**: Kerberos SPNEGO ticket authentication via keytab or ticket cache (`KRB5CCNAME`).
- **High Availability**: Automatic discovery of active NameNode via Hadoop JMX endpoint (`/jmx?qry=Hadoop:service=NameNode,name=NameNodeStatus`).
