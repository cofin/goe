---
type: Spec
flow_id: backend_capabilities_and_cached_catalog_20261024
title: "Chapter 9.2: Backend Capabilities and Cached Catalog"
state: completed
plan_revision: 1
plan_commit: null
state_revision: 3
current_task: null
last_operation: complete_flow
operation_targets: []
last_verified_checkpoint: "1.3"
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-26T21:30:00Z
description: "Replace the 34-key capability dictionaries, 65+ capability query methods, and monolithic BackendApiInterface and BackendTableInterface classes with BackendCapabilities, a write-through CachedBackendCatalog, and focused backend session, DDL, staging load, and final merge services."
tags: [refactor, backends, caching, capabilities, ddl]
parent_prd: prd_09_composable_backends_and_direct_bigquery_ingestion_20261024
depends_on:
  - canonical_column_model_and_type_registry_20261024
research:
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/duckdb2-arrow-and-storage-dataplane.md
---

# Chapter 9.2: Backend Capabilities and Cached Catalog

## Specification

### 1. Overview and Goals

`BackendApiInterface` (`src/goe/offload/backend_api.py:183-1800`) and `BackendTableInterface` (`src/goe/offload/backend_table.py:89-2242`) combine capability lookup dictionaries, 65+ boolean capability and limit methods, 50+ pass-through forwarders on `BackendTableInterface`, uncached or ad-hoc metadata queries, session parameter merging, DDL string formatting, staging load verification, and `INSERT INTO ... SELECT` merge assembly inside two inheritance hierarchies totaling over 4,000 lines of base-class code.

This chapter:

1. Introduces `BackendCapabilities(FrozenBaseStruct)` in `src/goe/offload/backend_capabilities.py` with declarative per-backend factory presets (`for_bigquery`, `for_snowflake`, `for_synapse`, `for_hive`, `for_impala`, `for_spark`) and `CachedBackendCatalog` in `src/goe/offload/backend_cache.py` storing frozen `BackendTableSnapshot` entries with monotonic TTL, `warm_schema(db_name)` batch warming, and deterministic write-through invalidation on `create_table`, `drop_table`, `alter_table`, and `load_table` (task 1.1).
2. Extracts composable backend services into `src/goe/offload/backend_session.py` (`BackendSessionManager`), `src/goe/offload/backend_ddl.py` (`BackendDDLCompiler`), and `src/goe/offload/backend_load.py` (`StagingLoadService`, `FinalTableMerger`) backed by `ColumnSpec` (Chapter 9.1) and `DialectSqlEngine` (PRD 7) (task 1.2).
3. Refactors `src/goe/offload/backend_api.py` and `src/goe/offload/backend_table.py` to delegate capability checks, catalog lookups, session parameter normalization, DDL generation, staged cast verification, and final table merges to those services while preserving the public method contracts consumed by the offload planner, schema sync, and secondary backends (task 1.3).

### 2. Code Analysis Summary

Files examined at `d6a02fe`:

- `src/goe/offload/backend_api.py` (1,800 LOC):
  - `CAPABILITY_*` constants imported at `:52-86` from `goe.offload.offload_constants`; `UdfParameter` (`:141-152`) and `UdfDetails` (`:154-181`) use `str_summary_of_self` (deleted in PRD 5) instead of `FrozenBaseStruct`.
  - `BackendApiInterface.__init__` (`:189-210`) merges `backend_session_parameters` via `_gen_global_session_parameters` (`:1517-1536`) and `_fixed_session_parameters` (`:1445-1448`), decrypts passwords via `_decrypt_password` (`:1436-1443`), and validates options via `_validate_connection_options` (`:1753-1756`).
  - Capability and limit surface (`:1019-1063`, `:1198-1323`, `:1758-1760`): `is_capability_supported` (`:1198-1200`), 33 boolean `<feature>_supported()` methods (`:1202-1323`), and limit/type abstract methods (`max_decimal_integral_magnitude`, `max_decimal_precision`, `max_decimal_scale`, `max_datetime_value`, `max_datetime_scale`, `max_partition_columns`, `max_sort_columns`, `max_table_name_length`, `min_datetime_value`, `native_integer_types`, `supported_backend_data_types`, `supported_date_based_partition_granularities`, `supported_partition_function_parameter_data_types`, `supported_partition_function_return_data_types`, `synthetic_partition_numbers_are_string`, `valid_staging_formats`).
  - SQL and DDL helpers (`:222-313`, `:1400-1422`, `:1450-1515`, `:1538-1698`): `decimal_scale_validation_expression`, `extract_date_part_sql_expression`, `format_column_comparison`, `_create_table_columns_clause_common`, `_create_table_column_nn_clause_common`, `_format_select_projection`, `_gen_max_column_values_sql`, `_gen_sql_text_common`, `_gen_select_count_sql_text_common`, `_get_max_column_values_common`, `_insert_literals_using_insert_values_sql_text`.
- `src/goe/offload/backend_table.py` (2,242 LOC):
  - `BackendTableInterface.__init__` (`:99-228`) validates `db_name` and `_load_db_name` against `max_db_name_length()`, initializes 30+ mutable attributes, and forwards over 50 methods to `self._db_api` (`:232-1399`).
  - Partition and synthetic column logic (`:238-380`, `:1599-1728`, `:1774-1800`): `check_partition_function`, `convert_canonical_columns_to_backend`, `_gen_synthetic_part_date_truncated_sql_expr`, `_gen_synthetic_part_date_as_string_sql_expr`, `_gen_synthetic_part_number_sql_expr`, `_gen_synthetic_part_string_sql_expr`, `_gen_synthetic_literal_function`, `_gen_synthetic_sql_cast`.
  - Final insert and materialized join SQL generation (`:1400-1598`): `_gen_final_insert_sqls`, `_gen_final_insert_subchunk_expressions`, `_gen_final_table_casts`, `_gen_mat_join_insert_sqls`.
  - Staged data and cast validation (`:1843-2165`): `_validate_final_table_casts_verification_sql`, `_validate_final_table_casts`, `_validate_staged_data_rules`, `_validate_staged_data`.
- `src/goe/offload/offload_constants.py`: defines `CAPABILITY_*` keys and per-backend capability dictionaries (`BIGQUERY_BACKEND_CAPABILITIES`, `SNOWFLAKE_BACKEND_CAPABILITIES`, `SYNAPSE_BACKEND_CAPABILITIES`, `HIVE_BACKEND_CAPABILITIES`, `IMPALA_BACKEND_CAPABILITIES`, `SPARK_BACKEND_CAPABILITIES`).

### 3. Requirements

Functional:

- **R1** `BackendCapabilities(FrozenBaseStruct)` in `src/goe/offload/backend_capabilities.py` captures all 34 boolean capability flags, identifier case sensitivity, supported staging formats, supported filesystem schemes, numeric/datetime precision and scale limits, partition and sort column limits, identifier length limits, and supported partition granularities as typed fields with factory constructors `for_backend(backend_type, target_version=None)` and `to_legacy_dict()` / `supports(capability_constant)` compatibility.
- **R2** `CachedBackendCatalog` in `src/goe/offload/backend_cache.py` stores immutable `BackendTableSnapshot(FrozenBaseStruct)` entries (`db_name`, `table_name`, `exists`, `is_view`, `columns: tuple[ColumnSpec, ...]`, `partition_columns: tuple[ColumnSpec, ...]`, `clustering_columns: tuple[str, ...]`, `size_bytes: int | None`, `row_count: int | None`, `fetched_at: float`) keyed by normalized `(db_name, table_name)` with configurable monotonic TTL (`default_ttl_seconds=60.0`), `no_caching` bypass, `warm_schema(db_name, loader)` batch pre-population, and write-through invalidation (`on_create_table`, `on_drop_table`, `on_alter_table`, `on_load_table`, `invalidate_table`, `invalidate_schema`, `clear`).
- **R3** `BackendSessionManager` in `src/goe/offload/backend_session.py` encapsulates session parameter normalization (case-insensitive clash removal against fixed backend parameters), password decryption via `PasswordTools`, connection option validation, and redacted SQL/command logging (`redact_log_message`).
- **R4** `BackendDDLCompiler` in `src/goe/offload/backend_ddl.py` compiles column definition clauses (`NOT NULL` suppression on external tables), `SELECT` projections, `SELECT COUNT(*)`, single/multi-column `MAX(...)` high-water-mark SQL, `INSERT INTO ... VALUES`, date-part extraction, column comparisons, and synthetic partition SQL cast expressions (`DATE` truncation, `YYYY-MM-DD` string formatting, numeric floor-bucket, string prefix `SUBSTR`, and UDF invocation).
- **R5** `StagingLoadService` and `FinalTableMerger` in `src/goe/offload/backend_load.py` encapsulate staging area lifecycle (`setup_staging_area`, `recreate_load_table`, `cleanup_staging_area`), staged cast expression resolution (`build_final_table_casts`), cast overflow verification SQL (`build_cast_verification_sql`, `build_cast_identification_sql`, `validate_final_table_casts`), staged data validation rules (`build_staged_validation_rules`, `validate_staged_data` checking `NOT NULL`, `NaN`, decimal scale overflow, synthetic partition digits, and range bounds), subchunk discovery (`build_subchunk_filter_clauses`), and final `INSERT INTO ... SELECT` / materialized join SQL compilation (`build_final_insert_plan`, `build_materialized_join_plan`).
- **R6** `BackendApiInterface` in `src/goe/offload/backend_api.py` and `BackendTableInterface` in `src/goe/offload/backend_table.py` convert `UdfParameter` and `UdfDetails` to `FrozenBaseStruct`, bind `self.capabilities: BackendCapabilities`, `self.catalog: CachedBackendCatalog`, `self._session_mgr: BackendSessionManager`, `self._ddl_compiler: BackendDDLCompiler`, `self._staging_service: StagingLoadService`, and `self._final_merger: FinalTableMerger`, automatically invalidate `self.catalog` on mutating DDL/load operations, and delegate all extracted methods without breaking existing subclass overrides.

Non-functional:

- **R7** `CachedBackendCatalog` is strictly instance-scoped to one backend API session and never leaks cached state across independent sessions or processes.
- **R8** Every touched file passes `ruff format --check`, `ruff check`, `mypy src/goe`, `tools/verify_architecture.py`, and the AST public-before-private check with zero inline `#` comments.

Risks and mitigations:

- **K1** Impala version-dependent capabilities (`canonical_date_supported`, `column_stats_set_supported`, `drop_column_supported`, `ranger_supported`, `sentry_supported`, `sorted_table_supported`, `filesystem_scheme_*`). Mitigation: `BackendCapabilities.for_impala(target_version)` computes version-gated booleans deterministically, and `BackendApiInterface` subclasses that override capability methods continue to work while `self.capabilities` provides the canonical struct.
- **K2** Stale catalog reads after DDL or load within the same offload execution. Mitigation: `BackendApiInterface` and `BackendTableInterface` invoke `self.catalog.on_create_table`, `self.catalog.on_drop_table`, `self.catalog.on_alter_table`, and `self.catalog.on_load_table` on every mutating path and respect `no_caching=True` in unit tests.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/offload/test_backend_capabilities_and_cache.py::test_capabilities_presets_match_legacy_constants` |
| R2 | 1.1 | `tests/unit/offload/test_backend_capabilities_and_cache.py::test_cached_catalog_hits_and_write_through_invalidation` |
| R3 | 1.2 | `tests/unit/offload/test_backend_services.py::test_session_manager_merges_parameters_and_redacts_logs` |
| R4 | 1.2 | `tests/unit/offload/test_backend_services.py::test_ddl_compiler_clauses_and_synthetic_casts` |
| R5 | 1.2 | `tests/unit/offload/test_backend_services.py::test_staging_load_service_and_final_table_merger` |
| R6 | 1.3 | `tests/unit/offload/test_backend_api.py`, `tests/unit/offload/test_backend_table.py` |
| R7 | 1.1, 1.3 | `tests/unit/offload/test_backend_capabilities_and_cache.py::test_catalog_isolation_across_sessions` |
| R8 | 1.1-1.3 | chapter verification gate below |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/test_backend_capabilities_and_cache.py tests/unit/offload/test_backend_services.py tests/unit/offload/test_backend_api.py tests/unit/offload/test_backend_table.py -v
uv run pytest tests/unit/offload tests/unit/characterization -q
uv run ruff format --check src/goe/offload/backend_capabilities.py src/goe/offload/backend_cache.py src/goe/offload/backend_session.py src/goe/offload/backend_ddl.py src/goe/offload/backend_load.py src/goe/offload/backend_api.py src/goe/offload/backend_table.py tests/unit/offload/test_backend_capabilities_and_cache.py tests/unit/offload/test_backend_services.py tests/unit/offload/test_backend_api.py tests/unit/offload/test_backend_table.py
uv run ruff check src/goe/offload/backend_capabilities.py src/goe/offload/backend_cache.py src/goe/offload/backend_session.py src/goe/offload/backend_ddl.py src/goe/offload/backend_load.py src/goe/offload/backend_api.py src/goe/offload/backend_table.py tests/unit/offload/test_backend_capabilities_and_cache.py tests/unit/offload/test_backend_services.py tests/unit/offload/test_backend_api.py tests/unit/offload/test_backend_table.py
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

Expected: every test suite, linter, type check, and architecture check exits 0.

## Implementation Plan

### Phase 1: Capabilities, Catalog Cache, and Composable Services

- [x] 1.1 Add BackendCapabilities and write-through CachedBackendCatalog ([tasks/1.1.md](tasks/1.1.md))
- [x] 1.2 Extract BackendSessionManager, BackendDDLCompiler, StagingLoadService, and FinalTableMerger ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: Base Interface Delegation

- [x] 1.3 Slim BackendApiInterface and BackendTableInterface to delegate to capabilities, catalog cache, and backend services ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `backend_capabilities_and_cached_catalog_20261024`, `completed`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: `1.3`.
- **Decisions**: place the composable backend modules directly under `src/goe/offload/` (`backend_capabilities.py`, `backend_cache.py`, `backend_session.py`, `backend_ddl.py`, `backend_load.py`) so all existing `goe.offload.*` imports remain cohesive; scope `CachedBackendCatalog` strictly per `BackendApiInterface` instance with automatic write-through invalidation on DDL and load operations.
- **Discoveries**: `BackendCapabilities`, `CachedBackendCatalog`, `BackendSessionManager`, `BackendDDLCompiler`, `StagingLoadService`, and `FinalTableMerger` extracted and wired into `BackendApiInterface` and `BackendTableInterface`; `UdfParameter` and `UdfDetails` converted to `FrozenBaseStruct` (fixing a tuple-vs-`UdfParameter` bug in `snowflake_backend_api.py`).
- **Blockers**: none.
- **Next exact step**: Proceed to Chapter 9.3 (`bigquery_ingest_strategies_20261024`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 3`.
- **Relevant knowledge**: `.agents/bundles/knowledge/backends/bigquery.md`, `.agents/bundles/knowledge/backends/snowflake.md`, `.agents/bundles/knowledge/backends/synapse.md`, `.agents/bundles/knowledge/backends/hadoop.md`, `.agents/bundles/knowledge/patterns/offload-and-typing.md`.
