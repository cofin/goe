---
type: Spec
flow_id: bigquery_ingest_strategies_20261024
title: "Chapter 9.3: BigQuery Ingest Strategies"
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
description: "Introduce pluggable BigQuery ingest strategies (GCS batch load jobs, sub-threshold direct Arrow upload, and Storage Write API pending Arrow IPC streams) and refactor BackendBigQueryApi and BackendBigQueryTable onto BackendCapabilities, CachedBackendCatalog, DialectSqlEngine, and CanonicalTypeRegistry."
tags: [feature, bigquery, ingestion, arrow]
parent_prd: prd_09_composable_backends_and_direct_bigquery_ingestion_20261024
depends_on:
  - backend_capabilities_and_cached_catalog_20261024
research:
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/duckdb2-arrow-and-storage-dataplane.md
---

# Chapter 9.3: BigQuery Ingest Strategies

## Specification

### 1. Overview and Goals

BigQuery offloads currently execute up to six BigQuery jobs and three full staging scans per offload chunk (`CREATE EXTERNAL TABLE` or `load_table_from_uri(WRITE_TRUNCATE)` into `<load_db>.<load_table>`, a `COUNT(*)` + `CASE WHEN` staged validation scan, a `SAFE_CAST` overflow check scan, an `INSERT INTO <target> SELECT SAFE_CAST(...) FROM <load_table>`, and `DROP TABLE <load_table>`), while `BackendBigQueryApi` (`src/goe/offload/bigquery/bigquery_backend_api.py`, 2,245 LOC) and `BackendBigQueryTable` (`src/goe/offload/bigquery/bigquery_backend_table.py`, 551 LOC) duplicate capability lookups, ad-hoc `_cached_bq_tables` state, hand-rolled SQL strings, and column type mapping logic.

This chapter:

1. Creates `src/goe/offload/bigquery/ingest_strategy.py` defining `BigQueryIngestStrategyProtocol`, `BigQueryLoadRequest(FrozenBaseStruct)`, `BigQueryLoadResult(FrozenBaseStruct)`, `GcsLoadJobStrategy` (for `>= 10 MB` multi-file GCS Parquet and Avro loads with `DecimalTargetTypes`, CMEK, and `WRITE_APPEND` direct target load or `WRITE_TRUNCATE` staging load), `DirectArrowUploadStrategy` (for `< 10 MB` sub-threshold Arrow `pa.Table` / `pa.RecordBatchReader` uploads via `load_table_from_dataframe` / Arrow Parquet buffer without GCS staging round-trips), `StorageWriteStreamStrategy` (using `google-cloud-bigquery-storage` Arrow IPC `PENDING` streams with `finalize_write_stream` and atomic `batch_commit_write_streams`), and `select_bigquery_ingest_strategy` (task 1.1).
2. Refactors `src/goe/offload/bigquery/bigquery_backend_api.py` to delegate capability checks to `BackendCapabilities.for_bigquery()`, table and SDK handle caching to `CachedBackendCatalog` (including 2-query `warm_schema` `INFORMATION_SCHEMA` batch loading), SQL generation to `DialectSqlEngine("bigquery")`, column mapping to `CanonicalTypeRegistry`, and batch/direct loads to `BigQueryIngestStrategyProtocol` while enriching `src/goe/observability/bigquery.py` with Storage Write stream span attributes (task 1.2).
3. Refactors `src/goe/offload/bigquery/bigquery_backend_table.py` to select and execute the appropriate `BigQueryIngestStrategyProtocol` from `OffloadOptions`, payload size, and staging preconditions while keeping `tests/unit/characterization/test_offload_bigquery_golden.py` 100% green (task 1.3).

### 2. Code Analysis Summary

Files examined at `d6a02fe`:

- `src/goe/offload/bigquery/bigquery_load_job.py` (40 LOC): `PARQUET_DECIMAL_TARGET_TYPES` (`:10-14`), `STAGING_SOURCE_FORMATS` (`:15-18`), and `build_staging_load_job_config` (`:21-40`) which sets `WriteDisposition.WRITE_TRUNCATE`, `decimal_target_types`, `labels`, and `destination_encryption_configuration`.
- `src/goe/offload/bigquery/bigquery_backend_api.py` (2,245 LOC):
  - Client and KMS initialization (`:157-182`, `:2015-2033`), `_cached_bq_tables` dictionary (`:168`, `:2009-2013`, `:2091-2100`), `_get_bq_table_partition_field` and `_get_bq_table_partition_type` (`:2102-2118`).
  - DDL and DML execution (`:195-232`, `:1802-1903`), query execution (`_execute_query_fetch_x` `:1930-2007`), `INFORMATION_SCHEMA` catalog queries (`list_tables`, `list_views`, `list_udfs`, `udf_details` `:1446-1488`, `_get_table_ddl` `:2164-2191`).
  - Column type mappings (`valid_canonical_override`, `to_canonical_column`, `from_canonical_column` `:1490-1737`), replaced by `CanonicalTypeRegistry` in Chapter 9.1.
- `src/goe/offload/bigquery/bigquery_backend_table.py` (551 LOC):
  - Staging lifecycle (`cleanup_staging_area` `:94-96`, `setup_staging_area` `:225-230`, `post_transport_tasks` `:200-202`, `_create_load_table` `:244-281`, `_load_native_load_table` `:283-302`, `_drop_load_table` `:304-306`).
  - Final insert and materialized join (`load_final_table` `:144-162`, `load_materialized_join` `:163-195`, `_final_insert_format_sql` `:308-328`, `_final_insert_query_options` `:330-337`).
  - Synthetic partition and staged cast expressions (`_gen_synthetic_partition_column_object` `:339-355`, `_gen_synthetic_partition_date_as_string_sql_expr` `:357-365`, `_gen_synthetic_partition_date_truncated_sql_expr` `:367-388`, `_gen_synthetic_part_number_granularity_sql_expr` `:390-410`, `_gen_synthetic_part_string_granularity_sql_expr` `:412-413`, `_staging_to_backend_cast` `:427-551`).
- `src/goe/observability/bigquery.py` (95 LOC): `bigquery_trace_labels`, `merge_trace_labels`, `traced_bigquery_job`, and `record_bigquery_job_metadata`.

### 3. Requirements

Functional:

- **R1** `src/goe/offload/bigquery/ingest_strategy.py` defines `BigQueryLoadRequest(FrozenBaseStruct)`, `BigQueryLoadResult(FrozenBaseStruct)`, `BigQueryIngestStrategyProtocol`, and three concrete strategy implementations:
  - `GcsLoadJobStrategy`: executes `client.load_table_from_uri` for `>= 10 MB` multi-file GCS Parquet or Avro loads with `PARQUET_DECIMAL_TARGET_TYPES`, CMEK `EncryptionConfiguration`, trace-merged job labels, and configurable `write_disposition` (`WRITE_TRUNCATE` for staged load tables or `WRITE_APPEND` for direct target loads).
  - `DirectArrowUploadStrategy`: ingests `< 10 MB` sub-threshold Arrow `pa.Table` or `pa.RecordBatchReader` payloads directly into BigQuery without a GCS staging round-trip via `client.load_table_from_dataframe` (or `client.load_table_from_file` with an in-memory Arrow-to-Parquet buffer when dataframe upload is unavailable for the given stream), applying `PARQUET_DECIMAL_TARGET_TYPES`, CMEK, and job labels.
  - `StorageWriteStreamStrategy`: writes Arrow `pa.RecordBatch` streams to BigQuery Storage Write API `PENDING` streams (`create_write_stream` -> `append_rows` with serialized Arrow `ipc_schema` and `serialized_record_batch` -> `finalize_write_stream` -> atomic `batch_commit_write_streams`), cleaning up uncommitted streams on failure.
- **R2** `select_bigquery_ingest_strategy` deterministically selects:
  - `StorageWriteStreamStrategy` when `ingest_mode == "STORAGE_WRITE"` (opt-in) and an Arrow stream/table is provided without staged-only SQL requirements.
  - `DirectArrowUploadStrategy` when `arrow_source is not None` and `payload_bytes is not None and payload_bytes < 10 * 1024 * 1024` (10 MiB threshold) and no staged-only SQL precondition is active.
  - `GcsLoadJobStrategy` for `>= 10 MiB` or URI-based GCS Parquet/Avro loads.
- **R3** `BackendBigQueryApi` in `src/goe/offload/bigquery/bigquery_backend_api.py` replaces `self._cached_bq_tables` with `self.catalog` (`CachedBackendCatalog`), exposes `warm_schema(db_name)` querying `INFORMATION_SCHEMA.TABLES` and `INFORMATION_SCHEMA.COLUMNS` in two queries, delegates SQL generation to `DialectSqlEngine("bigquery")`, and exposes `execute_ingest(request, strategy=None) -> BigQueryLoadResult`.
- **R4** `BackendBigQueryTable` in `src/goe/offload/bigquery/bigquery_backend_table.py` routes load operations through `select_bigquery_ingest_strategy` and `self._db_api.execute_ingest(...)`, supports direct target ingestion as well as staged native/external load tables (when backend UDF partition functions, `--offload-chunk-column`, `--preserve-load-table`, or stringified staging require the staged SQL path), and keeps `tests/unit/characterization/test_offload_bigquery_golden.py` 100% green.

Non-functional:

- **R5** All BigQuery load jobs and Storage Write operations emit `goe.backend.bigquery.<operation>` OpenTelemetry spans and job metrics via `src/goe/observability/bigquery.py`.
- **R6** Every touched file passes `ruff format --check`, `ruff check`, `mypy src/goe`, `tools/verify_architecture.py`, and the AST public-before-private check with zero inline `#` comments.

Risks and mitigations:

- **K1** Golden characterization tests in `tests/unit/characterization/test_offload_bigquery_golden.py` assert exact logged command strings (`BigQuery load job: gs://... -> project.dataset.table (format=..., write_disposition=...)` and `CREATE EXTERNAL TABLE`). Mitigation: `GcsLoadJobStrategy.format_log_command` emits the exact command string pinned by `test_offload_bigquery_golden.py`, and staged external/native table modes preserve their exact logged SQL/command sequence.
- **K2** `google-cloud-bigquery-storage` is an optional runtime dependency in minimal environments. Mitigation: `StorageWriteStreamStrategy` imports `google.cloud.bigquery_storage_v1` via `goe.util.module_loader.import_optional` and raises a clear `BackendApiException` if invoked when the package is absent.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/offload/bigquery/test_ingest_strategy.py` |
| R2 | 1.1, 1.3 | `tests/unit/offload/bigquery/test_ingest_strategy.py::test_strategy_selection_by_mode_and_payload_size`, `tests/unit/offload/bigquery/test_bigquery_backend_table.py` |
| R3 | 1.2 | `tests/unit/offload/bigquery/test_bigquery_backend_api.py` |
| R4 | 1.3 | `tests/unit/offload/bigquery/test_bigquery_backend_table.py`, `tests/unit/characterization/test_offload_bigquery_golden.py` |
| R5 | 1.1, 1.2 | `tests/unit/offload/bigquery/test_ingest_strategy.py::test_observability_spans_recorded` |
| R6 | 1.1-1.3 | chapter verification gate below |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/bigquery tests/unit/characterization/test_offload_bigquery_golden.py -v
uv run pytest tests/unit/offload -q
uv run ruff format --check src/goe/offload/bigquery src/goe/observability/bigquery.py tests/unit/offload/bigquery tests/unit/characterization/test_offload_bigquery_golden.py
uv run ruff check src/goe/offload/bigquery src/goe/observability/bigquery.py tests/unit/offload/bigquery tests/unit/characterization/test_offload_bigquery_golden.py
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

Expected: all unit and golden characterization tests pass and all lint, type, and architecture gates exit 0.

## Implementation Plan

### Phase 1: BigQuery Ingest Strategies and API Refactor

- [ ] 1.1 Add BigQueryIngestStrategyProtocol, GcsLoadJobStrategy, DirectArrowUploadStrategy, and StorageWriteStreamStrategy ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Refactor BackendBigQueryApi onto BackendCapabilities, CachedBackendCatalog, DialectSqlEngine, and BigQueryIngestStrategyProtocol ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: BigQuery Table Strategy Selection and Golden Parity

- [ ] 1.3 Refactor BackendBigQueryTable to select ingest strategies and preserve BigQuery golden characterization ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `bigquery_ingest_strategies_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `10 MiB` (`10 * 1024 * 1024` bytes) is the default sub-threshold cutoff between `DirectArrowUploadStrategy` and `GcsLoadJobStrategy`; `StorageWriteStreamStrategy` uses `PENDING` streams committed atomically via `batch_commit_write_streams`; `GcsLoadJobStrategy` preserves the exact log command format expected by `test_offload_bigquery_golden.py`.
- **Discoveries**: none yet.
- **Blockers**: Chapter 9.2 (`backend_capabilities_and_cached_catalog_20261024`) must complete first.
- **Next exact step**: execute task `1.1` (`bigquery_ingest_strategies_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/backends/bigquery.md`, `.agents/bundles/knowledge/architecture/type-mapping.md`, `.agents/bundles/knowledge/patterns/offload-and-typing.md`.
