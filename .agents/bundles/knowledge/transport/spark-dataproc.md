---
type: Reference
title: Dataproc & Spark Execution Engines
description: Spark transport architectures, Dataproc Serverless Batches, Livy REST, and parallel JDBC slicing
tags:
  - reference
  - transport
  - spark
  - dataproc
  - livy
---

# Dataproc & Spark Execution Engines

The Spark transport engine (`src/goe/offload/spark/` & `offload_transport.py`) orchestrates parallel data extraction from source RDBMS to cloud storage.

## Execution Topologies

| Mode | Implementation Class | Command Submission | Startup Overhead |
| :--- | :--- | :--- | :--- |
| **Dataproc Serverless** | `OffloadTransportSparkBatchesGcloud` | `gcloud dataproc batches submit pyspark` | 30–60s (cold start) |
| **Dataproc Cluster** | `OffloadTransportSparkDataprocGcloud` | `gcloud dataproc jobs submit pyspark --cluster=...` | 5–10s (pre-warmed) |
| **Apache Livy** | `OffloadTransportSparkLivy` | HTTP `POST /sessions/{id}/statements` | < 2s (active session) |
| **Spark Submit** | `OffloadTransportSparkSubmit` | Subprocess / SSH `spark-submit` | 3–5s |

## Slicing & Parallel Extraction

To distribute data extraction across Spark executors, GOE slices source tables:
1. **MOD Slicing (`SPLIT_BY_MOD`)**:
   - `WHERE MOD(ORA_HASH(col), parallelism) = split_id` (Oracle).
   - `WHERE ABS(CHECKSUM(col)) % parallelism = split_id` (SQL Server).
2. **ID Range Slicing (`SPLIT_BY_ID_RANGE`)**:
   - Queries `MIN(id_col)` and `MAX(id_col)` and configures PySpark JDBC options: `lowerBound`, `upperBound`, `numPartitions`, `partitionColumn`.
3. **Native Range Slicing (`SPLIT_BY_NATIVE_RANGE`)**:
   - Direct partition querying per executor task.
