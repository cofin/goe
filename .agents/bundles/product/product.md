---
type: product
title: Product Definition
description: Vision, core offload capabilities, and architectural overview of the Gluent Offload Engine (GOE).
status: stable
tags:
  - product
  - vision
  - offload
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: offload-pipeline
    resource: src/goe/orchestration/pipeline.py::OffloadPipeline
    title: Staged Offload Pipeline Orchestrator
  - id: adapter-registry
    resource: src/goe/offload/registry.py::AdapterRegistry
    title: Declarative Frontend/Backend/Filesystem Adapter Registry
  - id: listener-app
    resource: src/goe/listener/app.py::create_app
    title: Litestar Listener and MCP Application Factory
---

# Product Definition

<!-- truth: start -->
- GOE (Gluent Offload Engine) orchestrates high-throughput, snapshot-consistent data offloading from relational frontends (Oracle, Microsoft SQL Server) to analytical cloud backends (Google BigQuery, Snowflake, Azure Synapse) and Hadoop engines.[^offload-pipeline]
- Preserves relational transactional snapshot consistency using Oracle System Change Numbers (`AS OF SCN`) without requiring source table downtime or exclusive DDL locks.
- Supports Full Table Offload (`100:0`), Incremental Partition Offload (`IPA` across Range, List, and List-as-Range `90:10`), and Predicate-Based Offload (`PBO`).
- Uses a declarative `AdapterRegistry` (`src/goe/offload/registry.py`), canonical `ColumnSpec` typing (`src/goe/offload/schema/column_spec.py`), and `DialectSqlEngine` (`src/goe/offload/sql_ast/dialect_engine.py`) for deterministic cross-dialect SQL generation.[^adapter-registry]
- Ships a pre-flight connectivity runner (`ConnectRunner` in `src/goe/connect/runner.py`), an asynchronous Litestar REST and MCP `2026-07-28` Listener service (`src/goe/listener/app.py`) served by Vertebra with an Oracle-backed durable job queue (`OracleJobStore`) and bounded `ListenerCache`, and opt-in OpenTelemetry observability (`src/goe/observability/`).[^listener-app]
<!-- truth: end -->

## Core Capabilities

### Data Offloading Modes
- **Full Offload (`100:0`)**: Migrates complete relational tables into target cloud data warehouses with synthetic or native partitioning, clustering, and column compression.[^offload-pipeline]
- **Incremental Partition Offload (`IPA`, `90:10`)**: Incrementally offloads historical partitions by high-water mark (`--offload-predicate-type`), age thresholds (`--older-than-days`, `--older-than-date`), or explicit partition names while retaining active partitions online.
- **Predicate-Based Offload (`PBO`)**: Offloads arbitrary relational slices using recursive-descent parsed `PredicateIR` AST expressions (`src/goe/offload/predicates/parser.py`) compiled into dialect-native SQL predicates (`src/goe/offload/predicates/compiler.py`).

### Distributed & Local Data Transport Engines
- **DuckDB 2.0 Streaming Transport (`DUCKDB`)**: Streams Oracle snapshots (`AS OF SCN`) through the signed community `oracle` extension (`cofin/duckdb-oracle`) and built-in `httpfs` secrets (`gs://`, `s3://`, `abfss://`) directly into compressed ZSTD Parquet staging files without a JVM.
- **Arrow Parquet Query Import (`QUERY_IMPORT`)**: Extracts small tables (`<= 5 GiB` under `AUTO`) via `OracleArrowBatchExtractor` and `ArrowParquetStagingWriter` (`src/goe/offload/transport/arrow_extractor.py`) into Parquet files uploaded via `StagingStorageService`.
- **Spark & Dataproc (`SPARK_SUBMIT`, `SPARK_THRIFT`, `SPARK_LIVY`, `DATAPROC`, `DATAPROC_GCLOUD`)**: Executes parallel JDBC extraction using `ORA_HASH`/`CHECKSUM`, `ID_RANGE`, `SPLIT_BY_EXTENT` ROWID ranges, and native partition/subpartition slicing for multi-hundred-gigabyte workloads.
- **Direct Target-Typed Cloud Warehouse Loads**: Loads staged Parquet directly into BigQuery via `BigQueryLoadJobIngestStrategy` (`load_table_from_uri` with `DecimalTargetType.NUMERIC`/`BIGNUMERIC`) or `EXTERNAL` table fallback (`src/goe/offload/bigquery/ingest_strategy.py`).

### Continuous Verification, Schema Evolution & Observability
- **Cross-Database Validation (`CrossDbValidator`)**: Compares source and target row counts, partition boundaries, and concurrent column aggregates (`MIN`, `MAX`, `SUM`, `AVG`, `STDDEV`) in `src/goe/validate/validator.py`.
- **Schema Synchronization (`SchemaSyncService`)**: Detects upstream relational column additions and type expansions and applies target DDL in `src/goe/sync/differ.py`.
- **End-to-End OpenTelemetry (`src/goe/observability/`)**: Propagates `ExecutionId` and W3C `traceparent` across CLI commands, orchestration stages, `OracleDatabaseRegistry` (`V$SESSION.CLIENT_INFO` + SQLCommenter), transport workers, cloud storage, BigQuery load jobs, and Listener REST/MCP endpoints.

[^offload-pipeline]: `src/goe/orchestration/pipeline.py::OffloadPipeline` — Staged offload discovery, boundary computation, plan resolution, and execution pipeline.
[^adapter-registry]: `src/goe/offload/registry.py::AdapterRegistry` — Lazy adapter registry mapping `(db_type, target)` keys to frontend, backend, and storage implementations.
[^listener-app]: `src/goe/listener/app.py::create_app` — Litestar ASGI application factory wiring REST controllers, `LitestarMCP`, `OracleJobStore`, and `ListenerCache`.
