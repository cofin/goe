---
type: Reference
title: Staging Serialization & Encoders
description: Zero-Python-row ArrowParquetStagingWriter, OracleArrowBatchExtractor, Parquet encoders, and retired Avro staging replaced by fastavro test helpers
tags:
  - reference
  - transport
  - serialization
  - arrow
  - parquet
  - pyarrow
updated_at: "2026-10-26T18:05:00Z"
---

# Staging Serialization & Encoders

GOE implements high-throughput columnar Parquet staging writers in `src/goe/offload/staging/parquet/` to serialize RDBMS extractions into cloud-optimized Snappy-compressed Parquet files.

## Staging Engines

### 1. Zero-Python-Row Arrow Parquet Pipeline (`src/goe/offload/staging/parquet/arrow_writer.py`)
- **`canonical_columns_to_arrow_schema(columns, binary_in_base64=False)`**: Deterministically maps GOE `CanonicalColumn` metadata to an explicit `pyarrow.Schema` (`pa.decimal128(38, s)`, `pa.int64()`, `pa.float64()`, `pa.string()`, `pa.binary()`, `pa.date32()`, `pa.timestamp("us", tz=...)`).
- **`OracleArrowBatchExtractor`**: Streams Arrow record batches from `sqlspec.adapters.oracledb` (`fetch_df_batches` / `connection.fetch_df_batches(statement, binds, size=batch_size)`), falling back to columnar `pa.RecordBatch.from_pydict` batch construction only when the underlying driver mock or cursor does not expose native Arrow/DataFrame batches, and normalizes column types and Base64 binary encoding in vectorized Arrow compute passes.
- **`ArrowParquetStagingWriter`**: Streams `pa.RecordBatch` chunks directly into `pyarrow.parquet.ParquetWriter(..., compression="SNAPPY", use_dictionary=True, write_statistics=True)` with bounded row-group buffering (`row_group_size = 122_880`) and returns `(rows_written, bytes_written)`.
- **`extract_oracle_to_parquet()`**: End-to-end helper combining `OracleArrowBatchExtractor` and `ArrowParquetStagingWriter` used by `OffloadTransportQueryImport` to achieve schema, row-count, and cell-value parity with `OffloadTransportDuckDB`.

### 2. Legacy Staging File Wrapper (`OffloadStagingParquetFile`, `ParquetEncoder`)
- Retains compatibility for `OffloadStagingFileInterface` consumers in `src/goe/offload/staging/parquet/parquet_staging_file.py` and `parquet_column.py`.
- The legacy `src/goe/offload/staging/avro/` package (`avro_staging_file.py`, `avro_column.py`) has been retired; Avro container inspection in unit test assertions uses `fastavro` in `tests/unit/test_framework/avro_Check.py`.

## Special Type Handling

- **Base64 Binary Encoding**: Binary columns (`RAW`, `BLOB`, `VARBINARY`) are converted to Base64 strings when `transport_binary_data_in_base64()` is active.
- **High-Precision Decimal & Timestamp Preservation**: High-precision Oracle `NUMBER(p, s)` values map to `pa.decimal128(p, s)` (or string representation when unconstrained), and timestamps map to `pa.timestamp("us")` with explicit UTC/time-zone handling so `QueryImport` and `DuckDB` produce identical Parquet physical schemas.
