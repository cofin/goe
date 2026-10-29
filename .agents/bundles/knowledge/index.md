---
type: Guide
title: Knowledge Base
description: Technical architecture, database adapters, transport engines, services, operations, observability, and development standards
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

### 2. [Patterns & Conventions](patterns/index.md)
- [Serialization & Utility Re-Export Patterns](patterns/serialization-and-utils.md) - `sqlspec.utils` re-exports in `src/goe/util/` and `msgspec.Struct` schemas.
- [Centralized Rich-Click CLI](patterns/cli-architecture.md) - Unified `goe` CLI (`src/goe/cli/`) (sole entrypoint; no `bin/` wrappers).
- [Data Offload, Canonical Typing & Storage Gotchas](patterns/offload-and-typing.md) - Three-tier column mapping, snapshot-consistent reads, staged ingestion, and Oracle sampling gotchas.

### 3. [Architecture & Orchestration](architecture/index.md)
- [Orchestration Core](architecture/orchestration.md) - `OrchestrationRunner`, locking, execution IDs, OpenTelemetry context bridge, and command steps.
- [Offload Lifecycle](architecture/offload-lifecycle.md) - Step-by-step data offloading flow from discovery to verification.
- [Canonical Type Mapping](architecture/type-mapping.md) - 3-tier typing system, sampling algorithms, and type conversion matrices.
- [Schema Evolution](architecture/schema-evolution.md) - `schema_sync` analysis, difference vector resolution, and DDL generation.

### 4. [Frontend RDBMS Adapters](frontends/index.md)
- [Oracle Adapter](frontends/oracle.md) - `oracledb`, SQLSpec `OracleGateway`, named SQL files, custom Oracle dialect AST (`AS OF SCN` / `PARTITION`), PL/SQL packages, and `V$SESSION.CLIENT_INFO` trace tagging.
- [SQL Server Adapter](frontends/sqlserver.md) - `pymssql`, session initialization, space sizing, and catalog extraction.

### 5. [Backend Cloud DW Adapters](backends/index.md)
- [Google BigQuery](backends/bigquery.md) - `google-cloud-bigquery`, `BigQuerySqlEngine`, native `load_table_from_uri` ingestion (`BIGQUERY_LOAD_TABLE_MODE`), `INFORMATION_SCHEMA.PARTITIONS`, KMS CMEK, and OpenTelemetry spans/metrics.
- [Snowflake](backends/snowflake.md) - `snowflake-connector-python`, stages, storage integrations, and `COPY INTO` projection.
- [Azure Synapse](backends/synapse.md) - `pyodbc`, PolyBase, clustered columnstore indexing, and table distributions.
- [Hadoop / Impala / Hive](backends/hadoop.md) - `better_impyla`, HiveServer2 Thrift, Kerberos, and incremental statistics.

### 6. [Multi-Cloud Storage Abstraction](storage/index.md)
- [Google Cloud Storage](storage/gcs.md) - `GOEGcs`, keyless ADC authentication, `if_generation_match` upload preconditions, single-pass `delete_blobs`, and `@traced_storage_call` spans.
- [Amazon S3](storage/s3.md) - `GOES3`, IAM credentials, bucket operations, and multipart cleanup.
- [Azure Blob & ADLS Gen2](storage/azure-blob.md) - `GOEAzure`, hierarchical namespace deletion, and token auth.
- [HDFS & WebHDFS](storage/hdfs.md) - `CliHdfs`, `WebHdfs`, Kerberos ticket management, and active NameNode discovery.

### 7. [Data Transport, Spark & DuckDB](transport/index.md)
- [Dataproc, Spark & Query Import Engines](transport/spark-dataproc.md) - GCP-first `AUTO` transport order, Serverless Batches, Dataproc clusters, Livy REST, Query Import, JDBC splitting, and transport OpenTelemetry spans.
- [DuckDB & `duckdb-oracle` Offload Transport](transport/duckdb.md) - Opt-in zero-JVM `OffloadTransportDuckDB` (`--offload-transport-method=DUCKDB`), `cofin/duckdb-oracle`, community `gcs` extension (`gcss://`), mandatory `AS OF SCN` verification, and per-batch spans.
- [Spark Task Listener](transport/spark-listener.md) - Custom Scala `GOETaskListener`, metric capture, and compilation matrices.
- [Staging & Serialization](transport/staging-serialization.md) - Parquet (default on GCP) and Avro encoding, Base64 binary handling, and chunk buffers.

### 8. [GOE Listener Service](listener/index.md)
- [REST API Architecture](listener/rest-api.md) - Litestar application factory, Granian ASGI runtime, `litestar-security` guards, `litestar-autowire` DI, `litestar-mcp` tools, and `OpenTelemetryPlugin` / queue / MCP telemetry (`src/goe/listener/telemetry.py`).
- [Listener Workers & Embedded Caching](listener/worker-and-redis.md) - `litestar-queues` background tasks, node heartbeats, scheduled cron jobs, and embedded in-process TTL caching.

### 9. [Operations & Tooling](operations/index.md)
- [CLI Utilities](operations/cli-tools.md) - `offload`, `connect`, `logmgr`, `agg_validate`, and `listener` commands.
- [Offload Home Runtime](operations/offload-home.md) - Directory layout, build targets, packaging, and virtualenv management.
- [Configuration Reference](operations/configuration-and-env.md) - Full inventory of environment variables, defaults, and validation.
- [OpenTelemetry Observability](operations/observability.md) - Zero-cost-by-default tracing, metrics, `ExecutionId` context bridge, OTLP / Google Cloud Telemetry API exporters, and JSONL log correlation.
- [Database Installation](operations/database-installation.md) - Oracle DDL scripts, user privileges, packages, and upgrade paths.
- [Container & Cloud Run](operations/cloud-run-deployment.md) - Google Cloud Run Jobs container deployment and networking.

### 10. [Development Standards](standards/index.md)
- [Python Standards](standards/python.md) - Coding standards, type annotations, formatting, docstrings, and error handling.
- [Database & SQL Standards](standards/database-and-sql.md) - Pluggable SQL dialect protocols (`sql_engine.py`), SQLSpec `OracleGateway` conventions, and transactional snapshot safety.
- [Shell & Tooling Standards](standards/shell-and-tooling.md) - Bash script conventions and build tooling.
- [Testing & Quality Assurance](standards/testing.md) - Unit testing, integration test harness, and mock databases.
