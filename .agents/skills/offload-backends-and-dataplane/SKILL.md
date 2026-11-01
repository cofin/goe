---
name: offload-backends-and-dataplane
description: "Use when working on ColumnSpec, TYPE_REGISTRY, BackendCapabilities, CachedBackendCatalog, BigQueryIngestStrategy, Snowflake/Synapse/Hadoop backends, DuckDBEngine, ArrowParquetStagingWriter, Spark transports, or StagingStorageService."
disable-model-invocation: false
---

# Canonical Typing, Cloud Backends, DuckDB 2.0, Arrow & Storage

<!-- truth: start -->
- `ColumnSpec(FrozenBaseStruct, frozen=True)` (`src/goe/offload/schema/column_spec.py`) and `TYPE_REGISTRY` (`src/goe/offload/schema/type_registry.py`) govern all RDBMS-to-canonical and canonical-to-backend/staging conversions; implicit lossy downcasting (`NUMBER(38)` to 32-bit `INT` or unscaled `DECIMAL` to float) is forbidden.
- Every backend exposes `BackendCapabilities` (`src/goe/offload/backend_capabilities.py`), caches table metadata in `CachedBackendCatalog` (`src/goe/offload/backend_catalog_cache.py`) with write-through DDL/load invalidation, and uses `StagingLoadService` + `FinalTableMerger` (`src/goe/offload/backend_services.py`) or `BigQueryIngestStrategy` (`src/goe/offload/bigquery/ingest_strategy.py`).
- `DuckDBEngine` (`src/goe/offload/transport/duckdb/engine.py`) targets `duckdb>=2.0.0`, clamps `memory_limit` to 75% of `CgroupQuota.detect()`, uses `:memory:goe_<execution_key>`, configures `CREATE OR REPLACE TEMPORARY SECRET` over `httpfs` (`gs://`, `s3://`, `abfss://`) and `oracle`, skips `LOAD httpfs` when `cloud_secret is None`, and verifies `AS OF SCN` via `verify_batch_scn_invariant` before connecting.
- `OracleArrowBatchExtractor` (`src/goe/offload/transport/arrow_extractor.py`) and `ArrowParquetStagingWriter` (`src/goe/offload/staging/arrow_writers.py`) stream Parquet files with schema, row-count, and cell-value parity against `OffloadTransportDuckDB`.
- `StagingStorageService` (`src/goe/filesystem/storage_service.py`) unifies GCS (`if_generation_match` atomic uploads, `max_results=2` prefix stat, 1,000-key batch deletes), S3, Azure Blob/ADLS, and local storage over `sqlspec.storage`, with keyless GCP ADC resolved via `resolve_gcp_credentials` (`src/goe/config/gcp_credentials.py`).
<!-- truth: end -->

## Workflow

1. **Ground in Domain Seams & Knowledge**:
   - Read [Patterns & Seams](references/patterns-and-seams.md) and the linked OKF v0.2 chapters before editing production modules:
- [Canonical Type Mapping System](../../bundles/knowledge/architecture/type-mapping.md)
- [Google BigQuery Backend Adapter](../../bundles/knowledge/backends/bigquery.md)
- [DuckDB 2.0 & duckdb-oracle Transport](../../bundles/knowledge/transport/duckdb.md)
- [Staging Serialization & Encoders](../../bundles/knowledge/transport/staging-serialization.md)
- [Google Cloud Storage & StagingStorageService](../../bundles/knowledge/storage/gcs.md)
- [ADR-002: DuckDB 2.0 Data Plane & Direct BigQuery Loads](../../bundles/knowledge/decisions/adr-002-duckdb2-dataplane-and-target-typed-bigquery-loads.md)
2. **Verify Public Seams First**:
   - Classify touched dependencies (`In-process`, `Local-substitutable`, `Remote-owned`, `External boundary`) and write or update unit tests in the canonical `tests/unit/` module before changing implementation behavior.
3. **Implement Within Architectural Boundaries**:
   - Preserve `FrozenBaseStruct(..., frozen=True)` / `BaseStruct` contracts, route JSON through `goe.serializers`, keep imports at module top-level (or `if TYPE_CHECKING:` / `import_optional_dependency`), and place public methods/functions above `_` private helpers.
4. **Run Focused & Aggregate Verification**:
   - Run the focused pytest suite, `uv run python tools/verify_architecture.py`, and `make lint`.

## Guardrails

- Never violate the 6 AST/token rules in `tools/verify_architecture.py` (`raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`).
- Never introduce inline `#` comments inside function or method bodies; document rationale in Google-style docstrings.
- Never add backward-compatibility shims, unused re-exports, or standalone `test_*_remediation.py` files; place tests in the canonical `tests/unit/` file for the module under test.
- Check [Review Checklist](../review-offload-backends-and-dataplane/references/checklist.md) and [False-Positive Suppressions](../review-offload-backends-and-dataplane/references/false-positive-suppressions.md) before finalizing changes.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/offload tests/unit/filesystem -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Summarize modified files, public-seam tests executed, and exact exit statuses for `pytest`, `verify_architecture.py`, and `make lint`.
