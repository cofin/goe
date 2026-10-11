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

## Authentication & Service Account Separation

- **Control-Plane Caller Impersonation (`--impersonate-service-account`)**:
  - Resolved via `resolve_gcloud_impersonation_principal(config)` (`GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT` falling back to `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`).
  - Applied consistently across `gcloud dataproc batches submit pyspark`, `gcloud dataproc batches describe`, and `gcloud dataproc jobs submit pyspark --cluster=...`.
- **Workload Runtime Identity (`--service-account`)**:
  - `GOOGLE_DATAPROC_SERVICE_ACCOUNT` specifies only the Dataproc Serverless batch workload execution identity (`gcloud dataproc batches submit pyspark --service-account=...`) and is never conflated with `gcloud` control-plane caller impersonation.
- **Standalone Spark GCS Connector**:
  - Non-Dataproc `spark-submit` and Livy sessions use `gcs-connector-3.0.20-shaded.jar` configured with `spark.hadoop.fs.gs.auth.type=APPLICATION_DEFAULT` and optional `spark.hadoop.fs.gs.auth.impersonation.service.account`.
