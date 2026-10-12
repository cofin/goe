---
type: Reference
title: Google Cloud BigQuery Backend Adapter
description: BigQuery client lifecycle, BigQuerySqlEngine AST DDL/DML, native LoadJobConfig ingestion, INFORMATION_SCHEMA metadata, KMS CMEK, and OpenTelemetry spans/metrics
tags:
  - reference
  - backends
  - bigquery
  - gcp
  - data-warehouse
  - opentelemetry
---

# Google Cloud BigQuery Backend Adapter

The BigQuery backend adapter (`src/goe/offload/bigquery/`) manages target datasets, tables, partition schemes, clustering keys, native and external staged ingestion, and OpenTelemetry job telemetry on Google Cloud BigQuery.

## Key Modules

- **`BackendBigQueryApi` (`src/goe/offload/bigquery/bigquery_backend_api.py`)**: Client management (`ClientInfo(user_agent=f"goe/{version()}")`, idempotent `close()`), `query_and_wait` execution, parameterized GoogleSQL `INFORMATION_SCHEMA.PARTITIONS` metadata queries, KMS CMEK bindings, job labels, and OpenTelemetry job spans/metrics.
- **`BackendBigQueryTable` (`src/goe/offload/bigquery/bigquery_backend_table.py`)**: Table creation, native `load_table_from_uri` staged loading (`BIGQUERY_LOAD_TABLE_MODE=NATIVE`), external staging table fallback (`BIGQUERY_LOAD_TABLE_MODE=EXTERNAL`), and final `INSERT INTO ... SELECT` ingestion.
- **`BigQuerySqlEngine` (`src/goe/offload/bigquery/bigquery_sql.py`)**: `BigQueryDialectEngineProtocol` implementation building `CREATE TABLE`, `CREATE EXTERNAL TABLE`, `DROP TABLE`, `ALTER TABLE ADD COLUMN`, `INSERT INTO ... SELECT`, and `SELECT` ASTs.
- **`build_staging_load_job_config` (`src/goe/offload/bigquery/bigquery_load_job.py`)**: Constructs `bigquery.LoadJobConfig` for native GCS load jobs (`PARQUET` with `DecimalTargetTypes` `[NUMERIC, BIGNUMERIC, STRING]` or `AVRO` with `use_avro_logical_types=True`, `WRITE_TRUNCATE`, `CREATE_IF_NEEDED`, optional CMEK `EncryptionConfiguration`, and `job_labels`).
- **`BigQueryColumn` & `BigQueryLiteral`**: Column translation and SQL literal formatting.
- **`src/goe/observability/bigquery.py`**: `traced_bigquery_job`, `merge_trace_labels`, and `record_bigquery_job_metrics`.

## Connection, Lifecycle & Security

- **SDK**: `google-cloud-bigquery` (`bigquery.Client`), `google-cloud-kms` (`kms.KeyManagementServiceClient`).
- **Unified Keyless ADC & Impersonation (`src/goe/util/gcp_credentials.py`)**:
  - Both `bigquery.Client` and `kms.KeyManagementServiceClient` obtain credentials via `resolve_gcp_credentials(self._config, component="bigquery" | "kms")`.
  - Job billing project precedence resolves `GOOGLE_CLOUD_PROJECT` -> ADC default project -> `BIGQUERY_DATASET_PROJECT`, while dataset/table DDL identifiers remain scoped to `BIGQUERY_DATASET_PROJECT`.
  - Supports keyless Application Default Credentials and service account impersonation chains via `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`.
- **Client Metadata & Cleanup**: `bigquery.Client` is initialized with `ClientInfo(user_agent=f"goe/{version()}")`, UTC session normalization (`bigquery.ConnectionProperty("time_zone", "UTC")`), and an idempotent `close()` method.
- **Encryption (CMEK)**: Customer-Managed Encryption Keys via Google Cloud KMS are applied across:
  - Dataset creation (`dataset.default_encryption_configuration = EncryptionConfiguration(kms_key_name=...)`).
  - Table DDL (`OPTIONS (kms_key_name=...)` via `BigQuerySqlEngine`).
  - Native load jobs (`LoadJobConfig.destination_encryption_configuration`) and query jobs (`QueryJobConfig.destination_encryption_configuration`).

## Table Design, Metadata & Query Execution

### 1. Partitioning & Clustering (`BigQuerySqlEngine`)
- **Date/Timestamp Partitioning**:
  - `PARTITION BY col` (for `DATE` columns).
  - `PARTITION BY DATE_TRUNC/DATETIME_TRUNC/TIMESTAMP_TRUNC(col, DAY|MONTH|YEAR)`.
- **Integer Range Partitioning**:
  - `PARTITION BY RANGE_BUCKET(col, GENERATE_ARRAY(start, end, interval))` for `INT64`.
- **Clustering**:
  - `CLUSTER BY col1, col2, ...` (up to 4 clustering columns).

### 2. GoogleSQL `INFORMATION_SCHEMA.PARTITIONS`
- `get_table_partition_count()` and `get_table_partitions()` query `project.dataset.INFORMATION_SCHEMA.PARTITIONS` using parameterized `@table_name` (`bigquery.ScalarQueryParameter("table_name", "STRING", table_name)`), filtering `WHERE table_name = @table_name AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')` (Legacy SQL `$__PARTITIONS_SUMMARY__` is retired).

### 3. `query_and_wait` Fast Path
- `_execute_query_fetch_x()` uses `client.query_and_wait(sql, job_config=job_config)` when `not log_job_stats and not dry_run`, falling back to `client.query(sql, job_config=job_config)` when full job statistics or dry-run validation is requested.

## Staged Data Ingestion (`PARQUET` Default & `BIGQUERY_LOAD_TABLE_MODE`)

- **Default Staging Format**: When `BACKEND_DISTRIBUTION == BACKEND_DISTRO_GCP`, `offload_staging_format_default()` defaults to `PARQUET` (`FILE_STORAGE_FORMAT_PARQUET`).
- **Load Table Mode (`BIGQUERY_LOAD_TABLE_MODE`, default `NATIVE`)**:
  1. **`NATIVE` Mode (Default)**:
     - `_recreate_load_table()` is a no-op during `STEP_STAGING_SETUP`.
     - After staged files land in GCS (`STEP_STAGING_TRANSPORT`), `BackendBigQueryTable._load_staged_files_into_native_load_table()` invokes `BackendBigQueryApi.load_table_from_uri(staging_uri, db_name, table_name, load_job_config)` before `STEP_VALIDATE_DATA` / `STEP_VALIDATE_CASTS` / `STEP_FINAL_LOAD`, materializing a native BigQuery load table that subsequent validation and `INSERT INTO ... SELECT` queries scan without re-reading GCS on every query.
     - `_drop_load_table()` drops the native load table with `external=False`.
  2. **`EXTERNAL` Mode (Fallback)**:
     - Creates `CREATE OR REPLACE EXTERNAL TABLE` over `gs://bucket/prefix/dataset/stage_table/part*` during `STEP_STAGING_SETUP` and drops it with `DROP EXTERNAL TABLE` during cleanup.

## Job Labels, OpenTelemetry Spans & Metrics (`src/goe/observability/bigquery.py`)

- **Job Labels (`job_labels()` + `merge_trace_labels()`)**:
  - Every `QueryJobConfig` and `LoadJobConfig` carries sanitized BigQuery job labels (`sanitize_bigquery_label_value`, lowercase `[a-z0-9_-]{1,63}`):
    - Base labels: `goe_component="offload"`, `goe_backend="bigquery"`, `goe_db`, `goe_table`.
    - Active trace/context labels (when OpenTelemetry / `ExecutionId` context is active): `goe_step`, `goe_execution_id`, `goe_trace_id`.
- **OpenTelemetry Spans (`traced_bigquery_job`)**:
  - Emits `SpanKind.CLIENT` spans named `goe.backend.bigquery.<operation>` (`create_table`, `drop_table`, `dml`, `query`, `load_table_from_uri`) with attributes `db.system="bigquery"`, `db.namespace`, `db.collection.name`, `db.operation.name`, `gcp.bigquery.job.id`, `gcp.bigquery.job.location`, `gcp.bigquery.slot_millis`, `gcp.bigquery.total_bytes_billed`, `gcp.bigquery.total_bytes_processed`, and `gcp.bigquery.cache_hit`.
- **OpenTelemetry Metrics (`record_bigquery_job_metrics`)**:
  - Records `goe.bigquery.slot_millis` (`ms` counter) and `goe.bigquery.bytes_billed` (`By` counter) with bounded attribute `{"db.operation.name": operation}`.
