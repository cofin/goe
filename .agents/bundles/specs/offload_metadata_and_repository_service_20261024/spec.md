---
type: Spec
flow_id: offload_metadata_and_repository_service_20261024
title: "Chapter 6.2: OffloadMetadata and Repository Service"
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
description: "Replace the mutable active-record OrchestrationMetadata and OracleOrchestrationRepoClient with frozen msgspec persistence models and an OracleRepositoryService that loads offload metadata in one round trip and executes repository procedures through pooled SQLSpec sessions."
tags: [refactor, persistence, oracle, sqlspec, msgspec]
parent_prd: prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024
depends_on: [oracle_database_registry_and_session_tracing_20261024]
research:
  - .agents/bundles/specs/prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 6.2: OffloadMetadata and Repository Service

## Specification

### 1. Overview and Goals

`OrchestrationMetadata` (`src/goe/persistence/orchestration_metadata.py`) is an active-record wrapper around an untyped upper-case dictionary that embeds a repository client and mutates state in place. Loading a single table's metadata through `OracleOrchestrationRepoClient._get_metadata` (`src/goe/persistence/oracle/oracle_orchestration_repo_client.py:415-430`) currently takes four network round trips: one `conn.gettype("OFFLOAD_METADATA_OT")` lookup, one `offload_repo.get_offload_metadata` PL/SQL call returning an Oracle UDT, and two separate `LOB.read()` round trips for the `OFFLOAD_HIGH_VALUE` and `OFFLOAD_PREDICATE_VALUE` CLOB attributes. Every repository read in `OracleOrchestrationRepoClient` also converts typed `msgspec.Struct` rows back into untyped `dict` objects via `msgspec.structs.asdict`.

This chapter replaces `OrchestrationMetadata` and `OffloadMetadataSchema` with immutable `FrozenBaseStruct` models in `src/goe/persistence/models.py` and replaces `OrchestrationRepoClientInterface` and `OracleOrchestrationRepoClient` with `OracleRepositoryService` in `src/goe/persistence/oracle/oracle_repository.py`.

Goals:

1. Define `OffloadMetadata(FrozenBaseStruct)`, `RepoQuantityUnit`, `CommandExecutionRecord(FrozenBaseStruct)`, and `CommandStepRecord(FrozenBaseStruct)` in `src/goe/persistence/models.py` with `from_attributes`, `from_repo_row`, and `to_repo_binds` conversion methods.
2. Load offload metadata in a single network round trip by querying `/* slot: repo_user */.offload_metadata_v` with `fetch_lobs=False` so CLOB columns arrive inline as Python strings.
3. Cache `OFFLOAD_METADATA_OT`, `OFFLOAD_PARTITION_OT`, and `OFFLOAD_PARTITION_NTT` `DbObjectType` descriptors per physical connection so `set_offload_metadata` and `start_offload_chunk` avoid repeated `ALL_TYPE_ATTRS` dictionary round trips.
4. Execute `OFFLOAD_REPO` PL/SQL procedures and functions through `OracleDatabaseRegistry` sessions and `driver.call_proc` / cursor `callfunc` with lost-session retry.
5. Migrate orchestration, offload, schema sync, status report, and Listener callers to `OffloadMetadata` and `OracleRepositoryService`, retiring `orchestration_metadata.py`, `orchestration_repo_client.py`, and `oracle_orchestration_repo_client.py`.

### 2. Code Analysis Summary

- `src/goe/persistence/orchestration_metadata.py:24-95` defines upper-case dictionary keys (`HADOOP_OWNER`, `HADOOP_TABLE`, `OFFLOAD_TYPE`, `OFFLOADED_OWNER`, `OFFLOADED_TABLE`, `INCREMENTAL_KEY`, `INCREMENTAL_HIGH_VALUE`, `INCREMENTAL_RANGE`, `INCREMENTAL_PREDICATE_TYPE`, `INCREMENTAL_PREDICATE_VALUE`, `OFFLOAD_BUCKET_COLUMN`, `OFFLOAD_SORT_COLUMNS`, `OFFLOAD_SNAPSHOT`, `OFFLOAD_PARTITION_FUNCTIONS`, `COMMAND_EXECUTION`) and incremental predicate constants. `OrchestrationMetadata` (`:137-388`) wraps `self._metadata: dict`, Lazily instantiates a repo client via `build_client` (`:104-115`, `:385-388`), and exposes `decode_incremental_predicate_values` (`:241-251`), `hwm_column_names` (`:253-263`), `incremental_data_append_feature` (`:265-279`), `is_hwm_in_hybrid_view` (`:280-285`), `is_subpartition_offload` (`:286-289`), and `update_offloaded_attributes_for_join` (`:290-296`).
- `src/goe/persistence/schemas.py:11-210` defines duplicate and partially untyped `msgspec.Struct` classes (`StepDetailSchema`, `CommandExecutionSchema`, `OffloadMetadataSchema`, `ColumnDetail`, `PartitionDetail`, `SubPartitionDetail`, `OffloadableSchemaRow`, `SchemaTableRow`, `CommandExecutionRow`, `CommandExecutionStepRow`).
- `src/goe/persistence/oracle/oracle_orchestration_repo_client.py`:
  - `start_command` (`:98-127`), `end_command` (`:129-141`), `start_command_step` (`:143-164`), `end_command_step` (`:166-179`), `start_offload_chunk` (`:181-233`), and `end_offload_chunk` (`:235-263`) call `offload_repo.*` PL/SQL procedures through `self._frontend_api.execute_function(...)`.
  - `_get_metadata` (`:415-430`) and `_ora_object_to_metadata_dict` (`:471-496`) call `offload_repo.get_offload_metadata` returning `OFFLOAD_METADATA_OT` and invoke `.read()` on `OFFLOAD_HIGH_VALUE` (`:481`) and `OFFLOAD_PREDICATE_VALUE` (`:486`).
  - `_set_metadata` (`:521-537`) and `_metadata_dict_to_ora_object` (`:445-469`) populate `OFFLOAD_METADATA_OT` via `_get_ora_type_object` (`:438-440`), which calls `conn.gettype(...)` on every invocation.
  - `get_table_columns` (`:304-331`), `get_table_partitions` (`:333-349`), and `get_table_subpartitions` (`:351-366`) open unpooled `OracleFrontendApi` and `OffloadSourceTable.create(...)` instances that are never closed, leaking 1 to 3 Oracle sessions per Listener call.
- `src/goe/offload/offload_metadata_functions.py:56-180` (`gen_offload_metadata`, `gen_and_save_offload_metadata`) and `:277-295` (`decode_metadata_incremental_high_values_from_metadata`) construct and consume `OrchestrationMetadata`.

### 3. Requirements

Functional:

- **R1** `src/goe/persistence/models.py` defines `RepoQuantityUnit`, `OffloadMetadata(FrozenBaseStruct)`, `OffloadMetadataRow(FrozenBaseStruct)`, `CommandExecutionRecord(FrozenBaseStruct)`, and `CommandStepRecord(FrozenBaseStruct)`, plus the preserved module-level constants (`HADOOP_OWNER`, `HADOOP_TABLE`, `OFFLOAD_TYPE`, `OFFLOADED_OWNER`, `OFFLOADED_TABLE`, `INCREMENTAL_KEY`, `INCREMENTAL_HIGH_VALUE`, `INCREMENTAL_RANGE`, `INCREMENTAL_PREDICATE_TYPE`, `INCREMENTAL_PREDICATE_VALUE`, `OFFLOAD_BUCKET_COLUMN`, `OFFLOAD_SORT_COLUMNS`, `OFFLOAD_SNAPSHOT`, `OFFLOAD_PARTITION_FUNCTIONS`, `COMMAND_EXECUTION`, `INCREMENTAL_PREDICATE_TYPE_*`, `hwm_column_names_from_predicates`).
- **R2** `OffloadMetadata` provides `from_attributes(**kwargs)`, `from_legacy_dict(mapping)`, `from_repo_row(row)`, `to_repo_binds()`, `as_dict()`, `with_updates(**changes)`, `with_join_target(offloaded_owner, offloaded_table)`, `decode_incremental_predicate_values(as_dsl=False)`, `hwm_column_names()`, `incremental_data_append_feature()`, `is_hwm_in_hybrid_view()`, and `is_subpartition_offload()`.
- **R3** `src/goe/persistence/sql/oracle_repo.sql` adds the `get_offload_metadata` and `list_offload_metadata_by_owner` named queries against `/* slot: repo_user */.offload_metadata_v`.
- **R4** `src/goe/persistence/oracle/oracle_repository.py` implements `OracleRepositoryService` backed by `OracleDatabaseRegistry`, loading `OffloadMetadata` in one round trip via `get_offload_metadata` (`fetch_lobs=False`), caching `DbObjectType` handles in a `weakref.WeakKeyDictionary` per physical connection for `set_offload_metadata` and `start_offload_chunk`, and executing `OFFLOAD_REPO` procedures (`start_command`, `end_command`, `start_command_step`, `end_command_step`, `start_offload_chunk`, `end_offload_chunk`, `drop_offload_metadata`) through `driver.call_proc` / cursor calls with `run_with_session_retry`.
- **R5** `src/goe/persistence/orchestration_metadata.py`, `src/goe/persistence/orchestration_repo_client.py`, and `src/goe/persistence/oracle/oracle_orchestration_repo_client.py` are retired, and callers across `offload`, `orchestration`, `schema_sync`, `report`, and `listener` use `OffloadMetadata` and `OracleRepositoryService` registered in `src/goe/offload/registry.py`.

Non-functional:

- **R6** `OffloadMetadata`, `CommandExecutionRecord`, and `CommandStepRecord` are frozen `msgspec` structs (`frozen=True, gc=False` via `FrozenBaseStruct`) with zero active-record database client state.
- **R7** All JSON serialization in `models.py` and `oracle_repository.py` routes through `goe.util.serializers` (`encode_json`, `decode_json`).

Risks and mitigations:

- Call sites that previously mutated `metadata.offload_type = ...` or `metadata.incremental_high_value = ...` in place: `OffloadMetadata.with_updates(**changes)` (wrapping `msgspec.structs.replace`) returns a new frozen instance cleanly.
- Call sites that index metadata as a legacy upper-case dict (`metadata[HADOOP_OWNER]` or `metadata.as_dict()`): `OffloadMetadata.as_dict()` and `OffloadMetadata.from_legacy_dict(...)` preserve exact upper-case key mapping where required by legacy tests or reports.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| --- | --- | --- |
| R1, R2, R6, R7 | 1.1 | `tests/unit/persistence/test_models.py` |
| R3, R4, R7 | 1.2 | `tests/unit/persistence/test_oracle_repository.py` |
| R5 | 1.3 | `tests/unit/offload/test_offload_metadata.py`; `tests/unit/listener/test_system_service.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/persistence/test_models.py tests/unit/persistence/test_oracle_repository.py tests/unit/offload/test_offload_metadata.py tests/unit/listener/test_system_service.py -q
uv run pytest tests/unit -q
uv run ruff format --check src/goe tests/unit
uv run ruff check src/goe tests/unit
uv run mypy src/goe
uv run python tools/verify_architecture.py
make test-integration-oracle
```

## Implementation Plan

### Phase 1: Frozen Persistence Models and Repository Service

- [ ] 1.1 Add frozen OffloadMetadata and execution record models in src/goe/persistence/models.py ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement OracleRepositoryService and 1-RTT offload_metadata_v queries ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: Caller Migration

- [ ] 1.3 Migrate orchestration, offload, sync, report, and Listener callers to OffloadMetadata and OracleRepositoryService ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `offload_metadata_and_repository_service_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `OffloadMetadata` is a pure value object (`FrozenBaseStruct`) with no embedded repository client; `OracleRepositoryService` uses `OracleDatabaseRegistry` admin sessions with `fetch_lobs=False` to read `offload_metadata_v` in 1 round trip and caches `DbObjectType` objects per connection in a `WeakKeyDictionary`.
- **Discoveries**: none yet.
- **Blockers**: Chapter 6.1 (`oracle_database_registry_and_session_tracing_20261024`) must complete first.
- **Next exact step**: execute task `1.1` (`offload_metadata_and_repository_service_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/frontends/oracle.md`, `.agents/bundles/knowledge/standards/database-and-sql.md`, `.agents/bundles/knowledge/operations/database-installation.md`.
