---
type: Reference
title: Dataproc, Spark & Query Import Execution Engines
description: GCP-first AUTO transport selection, Dataproc Serverless Batches, Livy REST, Query Import, parallel JDBC slicing, and OpenTelemetry transport spans
tags:
  - reference
  - transport
  - spark
  - dataproc
  - livy
  - opentelemetry
---

# Dataproc, Spark & Query Import Execution Engines

The transport layer (`src/goe/offload/transport/` & `src/goe/offload/spark/`) orchestrates data extraction from source RDBMS to cloud storage staging files.

## Execution Topologies & GCP-First `AUTO` Selection

When `OFFLOAD_TRANSPORT=AUTO` (`choose_offload_transport_method` in `src/goe/offload/transport/factory.py`) and `target_Is_gcp` (`backend_distribution == BACKEND_DISTRO_GCP`):
- GOE evaluates `GCP_AUTO_TRANSPORT_METHODS` in priority order:
  1. `OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD` (Dataproc Serverless Batches)
  2. `OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD` (Dataproc Clusters)
  3. `OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT` (Spark Thrift Server)
  4. `OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT` (`spark-submit`)
  5. `OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY` (Apache Livy REST)
  6. `OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT` (Local Python RDBMS cursor streaming)
- Legacy Hadoop Sqoop methods (`SQOOP`, `SQOOP_BY_TABLE`) are excluded from `GCP_AUTO_TRANSPORT_METHODS`.
- `OFFLOAD_TRANSPORT_METHOD_DUCKDB` (`DUCKDB`) is strictly opt-in (`--offload-transport-method=DUCKDB`) and never selected by `AUTO`.

| Mode | Implementation Class | Command Submission | Startup Overhead |
| :--- | :--- | :--- | :--- |
| **Dataproc Serverless** | `OffloadTransportSparkBatchesGcloud` | `gcloud dataproc batches submit pyspark` | 30–60s (cold start) |
| **Dataproc Cluster** | `OffloadTransportSparkDataprocGcloud` | `gcloud dataproc jobs submit pyspark --cluster=...` | 5–10s (pre-warmed) |
| **Apache Livy** | `OffloadTransportSparkLivy` | HTTP `POST /sessions/{id}/statements` | < 2s (active session) |
| **Spark Submit** | `OffloadTransportSparkSubmit` | Subprocess / SSH `spark-submit` | 3–5s |
| **Query Import** | `OffloadTransportQueryImport` | In-process `oracledb` cursor -> Avro/Parquet | < 1s |
| **DuckDB (Opt-In)** | `OffloadTransportDuckDB` | In-process `duckdb-oracle` -> `gcss://` Parquet | < 1s |

## Query Import Modernization (`src/goe/offload/transport/query_import.py`)

- **Adaptive RDBMS Fetch Array Size**: Computes `fetch_size = min(max(100, int(10 * 1024 * 1024 / row_size)), 10_000)` based on estimated row width (`_source_table.get_max_row_size()`), targeting ~10 MiB fetch buffers bounded between `100` and `10,000` rows.
- **Single-Pass Staging Cleanup**: `_clean_staging_area()` calls `self._dfs_client.delete(self._staging_file_dir, recursive=True)` directly instead of listing and deleting individual files in a loop.

## Slicing & Parallel Extraction

To distribute data extraction across workers, GOE slices source tables via `OracleSqlEngine.build_extraction_query()` (`src/goe/offload/oracle/oracle_dialect.py`):
1. **Partition / Subpartition Slicing (`SPLIT_BY_PARTITION`, `SPLIT_BY_SUBPARTITION`)**:
   - `SELECT ... FROM "OWNER"."TABLE" PARTITION ("P1") AS OF SCN <scn>`.
2. **Extent Slicing (`SPLIT_BY_EXTENT`)**:
   - `WHERE ROWID BETWEEN CHARTOROWID(low) AND CHARTOROWID(high)`.
3. **MOD Slicing (`SPLIT_BY_MOD`)**:
   - `WHERE MOD(ORA_HASH(col), parallelism) = split_id` (Oracle) or `WHERE ABS(CHECKSUM(col)) % parallelism = split_id` (SQL Server).
4. **ID Range Slicing (`SPLIT_BY_ID_RANGE`)**:
   - Queries `MIN(id_col)` and `MAX(id_col)` and configures JDBC / batch lower and upper bounds.

## Authentication & Service Account Separation

- **Control-Plane Caller Impersonation (`--impersonate-service-account`)**:
  - Resolved via `resolve_gcloud_impersonation_principal(config)` (`GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT` falling back to `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`).
  - Applied consistently across `gcloud dataproc batches submit pyspark`, `gcloud dataproc batches describe`, and `gcloud dataproc jobs submit pyspark --cluster=...`.
- **Workload Runtime Identity (`--service-account`)**:
  - `GOOGLE_DATAPROC_SERVICE_ACCOUNT` specifies only the Dataproc Serverless batch workload execution identity (`gcloud dataproc batches submit pyspark --service-account=...`).
- **Standalone Spark GCS Connector**:
  - Non-Dataproc `spark-submit` and Livy sessions use `gcs-connector-3.0.20-shaded.jar` configured with `spark.hadoop.fs.gs.auth.type=APPLICATION_DEFAULT` and optional `spark.hadoop.fs.gs.auth.impersonation.service.account`.

## OpenTelemetry Transport, Chunk & Subprocess Spans (`src/goe/observability/transport.py`)

- **Chunk & Transport Spans**:
  - `_offload_chunk()` in `src/goe/orchestration/execution.py` wraps each chunk in `traced_chunk(chunk_number, partition_count=...)` (`goe.chunk`) and records `transport_rows` and `transport_bytes` via `record_transport_outcome()`.
  - Every `OffloadTransport.transport()` implementation wraps execution in `traced_transport(...)` (`goe.transport.<method_lower>`), recording `goe.transport.rows_fetched`, `goe.transport.bytes_staged`, and `goe.transport.duration` metrics.
- **Subprocess & Spark W3C Trace Propagation**:
  - `run_os_cmd()` (`src/goe/offload/offload_transport_functions.py`) wraps subprocess invocations in `traced_os_cmd(cmd)` (`goe.os_cmd.<executable>`) and injects `TRACEPARENT`, `TRACESTATE`, and `GOE_EXECUTION_ID` into the child environment when OpenTelemetry is enabled.
  - Spark transports (`spark-submit`, Dataproc Gcloud, Dataproc Batches) merge `spark_trace_conf_overrides()` (`spark.executorEnv.TRACEPARENT`, `spark.executorEnv.GOE_EXECUTION_ID`, `spark.yarn.appMasterEnv.TRACEPARENT`, `spark.dataproc.driverEnv.TRACEPARENT`) and append spec-compliant Google SQLCommenter comments (`build_transport_sql_comment()`) to JDBC extraction queries when OpenTelemetry is enabled.
