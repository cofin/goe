---
type: concept
title: DuckDB 2.0 & duckdb-oracle Offload Transport
description: Zero-JVM DuckDB 2.0 transport engine using sqlspec DuckDBConfig, cgroup resource bounding, cofin/duckdb-oracle, and built-in httpfs secrets for Oracle-to-Parquet offloads.
status: stable
tags:
  - transport
  - duckdb
  - oracle
  - gcs
  - parquet
  - opentelemetry
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
  - id: oracle-pushdown
    resource: src/goe/offload/transport/duckdb/oracle_pushdown.py::attach_oracle
    title: Oracle Extension Attachment and SCN Invariant Check
  - id: parquet-writer
    resource: src/goe/offload/transport/duckdb/parquet_writer.py::copy_to_parquet
    title: DuckDB Target-Typed Parquet Copy Writer
  - id: duckdb-transport
    resource: src/goe/offload/transport/duckdb_transport.py::OffloadTransportDuckDB
    title: DuckDB Offload Transport Implementation
---

# DuckDB 2.0 & `duckdb-oracle` Offload Transport

<!-- truth: start -->
- `OffloadTransportDuckDB` (`src/goe/offload/transport/duckdb_transport.py`) targets `duckdb>=2.0.0` (`MIN_SUPPORTED_DUCKDB_VERSION = "2.0.0"` in `src/goe/offload/transport/duckdb_constants.py`), using the signed community `oracle` extension (`cofin/duckdb-oracle`) and built-in `httpfs` `TEMPORARY SECRET` over `gs://`, `s3://`, and `abfss://`.[^duckdb-engine][^duckdb-transport]
- `TransportSelector` (`src/goe/offload/transport/selector.py`) automatically selects `QUERY_IMPORT` for `<= 5 GiB`, `DUCKDB` for `5 GiB < estimated_bytes <= 100 GiB`, and Spark transports above `100 GiB`.
- `DuckDBSessionConfig` (`src/goe/offload/transport/duckdb/engine.py`) clamps `memory_limit` to 75% of effective cgroup v1/v2 or host RAM (`CgroupQuota.detect()`) and sets `preserve_insertion_order=False` and `parquet_metadata_cache=True`.[^duckdb-engine]
- `verify_batch_scn_invariant(query, scn)` (`src/goe/offload/transport/duckdb/oracle_pushdown.py`) verifies that `AS OF SCN <scn>` is present in the extraction SQL before opening any DuckDB connection.[^oracle-pushdown]
- When `cloud_secret is None` (local filesystem staging), `DuckDBEngine` skips `LOAD httpfs` unless an `httpfs`-backed URI (`gs://`, `s3://`, `abfss://`) is targeted.
<!-- truth: end -->

## Key Modules (`src/goe/offload/transport/duckdb/`)

- **`engine.py` (`src/goe/offload/transport/duckdb/engine.py`)**:
  - `DuckDBSessionConfig(FrozenBaseStruct, frozen=True)` and `build_session_config()`: Clamps `memory_limit_bytes` to 75% of `CgroupQuota.detect()` and `threads` to `min(requested, cgroup_cores, 8)`, setting `database=":memory:goe_<execution_key>"`, `preserve_insertion_order=False`, and `parquet_metadata_cache=True`.
  - `DuckDBEngine`: Wraps `sqlspec.adapters.duckdb.DuckDBConfig` and manages per-session `CREATE OR REPLACE TEMPORARY SECRET` registration for Oracle (`TYPE oracle`) and cloud storage (`CloudStorageSecretSpec` over `httpfs` for `gs://`, `s3://`, and `abfss://`, with 600s OAuth token refresh margin on GCS `BEARER_TOKEN` secrets).[^duckdb-engine]
- **`oracle_pushdown.py` (`src/goe/offload/transport/duckdb/oracle_pushdown.py`)**:
  - `attach_oracle()`: Builds EZConnect DSN (`host:port/service_name`) via `parse_oracle_dsn()`, issues `CREATE OR REPLACE TEMPORARY SECRET ... (TYPE oracle, ...)` and `ATTACH '<dsn>' AS goe_ora (TYPE ORACLE, SECRET ..., READ_ONLY)`, and configures `SET oracle_enable_pushdown = true`.
  - `verify_batch_scn_invariant(query, scn)`: Enforces that `AS OF SCN <scn>` is present in the extraction SQL before any DuckDB connection opens.
  - `build_oracle_scan_sql()`: Wraps the Oracle extraction query in `oracle_query('goe_ora', '...')`.[^oracle-pushdown]
- **`parquet_writer.py` (`src/goe/offload/transport/duckdb/parquet_writer.py`)**:
  - `build_cast_projection()`: Generates target-typed SQL `CAST` expressions (`DECIMAL(p, s)`, `BIGINT`, `DOUBLE`, `VARCHAR`, `BLOB`, `DATE`, `TIMESTAMP`, plus synthetic partition expressions `GOE_PART_*`) from `ColumnSpec` metadata.
  - `copy_to_parquet()`: Executes `COPY (<projected_sql>) TO '<staging_uri>' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)` and verifies output row counts via `parquet_metadata()`.[^parquet-writer]
- **`duckdb_constants.py` & `duckdb_availability.py`**:
  - Enforces `MIN_SUPPORTED_DUCKDB_VERSION = "2.0.0"`, `not use_oracle_wallet`, and `max_offload_chunk_size <= offload_transport_duckdb_max_bytes` (`100 GiB` default).
- **`duckdb_transport.py` (`src/goe/offload/transport/duckdb_transport.py`)**:
  - `OffloadTransportDuckDB` executes single or parallel (`ThreadPoolExecutor`) batch extractions into `gs://`/`s3://`/`abfss://`/local Parquet files via `DuckDBEngine`, `attach_oracle`, and `copy_to_parquet`, with Clientless Thin PyCapsule Arrow fallback (`extract_oracle_to_parquet`) when the native `oracle` extension is unavailable.[^duckdb-transport]

## Snapshot Invariant & Per-Batch Telemetry

- **Mandatory `AS OF SCN` Verification (`verify_batch_scn_invariant`)**: Because each parallel worker thread opens an independent Oracle session via `ATTACH '<dsn>' AS goe_ora`, `OffloadTransportDuckDB._run_batch()` calls `verify_batch_scn_invariant(query, self._scn)` before opening a DuckDB connection, raising `OffloadTransportException` if `AS OF SCN <scn>` is absent.[^oracle-pushdown]
- **Parallel Execution & OpenTelemetry Spans**:
  - Multi-batch runs (`degree_of_parallelism > 1`) dispatch `_run_batch` across `ThreadPoolExecutor(max_workers=self._dop)` via `submit_with_context()` (`src/goe/observability/context.py`) so active OpenTelemetry spans, W3C baggage, and SQLSpec `CorrelationContext` propagate to every worker thread.
  - Each `_run_batch` is wrapped in `traced_duckdb_batch()` (`src/goe/observability/transport.py`), emitting a `SpanKind.CLIENT` span `goe.transport.duckdb.batch`.

[^duckdb-engine]: `src/goe/offload/transport/duckdb/engine.py::DuckDBEngine` — DuckDB 2.0 session, cgroup memory clamping, and `TEMPORARY SECRET` configuration.
[^oracle-pushdown]: `src/goe/offload/transport/duckdb/oracle_pushdown.py::attach_oracle` — Oracle extension attachment and `AS OF SCN` invariant check.
[^parquet-writer]: `src/goe/offload/transport/duckdb/parquet_writer.py::copy_to_parquet` — Target-typed DuckDB Parquet writer and metadata verifier.
[^duckdb-transport]: `src/goe/offload/transport/duckdb_transport.py::OffloadTransportDuckDB` — DuckDB offload transport implementation.
