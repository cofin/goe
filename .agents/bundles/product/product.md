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
- GOE (Gluent Offload Engine) orchestrates high-throughput, consistent data offloading from RDBMS (Oracle, SQL Server, Teradata) to cloud data warehouses (Google BigQuery, Snowflake, Azure Synapse) and Hadoop engines.
- Provides non-invasive data movement preserving RDBMS transactional snapshot consistency (via SCN / Flashback) without requiring source table downtime.
- Supports Full Table Offload, Partition-Based Incremental Offload (Range, List, List-as-Range), and Predicate-Based Offload.
- Employs a 3-tier canonical column typing abstraction to ensure lossless type conversion across disparate SQL dialects.
- Includes a standalone REST Listener service (FastAPI, Redis) for remote execution and real-time event streaming.
<!-- truth: end -->

## Core Capabilities

### 1. Data Offloading Modes
- **Full Offload**: Migrates complete source tables into backend cloud data warehouses, applying optimal clustering, partitioning, and compression.
- **Incremental Partition Offload (IPA)**: Incrementally offloads historical partitions based on age (`--older-than-days`, `--older-than-date`), high-water marks, or partition name filters.
- **Predicate-Based Offload (PBO)**: Offloads arbitrary row slices using Lark-parsed AST WHERE predicates with automatic synthetic partition pruning.

### 2. Virtualization & Hybrid Queries
- Generates transparent Oracle hybrid views combining active online partitions in the RDBMS with historical offloaded data in BigQuery/Snowflake.
- Allows legacy applications and BI tools to query unified datasets seamlessly without code rewrites.

### 3. Distributed Transport & High-Performance Slicing
- Uses PySpark on Google Cloud Dataproc (Serverless Batches or persistent clusters) and Apache Livy to execute parallel JDBC extraction.
- Implements intelligent query splitting algorithms: `MOD` hashing (`ORA_HASH` / `CHECKSUM`), integer range splitting (`ID_RANGE`), and native partition slicing.
- Streams data through cloud storage staging buckets (GCS, S3, Azure Blob) formatted as Avro or Snappy-compressed Parquet.

### 4. Continuous Verification & Schema Evolution
- Built-in post-offload validation comparing source and target row counts, boundary ranges, and deep aggregation checksums (`MIN`, `MAX`, `SUM`, `AVG`).
- Automatic schema synchronization (`schema_sync`) detecting upstream column additions, alterations, and data type evolutions.
