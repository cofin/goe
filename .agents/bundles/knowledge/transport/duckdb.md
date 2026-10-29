---
type: Reference
title: DuckDB & duckdb-oracle Offload Transport
description: Zero-JVM DuckDB 2.0 transport engine using sqlspec DuckDBConfig, cgroup resource bounding, cofin/duckdb-oracle, and community gcs extension for Oracle-to-BigQuery Parquet offloads
tags:
  - reference
  - transport
  - duckdb
  - oracle
  - gcs
  - parquet
  - opentelemetry
updated_at: "2026-10-26T18:05:00Z"
---

# DuckDB & `duckdb-oracle` Offload Transport

`OffloadTransportDuckDB` (`src/goe/offload/transport/duckdb_transport.py` and `src/goe/offload/transport/duckdb/`) is a zero-JVM local offload transport engine (`--offload-transport-method=DUCKDB` / `OFFLOAD_TRANSPORT=DUCKDB`, and included in `GCP_AUTO_TRANSPORT_METHODS` for tables `5 GiB < estimated_bytes <= 100 GiB`) that streams Oracle rows directly to Google Cloud Storage (`gcss://`) or local Parquet files as Snappy-compressed Parquet files using `duckdb==1.5.5`, `sqlspec.adapters.duckdb.DuckDBConfig`, `cofin/duckdb-oracle` (`oracle_execute`), and the DuckDB community `gcs` extension (`northpolesec/duckdb-gcs`).

## Key Modules (`src/goe/offload/transport/duckdb/`)

- **`engine.py` (`src/goe/offload/transport/duckdb/engine.py`)**:
  - `CgroupQuota(FrozenBaseStruct)` and `read_cgroup_quota()`: Reads Linux cgroup v2 (`/sys/fs/cgroup/memory.max`, `/sys/fs/cgroup/cpu.max`) and cgroup v1 (`/sys/fs/cgroup/memory/memory.limit_in_bytes`, `/sys/fs/cgroup/cpu/cpu.cfs_quota_us` + `cpu.cfs_period_us`) limits and host physical RAM.
  - `DuckDBSessionConfig(FrozenBaseStruct)` and `build_session_config()`: Clamps `memory_limit_bytes` to 75% of effective cgroup/host RAM (warning when the operator's requested `--duckdb-memory-limit` exceeds the 75% ceiling) and `threads` to effective cgroup CPU cores (`min(requested, cgroup_cores, 8)`), setting `database=":memory:goe_<execution_key>"`, `preserve_insertion_order=False`, `parquet_metadata_cache=True`, and `temp_directory`.
  - `DuckDBEngine`: Wraps `sqlspec.adapters.duckdb.DuckDBConfig` and manages per-session `CREATE OR REPLACE TEMPORARY SECRET` registration for Oracle (`TYPE oracle`) and GCS (`TYPE gcs`, `credential_chain` or `access_token` with 600s token refresh margin via `refresh_gcs_secret_if_expiring()`).
- **`oracle_scan.py` (`src/goe/offload/transport/duckdb/oracle_scan.py`)**:
  - `attach_oracle()`: Builds EZConnect DSN (`host:port/service_name`) via `parse_oracle_dsn()`, issues `CREATE OR REPLACE TEMPORARY SECRET ... (TYPE oracle, ...)` and `ATTACH '<dsn>' AS goe_ora (TYPE ORACLE, SECRET ..., READ_ONLY)`, and attempts `CALL oracle_clear_cache()` and `SET oracle_enable_pushdown = true`.
  - `verify_batch_scn_invariant(query, scn)`: Enforces that `AS OF SCN <scn>` is present in the extraction SQL before any DuckDB connection opens.
  - `build_oracle_scan_sql()`: Wraps the Oracle extraction query in `oracle_query('goe_ora', '...')` or `FROM goe_ora.<owner>.<table>` with predicate pushdown.
- **`parquet_writer.py` (`src/goe/offload/transport/duckdb/parquet_writer.py`)**:
  - `build_cast_projection()`: Generates target-typed SQL `CAST` expressions (`DECIMAL(38, s)`, `BIGINT`, `DOUBLE`, `VARCHAR`, `BLOB`, `DATE`, `TIMESTAMP`, plus synthetic partition expressions `GOE_PART_*`) from `CanonicalColumn` metadata.
  - `copy_to_parquet()`: Executes `COPY (<projected_sql>) TO '<staging_uri>' (FORMAT PARQUET, COMPRESSION SNAPPY, ROW_GROUP_SIZE 122880)` and verifies output row counts via `parquet_metadata()`.
- **`duckdb_constants.py` & `duckdb_availability.py`**:
  - `is_duckdb_available()` checks `BACKEND_DISTRO_GCP`, `DBTYPE_ORACLE`, `FILE_STORAGE_FORMAT_PARQUET`, `OFFLOAD_FS_SCHEME_GS`, `not use_oracle_wallet`, `duckdb.__version__` prefix `"1.5.5"`, `max_offload_chunk_size <= offload_transport_duckdb_max_bytes` (`100 GiB` default), and unsigned extension opt-in before attempting any network or database connection.
- **`duckdb_transport.py` (`src/goe/offload/transport/duckdb_transport.py`)**:
  - `OffloadTransportDuckDB` subclassing `OffloadTransportRdbms` to execute single or parallel (`ThreadPoolExecutor`) batch extractions into `gcss://` Parquet files via `DuckDBEngine`, `attach_oracle`, and `copy_to_parquet`.

## Safety Gates & Selection Rules

1. **Cost-Based `AUTO` Selection & Explicit Mode**: `TransportSelector` (`src/goe/offload/transport/selector.py`) selects `QUERY_IMPORT` for `<= 5 GiB`, `DUCKDB` for `5 GiB < estimated_bytes <= 100 GiB` when `is_duckdb_available()` is true, and Spark transports (`SPARK_BATCHES_GCLOUD`, `SPARK_DATAPROC_GCLOUD`, `SPARK_THRIFT`, `SPARK_SUBMIT`, `SPARK_LIVY`) above `100 GiB` or when `DUCKDB` is unavailable.
2. **Version Pin & Runtime Check**: `cofin/duckdb-oracle` v0.2.2 targets `duckdb==1.5.5`. Both `uv.lock` and `duckdb.__version__.startswith("1.5.5")` enforce this version.
3. **Unsigned Extension Policy**:
   - When `OFFLOAD_TRANSPORT_DUCKDB_ORACLE_EXTENSION_PATH` points to an existing local `.duckdb_extension` binary, DuckDB loads it directly.
   - When installing `oracle` from `OFFLOAD_TRANSPORT_DUCKDB_ORACLE_REPOSITORY` without a local binary path, `OFFLOAD_TRANSPORT_DUCKDB_ALLOW_UNSIGNED_EXTENSIONS=true` is required.
4. **Cgroup & Memory Ceiling Guard**: `DuckDBSessionConfig` automatically clamps DuckDB's `memory_limit` to 75% of the active container cgroup v1/v2 memory limit (or host physical RAM) and disables insertion order preservation (`preserve_insertion_order=false`) to prevent OOM kills during parallel Parquet row-group compression.

## Snapshot Invariant & Per-Batch Telemetry

- **Mandatory `AS OF SCN` Verification (`verify_batch_scn_invariant`)**: Because each parallel worker thread opens an independent Oracle session via `ATTACH '<dsn>' AS goe_ora`, `OffloadTransportDuckDB._run_batch()` calls `verify_batch_scn_invariant(query, self._scn)` *before* opening a DuckDB connection, raising `OffloadTransportException` if `AS OF SCN <scn>` is absent from the batch SQL.
- **Parallel Execution & OpenTelemetry Spans**:
  - Single-batch runs execute inline; multi-batch runs (`degree_of_parallelism > 1`) dispatch `_run_batch` across `ThreadPoolExecutor(max_workers=self._dop)` via `submit_with_context()` (`src/goe/observability/context.py`) so the active OpenTelemetry span context, W3C baggage, and SQLSpec `CorrelationContext` propagate to every worker thread.
  - Each `_run_batch` is wrapped in `traced_duckdb_batch(batch_index=..., staging_uri=..., scn=...)` (`src/goe/observability/transport.py`), emitting a `SpanKind.CLIENT` span `goe.transport.duckdb.batch` with `db.system="oracle"`, `goe.transport.batch_index`, `goe.transport.staging_uri`, `goe.transport.scn`, and `goe.transport.rows`.
