---
type: Reference
title: Backend Cloud DW Adapters
description: Target database engines, DDL generation, staging ingestion, partitioning, and query optimization
tags:
  - reference
  - backends
  - data-warehouse
  - index
---

# Backend Cloud DW Adapters

This section documents the target cloud data warehouse and query engine adapters supported by GOE.

## Adapters

- [Google Cloud BigQuery](bigquery.md) - `google-cloud-bigquery`, date/integer partitioning, clustering, KMS CMEK encryption, and slot telemetry.
- [Snowflake](snowflake.md) - `snowflake-connector-python`, stages, storage integrations, and `COPY INTO` projection.
- [Azure Synapse Analytics](synapse.md) - `pyodbc`, PolyBase external tables, clustered columnstore indexing, and table distributions.
- [Apache Hadoop / Impala / Hive](hadoop.md) - `better_impyla`, HiveServer2 Thrift protocol, Kerberos authentication, and incremental statistics.
