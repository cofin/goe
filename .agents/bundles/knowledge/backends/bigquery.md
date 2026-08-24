---
type: Reference
title: Google Cloud BigQuery Backend Adapter
description: BigQuery client lifecycle, partitioning, clustering, KMS CMEK encryption, and staged ingestion
tags:
  - reference
  - backends
  - bigquery
  - gcp
  - data-warehouse
---

# Google Cloud BigQuery Backend Adapter

The BigQuery backend adapter (`src/goe/offload/bigquery/`) manages target datasets, tables, partition schemes, clustering keys, and staged ingestion on Google Cloud BigQuery.

## Key Modules

- **`BackendBigQueryApi` (`bigquery_backend_api.py`)**: Client management, DDL generation, KMS key bindings, and dataset lifecycle.
- **`BackendBigQueryTable` (`bigquery_backend_table.py`)**: Table creation, external staging table definitions, and data loading DML.
- **`BigQueryColumn` & `BigQueryLiteral`**: Column translation and SQL literal formatting.

## Connection & Security

- **SDK**: `google-cloud-bigquery` (`bigquery.Client`), `google-cloud-kms` (`kms.KeyManagementServiceClient`).
- **Timezone**: Normalized to UTC via `bigquery.ConnectionProperty("time_zone", "UTC")`.
- **Encryption**: Customer-Managed Encryption Keys (CMEK) via Google Cloud KMS configured on dataset, table options (`OPTIONS(kms_key_name=...)`), and query jobs (`QueryJobConfig.destination_encryption_configuration`).

## Table Design & Optimization

### 1. Partitioning
- **Date/Timestamp Partitioning**:
  - `PARTITION BY col` (for `DATE` columns).
  - `PARTITION BY DATE_TRUNC(col, DAY|MONTH|YEAR)` (for `DATETIME`/`TIMESTAMP` columns).
- **Integer Range Partitioning**:
  - `PARTITION BY RANGE_BUCKET(col, GENERATE_ARRAY(start, end, interval))` for `INT64`.

### 2. Clustering
- `CLUSTER BY col1, col2, ...` (up to 4 clustering columns for query pruning).

### 3. Staged Data Ingestion
1. **External Staging Table**:
   ```sql
   CREATE OR REPLACE EXTERNAL TABLE `project.dataset.stage_table`
   OPTIONS (
     format = 'PARQUET',
     uris = ['gs://bucket/prefix/dataset/stage_table/part*']
   );
   ```
2. **Atomic Load**:
   ```sql
   INSERT INTO `project.dataset.target_table` (col1, col2, ...)
   SELECT SAFE_CAST(col1 AS TYPE), SAFE_CAST(col2 AS TYPE), ...
   FROM `project.dataset.stage_table`;
   ```

## Telemetry & Slot Metrics
Extracts job metrics: `slot_millis`, `total_bytes_billed`, and estimated slot usage: `ceil(slot_millis / elapsed_ms)`.
