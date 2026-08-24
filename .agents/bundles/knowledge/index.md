---
type: Guide
title: Knowledge Base
description: Technical architecture, database adapters, transport engines, services, operations, and development standards
tags:
  - guide
  - knowledge
  - index
---

# GOE Knowledge Base

The GOE Knowledge Base is organized into focused sub-domains containing comprehensive technical reference documentation, architectural blueprints, engine-specific adapters, and development standards.

## Knowledge Sub-Domains

### 1. [Workflow & Operational Commands](workflow.md)
Canonical setup, development, testing, packaging, and validation workflows with repository-native commands.

### 2. [Patterns & Conventions](patterns.md)
Consolidated architectural patterns, coding conventions, gotchas, and specialized skill associations.

### 3. [Architecture & Orchestration](architecture/index.md)
- [Orchestration Core](architecture/orchestration.md) - `OrchestrationRunner`, locking, execution IDs, and command steps.
- [Offload Lifecycle](architecture/offload-lifecycle.md) - Step-by-step data offloading flow from discovery to verification.
- [Canonical Type Mapping](architecture/type-mapping.md) - 3-tier typing system, sampling algorithms, and type conversion matrices.
- [Schema Evolution](architecture/schema-evolution.md) - `schema_sync` analysis, difference vector resolution, and DDL generation.

### 4. [Frontend RDBMS Adapters](frontends/index.md)
- [Oracle Adapter](frontends/oracle.md) - `oracledb`, SCN snapshots, PL/SQL packages, partitioning, and extent chunking.
- [SQL Server Adapter](frontends/sqlserver.md) - `pymssql`, session initialization, space sizing, and catalog extraction.
- [Teradata Adapter](frontends/teradata.md) - `pyodbc`, batch parameter streaming, and `RANGE_N` partition parsing.

### 5. [Backend Cloud DW Adapters](backends/index.md)
- [Google BigQuery](backends/bigquery.md) - `google-cloud-bigquery`, date/integer partitioning, clustering, KMS, and slot telemetry.
- [Snowflake](backends/snowflake.md) - `snowflake-connector-python`, stages, storage integrations, and `COPY INTO` projection.
- [Azure Synapse](backends/synapse.md) - `pyodbc`, PolyBase, clustered columnstore indexing, and table distributions.
- [Hadoop / Impala / Hive](backends/hadoop.md) - `better_impyla`, HiveServer2 Thrift, Kerberos, and incremental statistics.

### 6. [Multi-Cloud Storage Abstraction](storage/index.md)
- [Google Cloud Storage](storage/gcs.md) - `GOEGcs`, Application Default Credentials, prefix operations, and consistency retries.
- [Amazon S3](storage/s3.md) - `GOES3`, IAM credentials, bucket operations, and multipart cleanup.
- [Azure Blob & ADLS Gen2](storage/azure-blob.md) - `GOEAzure`, hierarchical namespace deletion, and token auth.
- [HDFS & WebHDFS](storage/hdfs.md) - `CliHdfs`, `WebHdfs`, Kerberos ticket management, and active NameNode discovery.

### 7. [Data Transport & Spark](transport/index.md)
- [Dataproc & Spark Engines](transport/spark-dataproc.md) - Serverless Batches, Dataproc clusters, Livy REST, and JDBC splitting.
- [Spark Task Listener](transport/spark-listener.md) - Custom Scala `GOETaskListener`, metric capture, and compilation matrices.
- [Staging & Serialization](transport/staging-serialization.md) - Avro and Parquet encoding, Base64 binary handling, and chunk buffers.

### 8. [GOE Listener Service](listener/index.md)
- [REST API Architecture](listener/rest-api.md) - FastAPI application factory, endpoints, security middleware, and compression.
- [Workers & Redis Cache](listener/worker-and-redis.md) - Task queues, node heartbeats, scheduled cron jobs, and event streaming.

### 9. [Operations & Tooling](operations/index.md)
- [CLI Utilities](operations/cli-tools.md) - `offload`, `connect`, `logmgr`, `agg_validate`, and `listener` commands.
- [Offload Home Runtime](operations/offload-home.md) - Directory layout, build targets, packaging, and virtualenv management.
- [Configuration Reference](operations/configuration-and-env.md) - Full inventory of environment variables, defaults, and validation.
- [Database Installation](operations/database-installation.md) - Oracle DDL scripts, user privileges, packages, and upgrade paths.
- [Container & Cloud Run](operations/cloud-run-deployment.md) - Google Cloud Run Jobs container deployment and networking.

### 10. [Development Standards](standards/index.md)
- [Python Standards](standards/python.md) - Coding standards, type annotations, formatting, docstrings, and error handling.
- [Database & SQL Standards](standards/database-and-sql.md) - SQL formatting, dialect abstraction, and transactional safety.
- [Shell & Tooling Standards](standards/shell-and-tooling.md) - Bash script conventions and build tooling.
- [Testing & Quality Assurance](standards/testing.md) - Unit testing, integration test harness, and mock databases.
