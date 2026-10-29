---
type: Spec
flow_id: duckdb2_engine_hardening_20261024
title: "Chapter 8.1: DuckDB 2.0 Engine Hardening, Community Oracle Extension, and Multi-File Parquet Sink"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T16:45:00Z
description: "Hardens the GOE DuckDB 2.0 transport engine over SQLSpec DuckDBConfig with CgroupQuota memory clamping, signed community oracle v0.3.1 pushdown, core httpfs cloud secrets, and parallel multi-file Parquet staging."
tags:
  - feature
  - duckdb
  - transport
  - parquet
  - oracle
parent_prd: prd_08_duckdb2_transport_query_import_parity_and_storage_20261024
depends_on:
  - prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024
  - prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024
research:
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/duckdb2-arrow-and-storage-dataplane.md
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/module-by-module-redesign.md
---

# Chapter 8.1: DuckDB 2.0 Engine Hardening, Community Oracle Extension, and Multi-File Parquet Sink

## Specification

### 1. Overview and Goals

This chapter replaces the broken DuckDB `1.5.5` transport prototype with a hardened DuckDB 2.0 data plane built on `sqlspec.adapters.duckdb.DuckDBConfig`:

1. **DuckDB 2.0 Version Gate and Shared Session Engine (`src/goe/offload/transport/duckdb/engine.py`)**: Replaces the exact `1.5.5` version check with `Version(duckdb.__version__) >= Version("2.0.0")`, wraps `sqlspec.adapters.duckdb.DuckDBConfig` inside `DuckDBEngine` configured by `DuckDBSessionConfig(FrozenBaseStruct)`, clamps `memory_limit` to 75% of container cgroup memory via `CgroupQuota`, configures `temp_directory`, `max_temp_directory_size = '90%'`, `threads`, and `preserve_insertion_order = false`, replaces `northpolesec/duckdb-gcs` (`gcss://`) with core `LOAD parquet; LOAD httpfs;` and `CREATE OR REPLACE TEMPORARY SECRET` for GCS (`TYPE gcs, BEARER_TOKEN`), S3 (`TYPE s3`), and Azure (`TYPE azure`), and loads the signed `oracle` v0.3.1 community extension (`INSTALL oracle FROM community; LOAD oracle;`) with air-gapped `extension_directory` pre-load support and `allow_unsigned_extensions=False` by default.
2. **Oracle Pushdown Transport and Type Fallback Router (`src/goe/offload/transport/duckdb/oracle_pushdown.py`)**: Implements `OracleExtensionTransport` executing `SELECT oracle_clear_cache();` before each extraction, pushing `AS OF SCN` and `ROWID`, `ORA_HASH`, `PARTITION`, `SUBPARTITION`, or `ID_RANGE` split queries down through `oracle_query`, setting `oracle_call_timeout_ms = 0`, `oracle_array_size = 10000`, and `oracle_connection_limit`, supporting Oracle Wallet and TNS aliases, and automatically routing tables containing `INTERVAL`, `TIMESTAMP WITH TIME ZONE`, `TIMESTAMP WITH LOCAL TIME ZONE`, `BFILE`, `XMLTYPE`, spatial/object types, >64 KiB LOB/JSON/VECTOR columns, or >18-digit `NUMBER` columns to `OracleArrowStreamExtractor`.
3. **Parallel Multi-File Parquet Writer (`src/goe/offload/transport/duckdb/parquet_writer.py`)**: Streams query or Arrow relation results through `COPY (...) TO '<uri>' (FORMAT PARQUET, COMPRESSION SNAPPY/ZSTD, FILE_SIZE_BYTES ..., PER_THREAD_OUTPUT true, RETURN_FILES true)`, verifies staged Parquet footers via `parquet_file_metadata`, and returns an immutable `StagedFileManifest(FrozenBaseStruct)`.

### 2. Code Analysis Summary

- `src/goe/offload/transport/duckdb_constants.py:1-10`: Hardcodes `SUPPORTED_DUCKDB_VERSION_PREFIX = "1.5.5"`, blocking execution on `.venv` where `duckdb==2.0.0` is installed (`pyproject.toml:26`).
- `src/goe/config/orchestration_defaults.py:782-797`: Defaults `OFFLOAD_TRANSPORT_DUCKDB_VERSION` to `"1.5.5"`, `OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES` to `20G`, and `OFFLOAD_TRANSPORT_DUCKDB_EXTENSION_REPOSITORY` to `https://cofin.github.io/duckdb-oracle`.
- `src/goe/offload/transport/duckdb_availability.py:32-79`: Rejects `duckdb.__version__ != config.offload_transport_duckdb_version`, rejects Oracle Wallet (`lines 65-66`), rejects TNS aliases (`lines 67-68`), and rejects `ORACLE_TYPE_RAW` (`line 39`).
- `src/goe/offload/transport/duckdb_engine.py:44-167`: Sets `allow_unsigned_extensions="true"` (`line 89`), rewrites `gs://` to `gcss://` via `to_duckdb_gcs_uri()` (`lines 75-80`), loads unported `INSTALL gcs FROM community` (`lines 112-120`), and uses `TYPE gcp, PROVIDER access_token` (`lines 133-139`) instead of core `httpfs` `TYPE gcs, BEARER_TOKEN`.
- `src/goe/offload/transport/duckdb_transport.py:163-222`: Opens a separate `:memory:` DuckDB instance per worker thread in `_run_batch` (`line 175`), multiplying `memory_limit` by `parallelism` (`N * memory_limit` container OOM defect), and mutates `os.environ["ORA_SDTZ"] = "UTC"` from worker threads (`line 209`).
- `.venv/lib/python3.14/site-packages/sqlspec/adapters/duckdb/config.py:265-310`: Provides `DuckDBConfig`, `DuckDBPoolParams`, and `DuckDBExtensionConfig` for managing DuckDB connections, extensions, and session pragmas.

### 3. Requirements

- **R1 (DuckDB 2.0 Gate and SQLSpec Engine)**: `DuckDBSessionConfig(FrozenBaseStruct)` and `DuckDBEngine` in `src/goe/offload/transport/duckdb/engine.py` must enforce `Version(duckdb.__version__) >= Version("2.0.0")`, configure a shared `:memory:goe_<execution_key>` instance over `sqlspec.adapters.duckdb.DuckDBConfig` with `CgroupQuota`-clamped `memory_limit` (75% of container limit), `temp_directory`, `max_temp_directory_size = '90%'`, `threads`, `preserve_insertion_order = false`, `LOAD parquet; LOAD httpfs;`, and `SET parquet_metadata_cache = true;` (issued after `LOAD parquet`).
- **R2 (Signed Community Oracle Extension and Cloud Storage Secrets)**: `DuckDBEngine` must keep `allow_unsigned_extensions = False` unless an explicit local `extension_path` override is configured, attempt `LOAD oracle;` first for air-gapped `extension_directory` deployments before falling back to `INSTALL oracle FROM community; LOAD oracle;`, and manage `CREATE OR REPLACE TEMPORARY SECRET` for GCS (`TYPE gcs, BEARER_TOKEN`), S3 (`TYPE s3, KEY_ID, SECRET, SESSION_TOKEN, REGION`), and Azure (`TYPE azure, CONNECTION_STRING` or `ACCOUNT_NAME`) over canonical `gs://`, `s3://`, and `az://`/`abfss://` URIs without `to_duckdb_gcs_uri()`.
- **R3 (Oracle Extension Pushdown and Cache Reset)**: `OracleExtensionTransport` in `src/goe/offload/transport/duckdb/oracle_pushdown.py` must configure `SET oracle_call_timeout_ms = 0;`, `SET oracle_array_size = 10000;`, and `SET oracle_connection_limit = <parallelism + 2>;`, execute `SELECT oracle_clear_cache();` prior to each extraction run, support EZConnect, TNS alias (`SERVICE` + `WALLET_PATH` / `TNS_ADMIN`), and SEPS Wallet (`/@alias`), verify the `AS OF SCN` invariant across `ROWID`, `ORA_HASH`, `PARTITION`, `SUBPARTITION`, and `ID_RANGE` split queries, and route tables with `INTERVAL`, `TIMESTAMP WITH TIME ZONE`, `TIMESTAMP WITH LOCAL TIME ZONE`, `BFILE`, `XMLTYPE`, spatial/object types, >64 KiB LOB/JSON/VECTOR columns, or >18-digit `NUMBER` columns to `OracleArrowStreamExtractor`.
- **R4 (Multi-File Parquet Writer and Staged Manifest)**: `DuckDBParquetWriter` in `src/goe/offload/transport/duckdb/parquet_writer.py` must execute `COPY (...) TO '<uri>' (FORMAT PARQUET, COMPRESSION <SNAPPY|ZSTD|UNCOMPRESSED>, FILE_SIZE_BYTES <bytes>, PER_THREAD_OUTPUT true, RETURN_FILES true)`, verify footer row counts via `parquet_file_metadata`, and return `StagedFileManifest(FrozenBaseStruct)` containing file URIs, total rows, and total staged bytes.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1, R2 | `1.1` | `uv run pytest tests/unit/offload/transport/test_duckdb_engine.py tests/unit/offload/transport/test_duckdb_availability.py -v` |
| R3 | `1.2` | `uv run pytest tests/unit/offload/transport/test_oracle_pushdown.py -v` |
| R4 | `1.3` | `uv run pytest tests/unit/offload/transport/test_parquet_writer.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/transport/test_duckdb_engine.py tests/unit/offload/transport/test_duckdb_availability.py tests/unit/offload/transport/test_oracle_pushdown.py tests/unit/offload/transport/test_parquet_writer.py -v
uv run ruff format --check src/goe/offload/transport src/goe/config/orchestration_defaults.py tests/unit/offload/transport
uv run ruff check src/goe/offload/transport src/goe/config/orchestration_defaults.py tests/unit/offload/transport
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: DuckDB 2.0 Engine, Oracle Pushdown, and Parquet Sink
- [ ] 1.1 Implement `DuckDBSessionConfig` and `DuckDBEngine` over `sqlspec.adapters.duckdb.DuckDBConfig` with core `httpfs` secrets and signed community `oracle` loading ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement `OracleExtensionTransport` with `oracle_clear_cache()`, `AS OF SCN` split pushdown, and type-based fallback routing to `OracleArrowStreamExtractor` ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Implement `DuckDBParquetWriter` multi-file `COPY ... TO (FORMAT PARQUET, PER_THREAD_OUTPUT true, RETURN_FILES true)` and `StagedFileManifest` verification ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `duckdb2_engine_hardening_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: Use one shared `:memory:goe_<execution_key>` DuckDB 2.0 connection per offload via `DuckDBConfig` with per-worker `cursor()` handles; load `parquet` and `httpfs` from core DuckDB 2.0 prior to setting `parquet_metadata_cache = true`; install `oracle` v0.3.1 from `community` with `allow_unsigned_extensions=False`; execute `oracle_clear_cache()` before each extraction and fall back to `OracleArrowStreamExtractor` for types outside `duckdb-oracle` native fidelity.
- **Discoveries**: none yet.
- **Blockers**: `prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024` and `prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`duckdb2_engine_hardening_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/transport/duckdb.md`, `.agents/bundles/knowledge/transport/staging-serialization.md`.
