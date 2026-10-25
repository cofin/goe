---
type: Guide
title: Product Definition
description: Vision, core offload capabilities, and architecture overview of the GOE data framework
tags:
  - guide
  - product
  - vision
  - offload
---

# Product Definition

<!-- truth: start -->
- GOE (Gluent Offload Engine) orchestrates high-throughput, consistent data offloading from RDBMS (Oracle, SQL Server) to cloud data warehouses (Google BigQuery, Snowflake, Azure Synapse) and Hadoop engines.
- Provides non-invasive data movement preserving RDBMS transactional snapshot consistency (via SCN / Flashback) without requiring source table downtime.
- Supports Full Table Offload, Partition-Based Incremental Offload (Range, List, List-as-Range), and Predicate-Based Offload.
- Employs a declarative `AdapterRegistry` (`src/goe/offload/registry.py`), a 3-tier canonical column typing abstraction, and pluggable Protocol-based SQL dialect engines (`src/goe/offload/sql_engine.py`) to ensure lossless type conversion and SQL generation across disparate dialects.
- Includes a concurrent pre-flight connectivity runner (`ConnectRunner` in `src/goe/connect/runner.py`), a REST Listener and MCP service (Litestar, Granian, `litestar-queues`, in-process `MemoryCache`), and opt-in end-to-end OpenTelemetry observability (`src/goe/observability/`).
<!-- truth: end -->

## Core Capabilities

### 1. Data Offloading Modes
- **Full Offload**: Migrates complete source tables into backend cloud data warehouses, applying optimal clustering, partitioning, and compression.
- **Incremental Partition Offload (IPA)**: Incrementally offloads historical partitions based on age (`--older-than-days`, `--older-than-date`), high-water marks, or partition name filters.
- **Predicate-Based Offload (PBO)**: Offloads arbitrary row slices using Lark-parsed AST WHERE predicates rendered via `PredicateSqlEngine` with automatic synthetic partition pruning.

### 2. Virtualization & Hybrid Queries
- Generates transparent Oracle hybrid views combining active online partitions in the RDBMS with historical offloaded data in BigQuery/Snowflake.
- Allows legacy applications and BI tools to query unified datasets seamlessly without code rewrites.

### 3. Distributed & Local Transport Engines
- Uses PySpark on Google Cloud Dataproc (Serverless Batches or persistent clusters) and Apache Livy to execute parallel JDBC extraction, with GCP-first `AUTO` transport selection (`GCP_AUTO_TRANSPORT_METHODS`).
- Provides an opt-in, zero-JVM local DuckDB transport engine (`--offload-transport-method=DUCKDB`) powered by `cofin/duckdb-oracle` (`oracle_query`) and the community `gcs` extension (`gcss://`) for streaming Oracle rows directly to GCS Parquet files.
- Implements intelligent query splitting algorithms: `MOD` hashing (`ORA_HASH` / `CHECKSUM`), integer range splitting (`ID_RANGE`), extent ROWID ranges (`SPLIT_BY_EXTENT`), and native partition/subpartition slicing.
- Streams data through cloud storage staging buckets (GCS with Parquet default, S3, Azure Blob) and loads into BigQuery via native `load_table_from_uri` jobs (`BIGQUERY_LOAD_TABLE_MODE=NATIVE`) or external staging tables (`EXTERNAL`).

### 4. Continuous Verification, Schema Evolution & Observability
- Built-in post-offload validation (`ValidationSqlEngine` / `CrossDbValidator`) comparing source and target row counts, boundary ranges, and deep aggregation checksums (`MIN`, `MAX`, `SUM`, `AVG`).
- Automatic schema synchronization (`schema_sync`) detecting upstream column additions, alterations, and data type evolutions.
- Opt-in, zero-cost-by-default OpenTelemetry tracing, metrics, and structured JSONL log correlation (`GOE_OTEL_ENABLED=true`) spanning CLI commands, orchestration steps, Listener HTTP/MCP/queue workers, `OracleGateway` SQLSpec queries (`V$SESSION.CLIENT_INFO` + SQLCommenter), offload transports, GCS, and BigQuery.
