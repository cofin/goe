---
type: Spec
flow_id: canonical_column_model_and_type_registry_20261024
title: "Chapter 9.1: Canonical Column Model and Type Registry"
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
description: "Replace the mutable ColumnMetadataInterface hierarchy and the per-dialect column subclasses with one frozen ColumnSpec and a table-driven CanonicalTypeRegistry after pinning every current mapping with golden characterization tables."
tags: [refactor, typing, type-mapping, backends]
parent_prd: prd_09_composable_backends_and_direct_bigquery_ingestion_20261024
depends_on:
  - prd_05_foundation_typing_settings_and_adapter_reduction_20261024
  - prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024
  - prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024
  - prd_08_duckdb2_transport_query_import_parity_and_storage_20261024
research:
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/duckdb2-arrow-and-storage-dataplane.md
---

# Chapter 9.1: Canonical Column Model and Type Registry

## Specification

### 1. Overview and Goals

GOE describes every column (source RDBMS, canonical, backend, staging file) with a mutable class hierarchy rooted at `ColumnMetadataInterface` (`src/goe/offload/column_metadata.py:324-495`), one subclass per dialect, and per-owner mapping methods (`to_canonical_column`, `from_canonical_column`, `valid_canonical_override`) spread over frontend source tables, backend APIs, and staging files. This chapter:

1. Pins every current mapping result, column trait, formatted data type, constructor normalization, and synthetic partition name in golden characterization tables before any code moves (task 1.1).
2. Adds `ColumnSpec(FrozenBaseStruct)`: one immutable value type with a `dialect` field, the same attribute names as today, table-driven dialect traits, and the column helper functions (task 1.2).
3. Adds `CanonicalTypeRegistry`: ordered rule tables for canonical-to-physical and physical-to-canonical mapping with precision, scale, and byte-length guards, override validation, staging-format mapping, and synthetic partition column types (task 1.3).
4. Cuts every column call site over to `ColumnSpec` and the registry, deletes `src/goe/offload/column_metadata.py` and every `*_column.py` subclass, and deletes the superseded mapping method bodies (task 1.4).

The golden tables are the acceptance oracle for tasks 1.2, 1.3, and 1.4: every expected value captured from the current classes in task 1.1 is reproduced byte for byte by the new model.

### 2. Code Analysis Summary

Files examined at `d6a02fe`:

- `src/goe/offload/column_metadata.py` (566 LOC): canonical type constants `GOE_TYPE_*` (`:23-42`), `ALL_CANONICAL_TYPES` and the date/numeric/string groups (`:44-82`), `CANONICAL_TYPE_OPTION_NAMES` (`:84-100`), `CANONICAL_TYPE_BYTE_LENGTHS` (`:102-109`), char semantics constants (`:111-113`), `SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE` and `SYNTHETIC_PARTITION_COLUMN_NAME_RE` (`:115-117`), staging name tokens (`:119-120`), helper functions (`:123-253`), mutable `ColumnPartitionInfo` with `synthetic_name()` (`:260-321`), `ColumnMetadataInterface` with nine abstract trait methods, `clone()` and the mutating `set_simplified_staging_column_name()` (`:324-495`), and `CanonicalColumn` (`:498-566`). `__str__`/`__repr__` use `goe.util.misc_functions.str_summary_of_self` (`:16`, `:294-298`, `:364-368`), which Chapter 5.4 deletes.
- Column subclasses (constants plus one class each): `src/goe/offload/oracle/oracle_column.py` (274 LOC; constructor normalization of `TIMESTAMP(n)`/interval types and N-type char semantics `:72-102`, `from_oracle` dictionary-row factory `:104-148`, `format_data_type` `:150-200`), `src/goe/offload/microsoft/mssql_column.py` (198 LOC; `from_mssql` `:74-100`), `src/goe/offload/bigquery/bigquery_column.py` (133 LOC; `FLOAT`/`INTEGER` aliasing and char length rules `:46-70`), `src/goe/offload/snowflake/snowflake_column.py` (133 LOC; `is_unbound_string` override `:119-128`), `src/goe/offload/microsoft/synapse_column.py` (190 LOC; `collation` `:61-75`), `src/goe/offload/hadoop/hadoop_column.py` (121 LOC), `src/goe/offload/staging/parquet/parquet_column.py` (90 LOC), `src/goe/offload/staging/avro/avro_column.py` (82 LOC). `src/goe/offload/teradata/teradata_column.py` is deleted by Chapter 5.1.
- Mapping owners (method spans at `d6a02fe`): `OracleSourceTable.to_canonical_column`/`from_canonical_column`/`valid_canonical_override` (`src/goe/offload/oracle/oracle_offload_source_table.py:628-741`, `:743-887`, `:889-926`) plus `OffloadSourceTableInterface._frontend_decimal_to_integral_type` (`src/goe/offload/offload_source_table.py:983-1001`) and `to_canonical_column_with_overrides` (`:850-893`); `MSSQLSourceTable` (`src/goe/offload/microsoft/mssql_offload_source_table.py:280-322`, `:324-443`, `:445-447`); `BackendBigQueryApi` (`src/goe/offload/bigquery/bigquery_backend_api.py:1490-1519`, `:1527-1595`, `:1597-1737`); `BackendSnowflakeApi` (`src/goe/offload/snowflake/snowflake_backend_api.py:1492-1520`, `:1550-1609`, `:1611-1722`); `BackendSynapseApi` (`src/goe/offload/microsoft/synapse_backend_api.py:1566-1597`, `:1619-1770`, `:1772-1904`); `BackendHadoopApi` (`src/goe/offload/hadoop/hadoop_backend_api.py:1025-1054`, `:1062-1139`, `:1141-1263`) with `BackendApiInterface._apply_decimal_padding_digits` (`src/goe/offload/backend_api.py:1354-1398`, called at `hadoop_backend_api.py:1214`); `BackendImpalaApi.from_canonical_column` (`src/goe/offload/hadoop/impala_backend_api.py:328-360`); staging `OffloadStagingParquetFile` (`src/goe/offload/staging/parquet/parquet_staging_file.py:87-93`, `:104-234`), `OffloadStagingAvroFile` (`src/goe/offload/staging/avro/avro_staging_file.py:88-184`), `OffloadStagingAvroImpalaFile.from_canonical_column` (`:302-333`), and `OffloadStagingFileInterface._map_from_canonical_columns` (`src/goe/offload/staging/staging_file.py:110-119`, the only caller of `set_simplified_staging_column_name` at `:115`); `BackendTableInterface.to_canonical_column_with_overrides` (`src/goe/offload/backend_table.py:805-871`).
- Mapping functions read owner state: `max_datetime_scale()` (Oracle `:866`, `:871`; BigQuery `:1590`, `:1594`, `:1726-1730`; Snowflake `:1606-1608`; Synapse `:1866-1891`), `max_decimal_precision()`/`max_decimal_scale()` (BigQuery `:1577-1578`; Snowflake and Synapse `:1699`, `:1851`), `canonical_date_supported()` (BigQuery `:1721`; Impala version gate `impala_backend_api.py:114-117`), `gen_default_numeric_column()` (Snowflake `:1698`, Synapse `:1850`), and VVERBOSE logging (BigQuery `:1689-1692`, `:1706-1709`; `offload_source_table.py:992-995`).
- Construction volume (AST scan of `src/goe` and `tests`, Teradata excluded): 1,468 constructor calls (`CanonicalColumn` 546, `OracleColumn` 208, `SynapseColumn` 189, `HadoopColumn` 180, `BigQueryColumn` 102, `SnowflakeColumn` 100, `MSSQLColumn` 41, `StagingParquetColumn` 40, `StagingAvroColumn` 38, `ColumnPartitionInfo` 24). Only `mssql_column.py:89` (inside `from_mssql`, deleted) passes more than two positional arguments; five `gen_column_object` methods forward `**kwargs` (`bigquery_backend_api.py:724`, `hadoop_backend_api.py:519`, `mssql_frontend_api.py:168`, `synapse_backend_api.py:690`, `oracle_frontend_api.py:212`, `snowflake_backend_api.py:633`).
- Mutation sites on column objects (the only places that break when columns become frozen): `backend_table.py:326`, `:330`, `:556` (`partition_info`), `:852-867` (`clone` plus `data_scale`), `:1293`; `offload_source_table.py:882`, `:885`, `:889` (`nullable`), `:1022-1025` (`clone` plus `partition_info`); `operation/data_type_controls.py:223-224` (`char_semantics`, `from_override`); `operation/not_null_columns.py:44-54` (`clone` plus `nullable`); `transport/base.py:302`, `:304` (Chapter 8.3 relocates this code); `orchestration/operation.py:1002` (`partition_info`); `synapse_backend_api.py:432-433` (`clone` plus `collation`); `snowflake_backend_table.py:252` (`clone`); `staging_file.py:115`.
- `isinstance` checks against column classes: 60 sites in 18 production modules (`backend_api.py:295`, `:304-305`; `backend_table.py:434`, `:584`, `:665`, `:825`, `:1258`, `:1285`, `:1383`, `:1678`; BigQuery, Snowflake, Synapse, Hadoop API and table modules; `offload_functions.py:114`; `offload_source_table.py:290-291`, `:624`, `:863`; `offload_xform_functions.py:26`; Oracle and MSSQL source tables; staging files).
- Importers: 60 production modules import `goe.offload.column_metadata` and 38 import a `*_column` module at `d6a02fe`. Earlier PRDs change this set before this chapter runs: Chapter 5.1 deletes the Teradata modules; Chapter 7.1 replaces `bigquery_sql.py` with `src/goe/offload/sql_ast/dialect_engine.py`; Chapter 7.2 deletes every `*_literal.py`, `*_predicate.py` (including `synthetic_partition_literal.py`) and replaces `predicate_offload.py`; Chapter 7.3 replaces `offload_validation.py`; Chapter 7.4 rewrites `src/goe/schema_sync/**`; Chapter 8.2 deletes `src/goe/util/{parquet_encoder,avro_encoder}.py` and rewrites `query_import`; Chapter 8.3 splits `transport/base.py`; Chapter 6.4 moves the MSSQL frontend onto `MssqlPythonConfig`; Chapter 5.4 moves `hive_table_stats.py` to `src/goe/offload/hadoop/`. Task 1.4 enumerates the live importer set with `git grep` before editing.
- `msgspec==0.22.0` facts verified in `.venv`: `msgspec.structs.force_setattr` and `msgspec.structs.replace` exist; assigning an attribute on a frozen struct raises `AttributeError: immutable type`; `msgspec.structs.replace` runs `__post_init__` again (probe output `[1, 2]`), so normalization in `__post_init__` must be idempotent and must never overwrite an explicitly supplied value.
- Existing tests: `tests/unit/offload/test_data_type_mappings.py` (2,422 LOC; per-dialect to/from canonical tests whose `column_assertions` at `:299-328` skips attributes expected to be `None`, so `None` results are not pinned), `tests/unit/offload/test_columns.py` (372 LOC), `tests/unit/offload/test_column_metadata.py` (158 LOC), `tests/unit/offload/test_staging_file.py`, `tests/unit/characterization/test_offload_bigquery_golden.py` (constructs `OracleColumn`, `CanonicalColumn`, `BigQueryColumn`, `ColumnPartitionInfo`), and the integration test framework under `tests/testlib/test_framework/**` (about 550 column constructions).

### 3. Requirements

Functional:

- **R1** Every current mapping result is pinned before code moves: physical-to-canonical for Oracle, MSSQL, BigQuery, Snowflake, Synapse, and Hadoop (Hive and Impala share one method); canonical-to-physical for Oracle, BigQuery, Snowflake, Synapse, Hive, Impala (with `decimal_padding_digits` 0 and 2), Parquet staging, Avro staging, and Avro-for-Impala staging (each with `binary_data_as_base64` true and false); canonical override validity for every source type and every canonical type plus one unknown type; staging-to-canonical; trait predicates and `format_data_type()` for every dialect type; constructor normalization; synthetic partition names. Expected values include `None` attributes and raised exception types.
- **R2** `ColumnSpec(FrozenBaseStruct)` is the single column type: fields `dialect, name, data_type, data_length, data_precision, data_scale, nullable, data_default, safe_mapping, partition_info, char_length, char_semantics, staging_file_column_name, from_override, hidden, collation`; trait methods keep their current names and results; `replace(**changes)` returns a modified copy; `with_simplified_staging_column_name(position)` replaces the mutating setter.
- **R3** `ColumnPartitionSpec(FrozenBaseStruct)` replaces `ColumnPartitionInfo`; `synthetic_name()` returns byte-identical names.
- **R4** Dialect vocabularies (`ORACLE_TYPE_*`, `MSSQL_TYPE_*`, `BIGQUERY_TYPE_*`, `SNOWFLAKE_TYPE_*`, `SYNAPSE_TYPE_*`, `HADOOP_TYPE_*`, `PARQUET_TYPE_*`, `AVRO_TYPE_*`, Oracle type regular expressions) and trait tables live in `src/goe/offload/schema/column_spec.py`.
- **R5** `CanonicalTypeRegistry` in `src/goe/offload/schema/type_registry.py` maps through ordered rule tables (one table per source dialect and per mapping target) with precision, scale, and byte-length guards; validates canonical overrides; maps canonical columns to staging columns; returns synthetic partition column types; mapping limits come from a frozen `TypeMappingLimits` supplied by the owner.
- **R6** Mapping owners delegate to the registry and their old mapping bodies are deleted in the same task.
- **R7** `src/goe/offload/column_metadata.py` and every `*_column.py` module are deleted; no alias, re-export, or wrapper of the old names remains.
- **R8** No code mutates a column; no code checks `isinstance` against a deleted class.

Non-functional:

- **R9** `tests/unit/characterization/test_offload_bigquery_golden.py` stays green with unchanged expected strings.
- **R10** `uv run ruff format --check`, `uv run ruff check`, `uv run mypy src/goe`, `uv run python tools/verify_architecture.py`, and the AST public-before-private check pass on every touched file; no new entry is added to `tools/architecture_baseline.toml`.

Risks and mitigations:

- **K1** Value equality: msgspec structs compare by field values, old columns compared by identity. Mitigation: task 1.4 checks `list.index`, `list.remove`, `in`, and `==` on column lists with `git grep -n -E "\.(index|remove)\(|in (self\.)?_?columns"` over the touched files and records any site whose result can change; none is expected because a table never holds two columns with the same name.
- **K2** `msgspec.structs.replace` re-runs `__post_init__`. Mitigation: every normalization rule applies only when the target attribute is `None` or matches a value it rewrites, and task 1.2 tests `replace()` round trips.
- **K3** `repr()` text of columns changes (msgspec repr instead of `str_summary_of_self`). Only VVERBOSE log lines print columns (`staging_file.py:117`, `str_list_of_columns` callers); default text output is unchanged.
- **K4** Earlier PRDs move importers. Mitigation: task 1.4 starts with a scripted importer inventory and stops (Flow block) when an importer outside its `files` list appears.
- **K5** Codemod precision. Mitigation: task 1.4 ships an exact rewrite table, runs `ruff check --select I --fix` to merge imports, and gates on the full unit suite plus `mypy`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/offload/test_data_type_mappings.py`, `tests/unit/offload/test_columns.py` against `tests/unit/offload/schema/type_mapping_cases.py` |
| R2 | 1.2, 1.4 | `tests/unit/offload/schema/test_column_spec.py`; full unit suite after cutover |
| R3 | 1.2 | `test_column_spec.py::test_synthetic_name_matches_golden` |
| R4 | 1.2 | `test_column_spec.py::test_traits_match_golden`, `::test_format_data_type_matches_golden` |
| R5 | 1.3 | `tests/unit/offload/schema/test_type_registry.py` against the golden tables |
| R6 | 1.4 | `test_type_registry.py` plus owner delegation tests in `tests/unit/offload/test_backend_api.py` and `tests/unit/offload/test_offload_source_table.py` |
| R7 | 1.4 | `git ls-files 'src/goe/**/*_column.py' src/goe/offload/column_metadata.py` prints nothing; `git grep -n "column_metadata\|ColumnMetadataInterface\|CanonicalColumn\|ColumnPartitionInfo" -- src tests` prints nothing |
| R8 | 1.4 | `mypy src/goe` (frozen attribute assignment errors) and the full unit suite |
| R9 | 1.4 | `uv run pytest tests/unit/characterization/test_offload_bigquery_golden.py` |
| R10 | 1.1-1.4 | chapter gate below |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/schema -q
uv run pytest tests/unit/characterization/test_offload_bigquery_golden.py -q
uv run pytest tests/unit -q
GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only -q
uv run ruff format --check src/goe tests/unit tests/testlib tests/integration
uv run ruff check src/goe tests/unit tests/testlib tests/integration
uv run mypy src/goe
uv run python tools/verify_architecture.py
test -z "$(git ls-files 'src/goe/**/*_column.py' src/goe/offload/column_metadata.py)"
test -z "$(git grep -n -E 'column_metadata|ColumnMetadataInterface|CanonicalColumn|ColumnPartitionInfo' -- src tests)"
```

Expected: every command exits 0; the two `test -z` checks print nothing.

## Implementation Plan

### Phase 1: Characterization and new model

- [ ] 1.1 Pin every column mapping, trait, and format with golden tables ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Add the frozen ColumnSpec model, dialect vocabulary, and column helpers ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Add the table-driven CanonicalTypeRegistry ([tasks/1.3.md](tasks/1.3.md))

### Phase 2: Cutover

- [ ] 1.4 Cut every column call site over to ColumnSpec and the registry and delete the column subclasses ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `canonical_column_model_and_type_registry_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: one `ColumnSpec` type with a `dialect` field and unchanged attribute and trait-method names; dialect vocabularies and trait tables live in `column_spec.py`, mapping rules in `type_registry.py`; `src/goe/offload/schema/__init__.py` holds only a docstring (importers use the submodules); golden tables are captured from the current classes and never edited by later tasks; the cutover is one task because the column type is shared by every layer and a partial swap cannot keep the suite green.
- **Discoveries**: none yet.
- **Blockers**: Master PRDs 5, 6, 7, and 8 must complete first (`goe.typing.FrozenBaseStruct`, `GOEError`, `tools/verify_architecture.py`, and the importer moves listed in §2).
- **Next exact step**: execute task `1.1` (`canonical_column_model_and_type_registry_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/architecture/type-mapping.md`, `.agents/bundles/knowledge/patterns/offload-and-typing.md`, `.agents/bundles/knowledge/standards/python.md`, `.agents/bundles/knowledge/standards/testing.md`.
