---
type: concept
title: Staging Serialization & Encoders
description: Zero-Python-row ArrowParquetStagingWriter, OracleArrowBatchExtractor, StagingFileSpec, and Parquet/Avro staging adapters.
status: stable
tags:
  - transport
  - serialization
  - arrow
  - parquet
  - pyarrow
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: arrow-writers
    resource: src/goe/offload/staging/arrow_writers.py::ArrowParquetStagingWriter
    title: Columnar PyArrow Parquet Staging Writer
  - id: arrow-extractor
    resource: src/goe/offload/transport/arrow_extractor.py::OracleArrowBatchExtractor
    title: Oracle PyArrow RecordBatch Extractor
  - id: staging-file
    resource: src/goe/offload/staging/staging_file.py::StagingFileSpec
    title: Canonical Staging File Specification
---

# Staging Serialization & Encoders

<!-- truth: start -->
- `OracleArrowBatchExtractor` (`src/goe/offload/transport/arrow_extractor.py`) and `ArrowParquetStagingWriter` (`src/goe/offload/staging/arrow_writers.py`) stream Oracle result batches into Parquet files (`row_group_size = 122_880`) with schema, row-count, and cell-value parity against `OffloadTransportDuckDB`.[^arrow-writers][^arrow-extractor]
- `StagingFileSpec` (`src/goe/offload/staging/staging_file.py`) and `OffloadStagingParquetFile` (`src/goe/offload/staging/parquet/parquet_staging_file.py`) define the staging file metadata and column cast contracts.[^staging-file]
- High-precision Oracle `NUMBER(p, s)` values map to `pa.decimal128(p, s)` and timestamps map to `pa.timestamp("us")` with explicit UTC normalization.
<!-- truth: end -->

## Staging Engines

### Zero-Python-Row Arrow Parquet Pipeline (`src/goe/offload/staging/arrow_writers.py` & `src/goe/offload/transport/arrow_extractor.py`)
- **`canonical_columns_to_arrow_schema(columns, binary_in_base64=False)`**: Deterministically maps GOE `ColumnSpec` metadata to an explicit `pyarrow.Schema` (`pa.decimal128(p, s)`, `pa.int64()`, `pa.float64()`, `pa.string()`, `pa.binary()`, `pa.date32()`, `pa.timestamp("us", tz=...)`).[^arrow-writers]
- **`OracleArrowBatchExtractor` (`src/goe/offload/transport/arrow_extractor.py`)**: Streams Arrow record batches from `sqlspec.adapters.oracledb` (`fetch_df_batches`), falling back to columnar `pa.RecordBatch.from_pydict` batch construction when a test double or cursor does not expose native Arrow batches, and normalizes column types and Base64 binary encoding in vectorized Arrow compute passes.[^arrow-extractor]
- **`ArrowParquetStagingWriter` (`src/goe/offload/staging/arrow_writers.py`)**: Streams `pa.RecordBatch` chunks directly into `pyarrow.parquet.ParquetWriter(..., compression="SNAPPY", use_dictionary=True, write_statistics=True)` with bounded row-group buffering (`row_group_size = 122_880`) and returns `(rows_written, bytes_written)`.
- **`extract_oracle_to_parquet()`**: End-to-end helper combining `OracleArrowBatchExtractor` and `ArrowParquetStagingWriter` used by `OffloadTransportQueryImport` (`src/goe/offload/transport/query_import.py`).

### Staging File Specs (`src/goe/offload/staging/`)
- **`StagingFileSpec` (`src/goe/offload/staging/staging_file.py`)**: Immutable `FrozenBaseStruct` staging specification replacing the legacy `staging_file_factory.py`.[^staging-file]
- **`OffloadStagingParquetFile` (`src/goe/offload/staging/parquet/parquet_staging_file.py`) & `OffloadStagingAvroFile` (`src/goe/offload/staging/avro/avro_staging_file.py`)**: Provide staging schema formatting and compatibility for Parquet (default on GCP, Snowflake, Synapse) and Avro (Hadoop/Impala).

## Special Type Handling

- **Base64 Binary Encoding**: Binary columns (`RAW`, `BLOB`, `VARBINARY`) are converted to Base64 strings when `transport_binary_data_in_base64()` is active.
- **High-Precision Decimal & Timestamp Preservation**: High-precision Oracle `NUMBER(p, s)` values map to `pa.decimal128(p, s)` (or string representation when unconstrained), and timestamps map to `pa.timestamp("us")` with explicit UTC/time-zone handling so `QueryImport` and `DuckDB` produce identical Parquet physical schemas.

[^arrow-writers]: `src/goe/offload/staging/arrow_writers.py::ArrowParquetStagingWriter` — Columnar PyArrow Parquet staging writer and schema builder.
[^arrow-extractor]: `src/goe/offload/transport/arrow_extractor.py::OracleArrowBatchExtractor` — Streaming Oracle-to-PyArrow RecordBatch extractor.
[^staging-file]: `src/goe/offload/staging/staging_file.py::StagingFileSpec` — Immutable staging file specification.
