---
type: Guide
title: Technology Stack
description: Core programming languages, database drivers, cloud engines, storage systems, and dependencies
tags:
  - guide
  - product
  - tech-stack
  - dependencies
---

# Technology Stack

<!-- truth: start -->
- **Language**: Python >= 3.8 (CPython) with type annotations.
- **Frontend Databases**: Oracle (`oracledb`), MS SQL Server (`pymssql`), Teradata (`pyodbc`).
- **Cloud DW Backends**: Google BigQuery (`google-cloud-bigquery`), Snowflake (`snowflake-connector-python`), Azure Synapse (`pyodbc`), Apache Hadoop (`better_impyla`).
- **Storage Systems**: Google Cloud Storage (`google-cloud-storage`, `fsspec[gcs]`), AWS S3 (`boto3`), Azure Blob / ADLS Gen2 (`azure-storage-blob`), HDFS (`hdfs`).
- **Compute & Transport**: PySpark, Google Cloud Dataproc (Serverless Batches & Clusters), Apache Livy, Scala 2.12/2.13 (`GOETaskListener`).
- **Data Serialization**: Apache Avro (`avro`, custom `AvroEncoder`), Apache Parquet (`pyarrow`, `ParquetEncoder`).
- **Listener & Services**: FastAPI, Uvicorn, Gunicorn, Redis (`redis-py`), Pydantic, msgspec, Brotli.
<!-- truth: end -->

## Subsystem Details

### 1. Python Runtime & Core Libraries
- **Base Environment**: Python >= 3.12 managed with `uv` virtual environments.
- **CLI & Parsing**: Standard library `optparse` / `argparse` wrapped by `goe.orchestration.cli_entry_points`, `lark-parser` for AST predicate grammar parsing.
- **Concurrency & Locking**: `filelock` for process mutual exclusion, `threading` for asynchronous telemetry scrapers.
- **Data Serialization**: `pyarrow` (columnar memory buffers), `avro` (schema validation and row serialization), `msgspec` (high-performance JSON serialization and typed Struct models), `sqlspec` (database abstraction layer).

### 2. Frontend RDBMS Connectivity
- **Oracle**: `oracledb` (Thin mode default, Thick mode for Oracle Wallet / OCI features), `DBMS_APPLICATION_INFO` session telemetry, `DBMS_METADATA` DDL extraction.
- **SQL Server**: `pymssql` with strict session initializers (`ARITHABORT`, `DATEFORMAT ymd`, `ANSI_WARNINGS`).
- **Teradata**: `pyodbc` with fast parameter execution batching (`fast_executemany` up to 7MB payload limits).

### 3. Backend Cloud Data Platforms
- **Google BigQuery**: `google-cloud-bigquery` with UTC connection normalization, KMS CMEK encryption, and slot resource telemetry.
- **Snowflake**: `snowflake-connector-python` with external storage integrations, RSA private key / password auth, and `COPY INTO` projection.
- **Azure Synapse**: `pyodbc` with Managed Identity (`ActiveDirectoryMsi`), Dedicated/Serverless SQL pools, and clustered columnstore indexing.
- **Hadoop Ecosystem**: `better_impyla` over HiveServer2 Thrift protocol (TCP/HTTP), Kerberos SPNEGO / GSSAPI authentication, and Apache Ranger / Sentry privilege checks.

### 4. Distributed Transport & Cloud Storage
- **Spark Ecosystem**: PySpark JDBC extraction, custom Scala listener (`GOETaskListener`) compiling across Spark 3.0 through 3.5 on Scala 2.12 and 2.13.
- **Multi-Cloud DFS**: Unified filesystem abstraction layer supporting GCS (`gs://`), S3 (`s3a://`), Azure ADLS Gen2 (`abfss://`), and HDFS (`hdfs://`, `webhdfs://`).
