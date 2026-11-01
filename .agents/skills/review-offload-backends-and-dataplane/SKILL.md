---
name: review-offload-backends-and-dataplane
description: "Use when reviewing GOE changes touching src/goe/offload/schema/, src/goe/offload/bigquery/, src/goe/offload/snowflake/, src/goe/offload/hadoop/, src/goe/offload/spark/, src/goe/offload/staging/, src/goe/offload/transport/, or src/goe/filesystem/."
disable-model-invocation: false
---

# Review: Canonical Typing, Cloud Backends, DuckDB 2.0, Arrow & Storage (`DPL`)

<!-- truth: start -->
- `ColumnSpec(FrozenBaseStruct, frozen=True)` (`src/goe/offload/schema/column_spec.py`) and `TYPE_REGISTRY` (`src/goe/offload/schema/type_registry.py`) govern all RDBMS-to-canonical and canonical-to-backend/staging conversions; implicit lossy downcasting (`NUMBER(38)` to 32-bit `INT` or unscaled `DECIMAL` to float) is forbidden.
- Every backend exposes `BackendCapabilities` (`src/goe/offload/backend_capabilities.py`), caches table metadata in `CachedBackendCatalog` (`src/goe/offload/backend_catalog_cache.py`) with write-through DDL/load invalidation, and uses `StagingLoadService` + `FinalTableMerger` (`src/goe/offload/backend_services.py`) or `BigQueryIngestStrategy` (`src/goe/offload/bigquery/ingest_strategy.py`).
- `DuckDBEngine` (`src/goe/offload/transport/duckdb/engine.py`) targets `duckdb>=2.0.0`, clamps `memory_limit` to 75% of `CgroupQuota.detect()`, uses `:memory:goe_<execution_key>`, configures `CREATE OR REPLACE TEMPORARY SECRET` over `httpfs` (`gs://`, `s3://`, `abfss://`) and `oracle`, skips `LOAD httpfs` when `cloud_secret is None`, and verifies `AS OF SCN` via `verify_batch_scn_invariant` before connecting.
- `OracleArrowBatchExtractor` (`src/goe/offload/transport/arrow_extractor.py`) and `ArrowParquetStagingWriter` (`src/goe/offload/staging/arrow_writers.py`) stream Parquet files with schema, row-count, and cell-value parity against `OffloadTransportDuckDB`.
- `StagingStorageService` (`src/goe/filesystem/storage_service.py`) unifies GCS (`if_generation_match` atomic uploads, `max_results=2` prefix stat, 1,000-key batch deletes), S3, Azure Blob/ADLS, and local storage over `sqlspec.storage`, with keyless GCP ADC resolved via `resolve_gcp_credentials` (`src/goe/config/gcp_credentials.py`).
<!-- truth: end -->

## Workflow

1. **Load Suppression & Checklist Catalogs**:
   - Read [Checklist (`DPL-01..06`)](references/checklist.md) and [False-Positive Suppressions (`FP-DPL-01..04`)](references/false-positive-suppressions.md) before flagging any finding.
2. **Inspect Changed Files & Surrounding Context**:
   - Read the full target files around every diff hunk in this domain to verify callers, types, resource cleanup, and concurrency invariants.
3. **Evaluate Two-Axis Conformance**:
   - Check spec/behavior correctness, public-seam test strength, and adherence to `DPL-01..06` and `tools/verify_architecture.py`.
4. **Filter Against Suppressions**:
   - Drop any candidate finding matching a `DO NOT FLAG` rule in [False-Positive Suppressions](references/false-positive-suppressions.md) or lacking a concrete failure mode.

## Guardrails

- Never flag stylistic preferences already enforced by `ruff` or `mypy` unless a real defect is present.
- Never propose inline `#` comments inside function/method bodies or nested function-scoped imports (both violate `tools/verify_architecture.py`).
- Anchor every finding to an exact `path/to/file.py:line` range, rule ID (`DPL-NN`), concrete failure scenario, and minimal fix.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/offload tests/unit/filesystem -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Return structured findings citing `[<PREFIX>-NN] path/to/file.py:line — <summary>`, severity (`blocking` | `important` | `nit`), reproduction/failure trace, and concrete fix, or state that zero issues were found across `DPL-01..06`.
