---
type: Guide
title: Technology Stack
description: Core programming languages, database drivers, SQL engines, cloud platforms, transport engines, observability, and dependencies
tags:
  - guide
  - product
  - tech-stack
  - dependencies
---

# Technology Stack

<!-- truth: start -->
- **Language**: Python >= 3.12 (CPython) with PEP 585/604 type annotations, `FrozenBaseStruct` / `BaseStruct` (`gc=False` in `src/goe/typing.py`), and strict `mypy` + `tools/verify_architecture.py` verification.
- **Frontend Databases & SQL Layer**: Oracle (`oracledb`, SQLSpec `OracleGateway` with `SQLFileLoader`), MS SQL Server (`pymssql`), Pluggable SQL Dialect Protocols (`src/goe/offload/sql_engine.py`, `sqlglot>=30.17.0` with custom Oracle `AS OF SCN`/`PARTITION` dialect extension).
- **Cloud DW Backends**: Google BigQuery (`google-cloud-bigquery`, native `load_table_from_uri` + `INFORMATION_SCHEMA.PARTITIONS`), Snowflake (`snowflake-connector-python`), Azure Synapse (`pyodbc`), Apache Hadoop (`better_impyla`).
- **Storage Systems**: Google Cloud Storage (`google-cloud-storage`), AWS S3 (`boto3`), Azure Blob / ADLS Gen2 (`azure-storage-blob`), HDFS (`hdfs`).
- **Compute & Transport**: PySpark, Google Cloud Dataproc (Serverless Batches & Clusters), Apache Livy, Scala 2.12/2.13 (`GOETaskListener`), opt-in DuckDB (`duckdb==2.0.0`, `cofin/duckdb-oracle`, community `gcs` extension).
- **Data Serialization**: Apache Parquet (`pyarrow`, `ParquetEncoder`, default on GCP), Apache Avro (`avro`, `AvroEncoder`), `msgspec` (`src/goe/serializers.py`), `sqlspec[performance,oracledb,adbc,duckdb]>=0.68.0`.
- **Listener & Observability**: Litestar (`>=2.8.0`), Granian (`litestar-granian`), `litestar-queues` (in-memory ASGI queue backend), `litestar-security`, `litestar-autowire`, `litestar-mcp`, embedded `MemoryCache` / `MemorySyncCache`, OpenTelemetry (`opentelemetry-api>=1.40.0` core + optional `otel` extra for SDK/OTLP/GCP Telemetry API).
<!-- truth: end -->

## Subsystem Details

### 1. Python Runtime & Core Libraries
- **Base Environment**: Python >= 3.12 managed with `uv` virtual environments and `hatchling.build`.
- **CLI & Parsing**: Unified `rich-click` CLI (`goe` entrypoint in `src/goe/cli/main.py`) with zero-type-loss lazy binding (`src/goe/cli/_lazy.py`), declarative `OptionSpec` registry (`src/goe/config/option_registry.py`), Click option builders (`src/goe/cli/options.py`), `GOESettings` (`src/goe/config/settings.py`), typed `msgspec.Struct` option models (`src/goe/config/options.py`), and `lark` (>= 1.1.9) for AST predicate grammar parsing.
- **SQL & Persistence**: `sqlspec[performance,oracledb,adbc,duckdb]>=0.68.0` (`OracleGateway`, `SQLFileLoader`, `SQLCommenterContext`) and pluggable protocol-based SQL AST builders (`src/goe/offload/sql_engine.py`, backed by `sqlglot>=30.17.0` and `src/goe/offload/oracle/oracle_dialect.py`).
- **Concurrency & Locking**: `filelock` (`src/goe/platform/locking.py`) for process mutual exclusion, `src/goe/platform/worker.py` (`LocalProcessWorker`, `LameDuckController`, `CgroupQuota`), and `src/goe/util/concurrency.py` (`run_bounded`) for bounded thread-pool execution with context propagation.
- **Data Serialization**: `pyarrow` (columnar memory buffers), `avro` (schema validation and row serialization), `msgspec` (`src/goe/typing.py` and `src/goe/serializers.py`).

### 2. Frontend RDBMS Connectivity
- **Oracle**: `oracledb` (Thin mode default, Thick mode for Oracle Wallet / OCI features), `OracleGateway` named SQL execution (`frontend_metadata.sql`, `oracle_repo.sql`), `DBMS_APPLICATION_INFO` session telemetry (`MODULE`/`ACTION` + `V$SESSION.CLIENT_INFO` W3C `traceparent`), `DBMS_METADATA` DDL extraction.
- **SQL Server**: `pymssql` with strict session initializers (`ARITHABORT`, `DATEFORMAT ymd`, `ANSI_WARNINGS`).

### 3. Backend Cloud Data Platforms
- **Google BigQuery**: `google-cloud-bigquery` with keyless ADC/impersonation (`resolve_gcp_credentials`), UTC connection normalization, native `load_table_from_uri` staged loading (`BIGQUERY_LOAD_TABLE_MODE=NATIVE`), parameterized GoogleSQL `INFORMATION_SCHEMA.PARTITIONS`, KMS CMEK encryption, job labels, and OpenTelemetry spans/metrics.
- **Snowflake**: `snowflake-connector-python` with external storage integrations, RSA private key / password auth, and `COPY INTO` projection.
- **Azure Synapse**: `pyodbc` with Managed Identity (`ActiveDirectoryMsi`), Dedicated/Serverless SQL pools, and clustered columnstore indexing.
- **Hadoop Ecosystem**: `better_impyla` over HiveServer2 Thrift protocol (TCP/HTTP), Kerberos SPNEGO / GSSAPI authentication, and Apache Ranger / Sentry privilege checks.

### 4. Distributed & Local Transport & Cloud Storage
- **Spark Ecosystem**: PySpark JDBC extraction, GCP-first `AUTO` transport order (`GCP_AUTO_TRANSPORT_METHODS`), custom Scala listener (`GOETaskListener`) compiling across Spark 3.0 through 3.5 on Scala 2.12 and 2.13.
- **Opt-In DuckDB Transport**: `OffloadTransportDuckDB` (`--offload-transport-method=DUCKDB`) using `duckdb==1.5.5`, `cofin/duckdb-oracle` (`oracle_query` with mandatory `AS OF SCN` verification), and the community `gcs` extension (`gcss://` + dual-mode ADC secrets).
- **Multi-Cloud DFS**: Unified filesystem abstraction layer supporting GCS (`gs://`, atomic `if_generation_match` uploads and single-pass `delete_blobs`), S3 (`s3a://`), Azure ADLS Gen2 (`abfss://`), and HDFS (`hdfs://`, `webhdfs://`).

### 5. OpenTelemetry Observability (`src/goe/observability/`)
- **Core API & Optional SDK (`otel` extra)**: Zero-cost no-op default when `GOE_OTEL_ENABLED=false`; supports OTLP (`grpc` / `http/protobuf`), Google Cloud Telemetry (OTLP) API (`https://telemetry.googleapis.com` via `resolve_gcp_credentials`), local JSONL, console, and in-memory exporters.
- **Correlation**: `ExecutionId` <-> W3C `traceparent`/`baggage`/SQLSpec `CorrelationContext` bridge, `OFFLOAD_REPO` `_trace_id`/`_span_id` persistence, `GOELogFileHandle` JSON/JSONL sidecar correlation, and Litestar `OpenTelemetryPlugin` + `litestar-queues` + `LitestarMCP` span hooks.
