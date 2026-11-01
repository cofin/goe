---
type: decision
title: "ADR-002: DuckDB 2.0 Data Plane, Arrow Parquet Extraction & Direct BigQuery Loads"
description: Standardize local data transport on DuckDB 2.0 (oracle + httpfs) and PyArrow Parquet staging with direct target-typed BigQuery load jobs.
status: stable
tags:
  - decision
  - adr
  - duckdb
  - pyarrow
  - bigquery
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: duckdb-engine
    resource: src/goe/offload/transport/duckdb/engine.py::DuckDBEngine
    title: DuckDB 2.0 Session and Cloud Secret Engine
  - id: arrow-extractor
    resource: src/goe/offload/transport/arrow_extractor.py::extract_oracle_to_parquet
    title: Oracle PyArrow Batch Extractor to Parquet
  - id: bq-ingest
    resource: src/goe/offload/bigquery/ingest_strategy.py::BigQueryLoadJobIngestStrategy
    title: Direct BigQuery Load Job Ingest Strategy
---

# ADR-002: DuckDB 2.0 Data Plane, Arrow Parquet Extraction & Direct BigQuery Loads

<!-- truth: start -->
- **Status**: Accepted (`stable`).
- **Decision**: Use `duckdb>=2.0.0` (`DuckDBEngine` with signed community `oracle` extension + built-in `httpfs` `TEMPORARY SECRET` over `gs://`/`s3://`/`abfss://`) for medium tables (`5 GiB < size <= 100 GiB`), PyArrow Parquet streaming (`extract_oracle_to_parquet`) for `QUERY_IMPORT` (`<= 5 GiB`), and `BigQueryLoadJobIngestStrategy` (`load_table_from_uri` with `DecimalTargetType.NUMERIC`/`BIGNUMERIC`) as the default BigQuery ingestion path.[^duckdb-engine][^arrow-extractor][^bq-ingest]
<!-- truth: end -->

## Context

Previously, GOE staged Avro or string-typed Parquet files, created an external staging table in BigQuery, ran validation `SELECT` queries against the external table, and executed an `INSERT ... SELECT CAST/PARSE_*` query—incurring 6 BigQuery jobs and full SQL scan byte charges on every offload. Meanwhile, DuckDB 1.5 required a third-party `gcss://` extension and lacked native `httpfs` GCS secret integration.

## Alternatives Considered

| Option | Summary | Why Rejected / Selected |
| :--- | :--- | :--- |
| **Selected: DuckDB 2.0 + PyArrow Parquet + Direct BigQuery `load_table_from_uri`** | Stream target-typed ZSTD Parquet via DuckDB 2.0 (`httpfs` secrets) or PyArrow, and load directly into BigQuery via free batch `load_table_from_uri` jobs (`NATIVE` default, `EXTERNAL` opt-in fallback). | **Selected**: Reduces BigQuery ingestion from 6 jobs to 1 job with zero SQL scan bytes billed, eliminates JVM startup for `<= 100 GiB` tables, and guarantees schema/value parity between `QUERY_IMPORT` and `DUCKDB`. |
| **Retain External Table + `INSERT ... SELECT` as Default** | Always stage stringified columns and cast inside BigQuery SQL. | **Rejected**: Incurs unnecessary BigQuery query scan charges and extra DDL round-trips on every offload. |
| **Retain Legacy Row-by-Row Avro `QUERY_IMPORT`** | Fetch Python tuples and serialize row-by-row via `avro`. | **Rejected**: High Python CPU/GC overhead and diverges from the Parquet schema produced by `DUCKDB` and `SPARK`. |

## Consequences

- `GCP_AUTO_TRANSPORT_METHODS` selects `QUERY_IMPORT` (`<= 5 GiB`), `DUCKDB` (`5 GiB < size <= 100 GiB`), and Spark (`> 100 GiB`) automatically based on estimated source bytes.
- `DuckDBEngine` clamps `memory_limit` to 75% of `CgroupQuota.detect()` and configures `CREATE OR REPLACE TEMPORARY SECRET` for Oracle and cloud storage (`gs://`, `s3://`, `abfss://`).[^duckdb-engine]
- `BigQueryLoadJobIngestStrategy` loads staged Parquet directly with `DecimalTargetType.NUMERIC` and `DecimalTargetType.BIGNUMERIC`, while `BigQueryExternalTableIngestStrategy` remains available when `--bigquery-load-table-mode=EXTERNAL` or synthetic partition expressions require SQL projection.[^bq-ingest]

[^duckdb-engine]: `src/goe/offload/transport/duckdb/engine.py::DuckDBEngine` — DuckDB 2.0 session, cgroup memory clamping, and `TEMPORARY SECRET` configuration.
[^arrow-extractor]: `src/goe/offload/transport/arrow_extractor.py::extract_oracle_to_parquet` — Streaming Oracle-to-PyArrow Parquet batch extractor.
[^bq-ingest]: `src/goe/offload/bigquery/ingest_strategy.py::BigQueryLoadJobIngestStrategy` — Direct `load_table_from_uri` BigQuery Parquet ingestion strategy.
