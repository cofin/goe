---
type: Spec
flow_id: arrow_extraction_and_query_import_parity_20261024
title: "Chapter 8.2: Clientless Arrow Extraction, Staging Writers, Differential Parity Suite, and QUERY_IMPORT Cutover"
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
description: "Implements lazy PyCapsule Arrow batch extraction from python-oracledb, DuckDB Parquet and fastavro staging writers, a differential parity suite across all 19 Oracle type families, and the QUERY_IMPORT cutover retiring legacy row-by-row encoders."
tags:
  - feature
  - arrow
  - transport
  - parquet
  - avro
parent_prd: prd_08_duckdb2_transport_query_import_parity_and_storage_20261024
depends_on:
  - duckdb2_engine_hardening_20261024
research:
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/duckdb2-arrow-and-storage-dataplane.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 8.2: Clientless Arrow Extraction, Staging Writers, Differential Parity Suite, and QUERY_IMPORT Cutover

## Specification

### 1. Overview and Goals

This chapter replaces row-by-row Python cursor fetching and transposition in `QUERY_IMPORT` (and provides the clientless/LOB fallback path for `DUCKDB` transport) with a streaming Apache Arrow data plane:

1. **Lazy PyCapsule Arrow Extractor (`src/goe/offload/transport/arrow_extractor.py`)**: Implements `OracleArrowStreamExtractor` streaming `conn.fetch_df_batches(statement=..., parameters=..., size=batch_size, fetch_decimals=True)` inside a lazy `pyarrow.RecordBatchReader.from_batches(schema, batch_generator())` (avoiding `sqlspec` `OracleSyncDriver.select_to_arrow`'s eager batch list buffering) with output-type handlers and column normalizers for high-precision `NUMBER(p, s)` (`Decimal128` / `Decimal256` / exact `TM` string), `INTERVAL YEAR TO MONTH`, `INTERVAL DAY TO SECOND`, `TIMESTAMP WITH TIME ZONE`, `TIMESTAMP WITH LOCAL TIME ZONE`, `CLOB`/`NCLOB`/`BLOB`, and nanosecond `TIMESTAMP(7..9)`.
2. **Arrow Staging Writers (`src/goe/offload/staging/arrow_writers.py`)**: Implements `ArrowParquetStagingWriter` (registering the lazy `RecordBatchReader` on a `DuckDBEngine` cursor with mandatory `cursor.unregister(view_name)` in `finally` and streaming through `DuckDBParquetWriter` `COPY ... TO (FORMAT PARQUET)`) and `ArrowAvroStagingWriter` (streaming `RecordBatchReader` batches into `fastavro.writer` with GOE's canonical Avro schema, replacing `avro` with `fastavro` in `pyproject.toml`).
3. **Differential Parity Suite and Golden Fixtures (`tests/unit/offload/transport/test_query_import_parity.py`, `tests/integration/offload/test_query_import_parity_oracle.py`)**: Captures committed golden Parquet/Avro schema and canonical row digest fixtures from the legacy `OffloadTransportQueryImport`, `ParquetEncoder`, and `AvroEncoder`, and verifies 100% schema, column name, nullability, row count, byte/value, compression, `NaN`/`Inf`, and empty-table parity across all 19 Oracle type families before the legacy encoders are removed.
4. **`QUERY_IMPORT` Cutover and Legacy Encoder Deletion (`src/goe/offload/transport/query_import.py`)**: Replaces `OffloadTransportQueryImport` with the Arrow-streaming implementation while preserving `--offload-transport-method=QUERY_IMPORT`, its configuration keys, and its staged-file contract, and deletes the legacy row-by-row `src/goe/util/parquet_encoder.py`, `src/goe/util/avro_encoder.py`, `src/goe/offload/factory/query_import_factory.py`, and `src/goe/offload/query_import_interface.py`.

### 2. Code Analysis Summary

- `src/goe/offload/transport/query_import.py:30-177`: Forces `self._offload_transport_parallelism = 1` (`line 62`), caps fetch size at `1000` / `10000` (`lines 30-37`), logs an inaccurate consistent-read message (`lines 113-117`), writes a single local file via `encoder.write_from_cursor` (`lines 163-165`), and uploads via `_query_import_copy_to_dfs` (`lines 170-176`).
- `src/goe/util/parquet_encoder.py:81-170`: Fetches Python tuple batches via `cursor.fetchmany()`, transposes rows into column lists in Python (`[[row[i] for row in rows] for i in ...]`), converts strings via `from_Timestamp`/`float`/`int`, and calls quadratic `pyarrow.concat_tables` before writing Parquet v1.0.
- `src/goe/util/avro_encoder.py:1-190`: Iterates row-by-row in pure Python using `avro.datafile.DataFileWriter` (`avro-python3`), base64-decoding binary columns per row.
- `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py:706-762`: Installs a cursor `outputtypehandler` converting numbers and dates to `str` (`lines 707-725`) inside `query_import_extraction`.
- `.venv/lib/python3.14/site-packages/sqlspec/adapters/oracledb/driver.py:1053-1085`: `OracleSyncDriver.select_to_arrow` calls `collect_oracle_arrow_batches`, materializing all batches into a Python `list` before constructing `pa.RecordBatchReader.from_batches`. GOE must wrap `conn.fetch_df_batches(...)` in a lazy generator yielding from `pa.RecordBatchReader.from_stream(ora_df)`.

### 3. Requirements

- **R1 (Lazy PyCapsule Arrow Stream Extractor)**: `OracleArrowStreamExtractor` in `src/goe/offload/transport/arrow_extractor.py` must stream `conn.fetch_df_batches(statement=..., parameters=..., size=batch_size, fetch_decimals=True)` inside a lazy `pyarrow.RecordBatchReader.from_batches(schema, batch_generator())` without buffering more than one batch in memory, and normalize high-precision `NUMBER(p, s)` (`Decimal128`), unbounded `NUMBER` (`TO_CHAR(..., 'TM')`), `INTERVAL YEAR TO MONTH`, `INTERVAL DAY TO SECOND`, `TIMESTAMP WITH TIME ZONE`, `TIMESTAMP WITH LOCAL TIME ZONE`, `CLOB`/`NCLOB`/`BLOB`, `RAW`, `BINARY_FLOAT`/`BINARY_DOUBLE` (`nan_values_as_null`), and nanosecond `TIMESTAMP(7..9)`.
- **R2 (DuckDB Parquet and `fastavro` Staging Writers)**: `ArrowParquetStagingWriter` in `src/goe/offload/staging/arrow_writers.py` must register the lazy `RecordBatchReader` on a `DuckDBEngine` cursor, stream through `DuckDBParquetWriter`, and always call `cursor.unregister(view_name)` in a `finally` block. `ArrowAvroStagingWriter` must stream `RecordBatchReader` batches into `fastavro.writer` using GOE's canonical Avro schema, loading `fastavro` via `goe.util.module_loader`.
- **R3 (Differential Parity Across All 19 Oracle Type Families)**: `tests/unit/offload/transport/test_query_import_parity.py` and `tests/integration/offload/test_query_import_parity_oracle.py` must prove 100% schema, column name, nullability, row count, canonical value/byte, compression (`SNAPPY`/`DEFLATE`/`UNCOMPRESSED`), and empty-table parity between the legacy encoders (captured in committed golden fixtures under `tests/unit/offload/transport/fixtures/query_import_parity/golden_manifest.json`) and the new Arrow writers across all 19 Oracle type families.
- **R4 (`QUERY_IMPORT` Replacement and Legacy Encoder Removal)**: `OffloadTransportQueryImport` in `src/goe/offload/transport/query_import.py` must execute via `OracleArrowStreamExtractor` + `ArrowParquetStagingWriter` / `ArrowAvroStagingWriter`, honor `--offload-transport-parallelism` and `AS OF SCN` consistent reads, and delete `src/goe/util/parquet_encoder.py`, `src/goe/util/avro_encoder.py`, `src/goe/offload/factory/query_import_factory.py`, and `src/goe/offload/query_import_interface.py`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | `1.1` | `uv run pytest tests/unit/offload/transport/test_arrow_extractor.py -v` |
| R2 | `1.2` | `uv run pytest tests/unit/offload/staging/test_arrow_writers.py -v` |
| R3 | `1.3` | `uv run pytest tests/unit/offload/transport/test_query_import_parity.py -v` |
| R4 | `1.4` | `uv run pytest tests/unit/offload/transport/test_query_import.py tests/unit/offload/transport/test_query_import_parity.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/transport/test_arrow_extractor.py tests/unit/offload/staging/test_arrow_writers.py tests/unit/offload/transport/test_query_import_parity.py tests/unit/offload/transport/test_query_import.py -v
uv run ruff format --check src/goe/offload/transport src/goe/offload/staging src/goe/offload/oracle src/goe/offload/registry.py tests/unit/offload
uv run ruff check src/goe/offload/transport src/goe/offload/staging src/goe/offload/oracle src/goe/offload/registry.py tests/unit/offload
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Arrow Stream Extractor, Staging Writers, Parity Suite, and Cutover
- [ ] 1.1 Implement `OracleArrowStreamExtractor` lazy `RecordBatchReader` over `fetch_df_batches` with output-type handlers for all Oracle types ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement `ArrowParquetStagingWriter` and `ArrowAvroStagingWriter` and replace `avro` with `fastavro` ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Build the differential parity suite and committed golden fixtures across all 19 Oracle type families ([tasks/1.3.md](tasks/1.3.md))
- [ ] 1.4 Cut `OffloadTransportQueryImport` over to the Arrow streaming pipeline and delete legacy `ParquetEncoder`, `AvroEncoder`, and `QueryImportInterface` ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `arrow_extraction_and_query_import_parity_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: Stream `oracledb` `DataFrame` objects via `pa.RecordBatchReader.from_stream(ora_df)` inside a lazy generator instead of `OracleSyncDriver.select_to_arrow`; always `cursor.unregister(view_name)` in `finally`; commit golden Parquet/Avro parity fixtures in Task 1.3 before deleting legacy encoders in Task 1.4.
- **Discoveries**: none yet.
- **Blockers**: `duckdb2_engine_hardening_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`arrow_extraction_and_query_import_parity_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/transport/duckdb.md`, `.agents/bundles/knowledge/transport/staging-serialization.md`.
