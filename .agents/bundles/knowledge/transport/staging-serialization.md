---
type: Reference
title: Staging Serialization & Encoders
description: Avro and Parquet encoders, PyArrow integration, 20MB buffer chunking, and Base64 binary serialization
tags:
  - reference
  - transport
  - serialization
  - avro
  - parquet
  - pyarrow
---

# Staging Serialization & Encoders

GOE implements high-throughput data encoders in `src/goe/offload/staging/` and `src/goe/util/` to serialize RDBMS rows into cloud-optimized formats.

## Staging Formats

### 1. Apache Parquet (`OffloadStagingParquetFile`, `ParquetEncoder`)
- **Library**: `pyarrow.Table`, `pyarrow.parquet.ParquetWriter`.
- **Buffer Threshold**: Buffers row batches in 20MB memory chunks before flushing columnar pages.
- **Compression**: `SNAPPY`.
- **Compatibility**: Formatted to Parquet version 1.0 for universal compatibility across BigQuery, Snowflake, and Synapse.

### 2. Apache Avro (`OffloadStagingAvroFile`, `AvroEncoder`)
- **Library**: `avro` with custom binary encoder.
- **Schema**: Dynamically generates JSON Avro schema with nullable union types (`["type", "null"]`).
- **Compression**: `deflate` (zlib) or uncompressed.

## Special Type Handling

- **Base64 Binary Encoding**: Binary columns (`RAW`, `BLOB`, `VARBINARY`) are converted to Base64 strings when `transport_binary_data_in_base64()` is active.
- **Timestamp Standardization**: Timestamps are formatted with explicit NLS masks to avoid timezone ambiguity during intermediate staging.
