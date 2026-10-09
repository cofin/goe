---
type: Reference
title: Data Offload, Canonical Typing & Storage Gotchas
description: Three-tier column mapping, snapshot-consistent extraction, staged ingestion, and RDBMS type sampling gotchas
tags:
  - pattern
  - offload
  - type-mapping
  - storage
  - gotchas
updated_at: "2026-10-02T19:33:00Z"
---

# Data Offload, Canonical Typing & Storage Gotchas

## Core Offload Patterns

- **Table-Level Concurrency Mutex**: Every offload, schema sync, and validation operation acquires an exclusive table lock via `OrchestrationRunner` and `OrchestrationLockInterface` (`filelock` in `$OFFLOAD_HOME/run/`).
- **Snapshot-Consistent Extraction**: RDBMS extraction queries bind to a consistent read snapshot (`FLASHBACK ANY TABLE` / Oracle `SCN`) to prevent phantom reads and avoid locking OLTP tables.
- **Three-Tier Column Mapping**: All schema translations pass through `Source RDBMS Column -> CanonicalColumn (src/goe/offload/column_metadata.py) -> Target Backend Column`.
- **Two-Phase Staged Ingestion**: Parallel extraction writes Avro or Snappy-compressed Parquet files to cloud staging storage (`gs://`, `s3a://`, `abfss://`, `hdfs://`), followed by an atomic target load (`LOAD DATA` / `COPY INTO` / `INSERT ... SELECT`) and automatic staging cleanup.

## Gotchas & Defenses

- **Ambiguous Oracle `NUMBER` / `FLOAT`**: Unscaled Oracle `NUMBER` and `FLOAT` columns must be sampled (`sample_rdbms_data_types` / `--data-sample-pct`) before target table creation so precision and scale boundaries are bounded explicitly.
- **High-Precision Decimal Truncation**: 38-digit integers and high-precision decimals (`NUMBER(38)`) risk silent float truncation if downcast; map strictly to `INTEGER_38` or backend arbitrary-precision `NUMERIC` / `BIGNUMERIC`.
- **Cloud Storage Eventual Consistency**: Verify staged object visibility on object stores before issuing backend load queries.
