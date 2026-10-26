---
type: Reference
title: Data Offload, Canonical Typing & Storage Gotchas
description: Three-tier column mapping, snapshot-consistent extraction, staged ingestion, AST/predicate boundaries, and RDBMS type sampling gotchas
tags:
  - pattern
  - offload
  - type-mapping
  - storage
  - gotchas
updated_at: "2026-10-26T14:50:00Z"
---

# Data Offload, Canonical Typing & Storage Gotchas

## Core Offload Patterns

- **Table-Level Concurrency Mutex**: Every offload, schema sync, and validation operation acquires an exclusive table lock via `OrchestrationRunner` and `OrchestrationLockInterface` (`filelock` in `$OFFLOAD_HOME/run/`).
- **Snapshot-Consistent Extraction**: RDBMS extraction queries bind to a consistent read snapshot (`FLASHBACK ANY TABLE` / Oracle `SCN`) to prevent phantom reads and avoid locking OLTP tables.
- **Three-Tier Column Mapping**: All schema translations pass through `ColumnSpec` (`src/goe/offload/schema/column_spec.py`, parameterized by `ColumnDialect`) and the table-driven `CanonicalTypeRegistry` (`TYPE_REGISTRY` in `src/goe/offload/schema/type_registry.py`).
- **Composable Backend Capabilities, Catalog Cache & Ingest Strategies**: Every backend API exposes an immutable `BackendCapabilities` profile (`src/goe/offload/backend_capabilities.py`), caches table/column/partition/size metadata in `CachedBackendCatalog` (`src/goe/offload/backend_cache.py`) with write-through DDL/load invalidation and batch `warm_schema(db_name)` pre-warming, and delegates staged cast validation and final merges to `StagingLoadService` and `FinalTableMerger` (`src/goe/offload/backend_load.py`) or BigQuery's `BigQueryIngestStrategy` (`src/goe/offload/bigquery/ingest_strategy.py`).
- **Two-Phase Staged Ingestion**: Parallel extraction writes Avro or Snappy-compressed Parquet files to cloud staging storage (`gs://`, `s3a://`, `abfss://`, `hdfs://`), followed by an atomic target load (`LOAD DATA` / `COPY INTO` / `INSERT ... SELECT`) and automatic staging cleanup.
- **Strict SQL AST & Predicate IR Boundary**: All SQL DDL/DML, Oracle `PARTITION` / `SUBPARTITION` / `AS OF SCN :scn` extraction queries, batched 64-aggregate cross-DB validation queries (`src/goe/offload/validation/`), and `SchemaSyncService` `ALTER TABLE` statements (`src/goe/sync/differ.py`) are built through `DialectSqlEngine` (`src/goe/offload/sql_ast/`) and `PredicateCompiler` (`src/goe/offload/predicates/`), keeping `sqlglot` imports out of orchestration and adapter modules (`[sqlglot-boundary] files = []` in `tools/architecture_baseline.toml`).
- **Zero-Python-Row Columnar Transport & Unified Cloud Storage**: Local extractions use either `OffloadTransportDuckDB` (`src/goe/offload/transport/duckdb/` over `sqlspec.adapters.duckdb.DuckDBConfig` with cgroup v1/v2 75% memory clamping) or `OffloadTransportQueryImport` (`src/goe/offload/staging/parquet/arrow_writer.py` streaming Arrow `RecordBatch`es to Snappy Parquet with differential schema/row/value parity), and stage objects via `StagingStorageService` (`src/goe/filesystem/storage_service.py` over `sqlspec.storage` with bounded `max_results=2` directory prefix checks and 1,000-key batch deletes).

## Gotchas & Defenses

- **`sqlspec.storage.LocalStore.delete_sync` Signature**: `LocalStore.delete_sync` accepts a single relative path string per call rather than a list of keys; iterate over each key in a `DELETE_BATCH_LIMIT = 1000` chunk when deleting local staging files.
- **Ambiguous Oracle `NUMBER` / `FLOAT`**: Unscaled Oracle `NUMBER` and `FLOAT` columns must be sampled (`sample_rdbms_data_types` / `--data-sample-pct`) before target table creation so precision and scale boundaries are bounded explicitly.
- **High-Precision Decimal Truncation**: 38-digit integers and high-precision decimals (`NUMBER(38)`) risk silent float truncation if downcast; map strictly to `INTEGER_38` or backend arbitrary-precision `NUMERIC` / `BIGNUMERIC`.
- **Oracle 9-Digit Nanosecond Timestamp Formatting**: Format `numpy.datetime64` `TIMESTAMP(9)` values directly in `PredicateCompiler` (`TIMESTAMP 'YYYY-MM-DD HH:MM:SS.fffffffff'` and `TO_TIMESTAMP(:bind, 'YYYY-MM-DD HH24:MI:SS.FF9')`) without re-parsing through `sqlglot.parse_one`, which would truncate nanosecond digits.
- **Single-Line `msgspec` JSON Formatting for Golden Reports**: `msgspec.json.encode(data)` emits compact JSON without spaces after `:` and `,`, whereas `format_json(encode_json(data), indent=0)` (`goe.serializers`) produces single-line JSON with standard `": "` and `", "` separators matching `json.dumps(data)` byte-for-byte.
- **Cloud Storage Eventual Consistency**: Verify staged object visibility on object stores before issuing backend load queries.
