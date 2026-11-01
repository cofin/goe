---
type: concept
title: Google Cloud BigQuery Backend Adapter
description: BigQuery client lifecycle, BIGQUERY_CAPABILITIES, CachedBackendCatalog, BigQueryIngestStrategy, KMS CMEK, and OpenTelemetry spans/metrics.
status: stable
tags:
  - backends
  - bigquery
  - gcp
  - data-warehouse
  - opentelemetry
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: bq-api
    resource: src/goe/offload/bigquery/bigquery_backend_api.py::BackendBigQueryApi
    title: BigQuery Backend API Adapter
  - id: bq-table
    resource: src/goe/offload/bigquery/bigquery_backend_table.py::BackendBigQueryTable
    title: BigQuery Backend Table Adapter
  - id: bq-ingest
    resource: src/goe/offload/bigquery/ingest_strategy.py::select_bigquery_ingest_strategy
    title: BigQuery Ingest Strategy Selector
  - id: gcp-creds
    resource: src/goe/config/gcp_credentials.py::resolve_gcp_credentials
    title: Keyless GCP ADC and Impersonation Resolver
---

# Google Cloud BigQuery Backend Adapter

<!-- truth: start -->
- `BackendBigQueryApi` (`src/goe/offload/bigquery/bigquery_backend_api.py`) exposes `BIGQUERY_CAPABILITIES`, caches metadata via `CachedBackendCatalog`, and resolves keyless ADC / impersonated credentials via `resolve_gcp_credentials` (`src/goe/config/gcp_credentials.py`).[^bq-api][^gcp-creds]
- `BackendBigQueryTable` (`src/goe/offload/bigquery/bigquery_backend_table.py`) generates DDL through `DialectSqlEngine` (`src/goe/offload/sql_ast/dialect_engine.py`) and delegates ingestion to `select_bigquery_ingest_strategy` (`src/goe/offload/bigquery/ingest_strategy.py`).[^bq-table][^bq-ingest]
- Default BigQuery ingestion uses `BigQueryLoadJobIngestStrategy` (`BIGQUERY_LOAD_TABLE_MODE=NATIVE`) with `load_table_from_uri` (`PARQUET` default, `DecimalTargetTypes=[NUMERIC, BIGNUMERIC, STRING]`), falling back to `BigQueryExternalTableIngestStrategy` (`EXTERNAL`) when configured or when SQL projection is required.[^bq-ingest]
- Partition inspection queries parameterized GoogleSQL `INFORMATION_SCHEMA.PARTITIONS` (`@table_name`) rather than legacy `$__PARTITIONS_SUMMARY__`.
- Every `QueryJobConfig` and `LoadJobConfig` attaches sanitized `goe_*` job labels (`goe_component`, `goe_backend`, `goe_db`, `goe_table`, `goe_step`, `goe_execution_id`, `goe_trace_id`) and records OpenTelemetry spans/metrics (`src/goe/observability/bigquery.py`).
<!-- truth: end -->

## Key Modules

- **`BackendBigQueryApi` (`src/goe/offload/bigquery/bigquery_backend_api.py`)**: Exposes `BIGQUERY_CAPABILITIES = BackendCapabilities.for_bigquery()`, routes metadata reads and write-through invalidation through `CachedBackendCatalog` (including 2-query `warm_schema(db_name)` via `INFORMATION_SCHEMA.TABLES` and `INFORMATION_SCHEMA.COLUMNS`), executes SQL via `query_and_wait`, and manages KMS CMEK bindings, job labels, and OpenTelemetry job spans/metrics.[^bq-api]
- **`BackendBigQueryTable` (`src/goe/offload/bigquery/bigquery_backend_table.py`)**: Coordinates target table DDL via `DialectSqlEngine` (`get_bigquery_dialect_engine()`), delegates staged cast verification and final SQL generation to `StagingLoadService` and `FinalTableMerger`, and dispatches ingestion through `select_bigquery_ingest_strategy`.[^bq-table]
- **`BigQueryIngestStrategy` (`src/goe/offload/bigquery/ingest_strategy.py`)**:
  - `BigQueryLoadJobIngestStrategy` / `DirectNativeLoadUriStrategy`: Directly loads staged GCS Parquet/Avro URIs into the target BigQuery table via `load_table_from_uri` (`DecimalTargetType.NUMERIC`/`BIGNUMERIC`).
  - `DirectBigQueryStorageWriteStrategy`: Streams Arrow/Parquet data to the BigQuery Storage Write API (`BigQueryWriteClient`) using `PENDING` streams and atomic `BatchCommitWriteStreamsRequest`.
  - `BigQueryExternalTableIngestStrategy` / `StagedLoadInsertStrategy`: Loads GCS files via a native or external staging table (`BIGQUERY_LOAD_TABLE_MODE=NATIVE | EXTERNAL`), runs staged cast/data validation, and executes `INSERT INTO ... SELECT` into the final table with guaranteed `finally` drop cleanup.[^bq-ingest]
- **`build_staging_load_job_config` & `build_final_append_load_job_config` (`src/goe/offload/bigquery/bigquery_load_job.py`)**: Constructs `bigquery.LoadJobConfig` for native GCS load jobs (`PARQUET` with `DecimalTargetTypes` `[NUMERIC, BIGNUMERIC, STRING]` or `AVRO` with `use_avro_logical_types=True`, optional CMEK `EncryptionConfiguration`, and `job_labels`).
- **`src/goe/observability/bigquery.py`**: `traced_bigquery_job`, `traced_bigquery_storage_write`, `merge_trace_labels`, and `record_bigquery_job_metrics`.

## Connection, Lifecycle & Security

- **Unified Keyless ADC & Impersonation (`src/goe/config/gcp_credentials.py`)**:
  - `bigquery.Client` obtains credentials via `resolve_gcp_credentials(self._config, component="bigquery")`.[^gcp-creds]
  - Job billing project precedence resolves `GOOGLE_CLOUD_PROJECT` -> ADC default project -> `BIGQUERY_DATASET_PROJECT`, while dataset/table DDL identifiers remain scoped to `BIGQUERY_DATASET_PROJECT`.
  - Supports keyless Application Default Credentials and service account impersonation via `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`.
- **Client Metadata & Cleanup**: `bigquery.Client` is initialized with `ClientInfo(user_agent=f"goe/{version()}")`, UTC session normalization (`bigquery.ConnectionProperty("time_zone", "UTC")`), and an idempotent `close()` method.
- **Encryption (CMEK)**: Customer-Managed Encryption Keys via Google Cloud KMS are applied across dataset creation, table DDL (`OPTIONS (kms_key_name=...)`), native load jobs, and query jobs.

## Table Design, Metadata & Query Execution

- **Partitioning & Clustering (`DialectSqlEngine`)**:
  - Date/Timestamp partitioning: `PARTITION BY col` or `PARTITION BY DATE_TRUNC/DATETIME_TRUNC/TIMESTAMP_TRUNC(col, DAY|MONTH|YEAR)`.
  - Integer range partitioning: `PARTITION BY RANGE_BUCKET(col, GENERATE_ARRAY(start, end, interval))` for `INT64`.
  - Clustering: `CLUSTER BY col1, col2, ...` (up to 4 clustering columns).
- **GoogleSQL `INFORMATION_SCHEMA.PARTITIONS`**:
  - `get_table_partition_count()` and `get_table_partitions()` query `project.dataset.INFORMATION_SCHEMA.PARTITIONS` using parameterized `@table_name` (`WHERE table_name = @table_name AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')`).
- **`query_and_wait` Fast Path**:
  - `_execute_query_fetch_x()` uses `client.query_and_wait(sql, job_config=job_config)` when `not log_job_stats and not dry_run`, falling back to `client.query(sql, job_config=job_config)` when full job statistics or dry-run validation is requested.

[^bq-api]: `src/goe/offload/bigquery/bigquery_backend_api.py::BackendBigQueryApi` — BigQuery backend API client, catalog cache, and query execution.
[^bq-table]: `src/goe/offload/bigquery/bigquery_backend_table.py::BackendBigQueryTable` — BigQuery backend table DDL and load orchestration.
[^bq-ingest]: `src/goe/offload/bigquery/ingest_strategy.py::select_bigquery_ingest_strategy` — Direct `load_table_from_uri` and staged BigQuery ingestion strategies.
[^gcp-creds]: `src/goe/config/gcp_credentials.py::resolve_gcp_credentials` — Keyless GCP ADC and service account impersonation resolver.
