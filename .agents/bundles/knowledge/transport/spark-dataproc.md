---
type: Reference
title: Dataproc, Spark, DuckDB & Query Import Execution Engines
description: Cost-based TransportSelector, decomposed transport packages, Dataproc Serverless Batches, Livy REST, Query Import Arrow Parquet streaming, and OpenTelemetry transport spans
tags:
  - reference
  - transport
  - spark
  - dataproc
  - duckdb
  - livy
  - opentelemetry
updated_at: "2026-10-26T18:05:00Z"
---

# Dataproc, Spark, DuckDB & Query Import Execution Engines

The transport layer (`src/goe/offload/transport/` & `src/goe/offload/transport/spark/`) orchestrates data extraction from source RDBMS to cloud storage staging files.

## Package Decomposition (`src/goe/offload/transport/`)

- **`protocol.py`**: Defines `@runtime_checkable class OffloadTransportProtocol(Protocol)`, `TransportPlan(FrozenBaseStruct)`, `TransportValidationStatus(FrozenBaseStruct)`, `OffloadTransport`, and `OffloadTransportRdbms` (replacing the retired monolithic `src/goe/offload/offload_transport.py`, `base.py`, `factory.py`, and `availability.py` modules).
- **`selector.py`**: Defines `TransportSelector` (`select()`, `offload_transport_factory()`, `choose_offload_transport_method()`, `is_offload_transport_method_available()`) with cost-based size thresholds (`QUERY_IMPORT_MAX_BYTES = 5 * 1024**3`, `DUCKDB_DEFAULT_MAX_BYTES = 100 * 1024**3`).
- **`canary.py`**: Defines `TransportCanaryPinger` (`ping_rdbms()`, `validate_transport_paths()`) for connectivity verification (`SELECT 1 FROM DUAL` / `SELECT 1` and Spark/Dataproc/Thrift/Livy canary checks).
- **`spark/` (`src/goe/offload/transport/spark/`)**:
  - `polling.py`: `OffloadTransportPollingThread` background metrics poller.
  - `spark_submit.py`: `OffloadTransportSparkSubmit` (`spark-submit` CLI transport).
  - `spark_thrift.py`: `OffloadTransportSparkThrift` (Spark Thrift Server transport).
  - `spark_livy.py`: `OffloadTransportSparkLivy` and `OffloadTransportLivyApi` (Apache Livy REST transport).
  - `dataproc.py`: `OffloadTransportSparkDataprocGcloud` and `OffloadTransportSparkBatchesGcloud` (`gcloud dataproc` cluster jobs and Serverless Batches).
- **`tools/spark-listener/`**: Targets Scala `2.12.18` and Spark `3.5.3` (`build.sbt`) using SLF4J (`org.slf4j.LoggerFactory`) in `GOETaskListener.scala`.

## Cost-Based `AUTO` Selection (`TransportSelector`)

When `OFFLOAD_TRANSPORT=AUTO` (`choose_offload_transport_method` in `src/goe/offload/transport/selector.py`):
- **Small Offloads (`0 < estimated_bytes <= 5 GiB`)**: Selects `OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT` when available to avoid JVM/cluster cold-start latency.
- **Medium Offloads (`5 GiB < estimated_bytes <= 100 GiB`, or when size is unknown and `DUCKDB` is eligible on GCP)**: Selects `OFFLOAD_TRANSPORT_METHOD_DUCKDB` when `is_duckdb_available()` is satisfied.
- **Large Offloads (`estimated_bytes > 100 GiB`) or Non-DuckDB Environments**: Evaluates Spark transports in priority order (`SPARK_BATCHES_GCLOUD` -> `SPARK_DATAPROC_GCLOUD` -> `SPARK_THRIFT` -> `SPARK_SUBMIT` -> `SPARK_LIVY`), falling back to `DUCKDB` or `QUERY_IMPORT`.
- Legacy Hadoop Sqoop methods (`SQOOP`, `SQOOP_BY_TABLE`) have been completely removed.

| Mode | Implementation Class | Command Submission | Typical Workload Tier |
| :--- | :--- | :--- | :--- |
| **Query Import** | `OffloadTransportQueryImport` | In-process `oracledb` Arrow batches -> Parquet + `StagingStorageService` | `<= 5 GiB` (`< 1s` startup) |
| **DuckDB** | `OffloadTransportDuckDB` | In-process `duckdb-oracle` -> `gcss://` Parquet | `5 GiB – 100 GiB` (`< 1s` startup) |
| **Dataproc Serverless** | `OffloadTransportSparkBatchesGcloud` | `gcloud dataproc batches submit pyspark` | `> 100 GiB` (30–60s cold start) |
| **Dataproc Cluster** | `OffloadTransportSparkDataprocGcloud` | `gcloud dataproc jobs submit pyspark --cluster=...` | `> 100 GiB` (5–10s pre-warmed) |
| **Apache Livy** | `OffloadTransportSparkLivy` | HTTP `POST /sessions/{id}/statements` | Pre-warmed Spark cluster (`< 2s`) |
| **Spark Submit** | `OffloadTransportSparkSubmit` | Subprocess / SSH `spark-submit` | Dedicated YARN/Standalone cluster |

## Query Import Arrow Parquet Pipeline (`src/goe/offload/transport/query_import.py`)

- **Zero-Python-Row Arrow Extraction**: `OffloadTransportQueryImport` streams RDBMS batches through `extract_oracle_to_parquet()` (`OracleArrowBatchExtractor` + `ArrowParquetStagingWriter`) into Snappy-compressed local Parquet files and uploads them to cloud staging via `StagingStorageService.upload_file()` (with compatibility hooks for `self._dfs_client.copy_from_local` and `self._staging_file.get_Staging_file_name()`).
- **Adaptive RDBMS Fetch Array Size**: Computes `fetch_size = min(max(100, int(10 * 1024 * 1024 / row_size)), 10_000)` based on estimated row width (`_source_table.get_max_row_size()`), targeting ~10 MiB fetch buffers bounded between `100` and `10,000` rows.
- **Single-Pass Staging Cleanup**: `_clean_staging_area()` calls `self._dfs_client.delete(self._staging_file_dir, recursive=True)` directly.

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
