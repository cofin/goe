---
type: Spec
flow_id: listener_and_persistence_schema_alignment_20261004
title: Listener REST & Persistence Schema Alignment
description: Align Listener OffloadOptions, ListenerConfig, SystemController.get_table_partitions, Persistence ColumnDetail/SubPartitionDetail, and serialization.py with main (ab4f0f9)
parent_prd: v2_main_alignment_remediation_20261004
state: completed
plan_revision: 1
plan_commit: null
state_revision: 5
current_task: null
last_operation: 20261004T182730Z-flow-completion-complete-c3-and-prd-00
operation_targets:
  - spec.md
last_verified_checkpoint: 3908785afe6181297d8ca67a6adc269ae0480ab8
created_at: 2026-10-04T15:00:00Z
updated_at: 2026-10-04T18:27:30Z
tags:
  - spec
  - listener
  - persistence
  - msgspec
  - serialization
---

# Spec: Listener REST & Persistence Schema Alignment (`listener_and_persistence_schema_alignment_20261004`)

## 1. Objective & Scope

Restore 100% schema and controller contract parity between `main` (`ab4f0f9`), `origin/litestar`, `origin/msgspec`, and the current v2 Listener and Persistence layers:
1. **`OffloadOptions` & `OrchestrationController.execute_offload_command` (`Finding LIS-1`)**:
   - `OffloadOperation.from_dict` (`src/goe/goe.py:2061-2070`) asserts `all(k in EXPECTED_OFFLOAD_ARGS for k in operation_dict)`.
   - Current `OffloadOptions` (`src/goe/listener/schemas.py:156-189`) defines non-canonical field names (`target_table_name`, `partitions`, `bucket_hash_column`, `sort_columns`, `partition_functions`, etc.) and defaults `quiet: bool = False` and `verbose: bool = False`, which are not in `EXPECTED_OFFLOAD_ARGS` (`src/goe/goe.py:154-240`), causing `OffloadOperation.from_dict(params, ...)` to fail with `AssertionError: Unexpected OffloadOperation keys`.
   - Align `OffloadOptions` with the canonical `EXPECTED_OFFLOAD_ARGS` fields from `main:src/goe/listener/schemas/orchestration.py` and `src/goe/goe.py:154-240`, provide `to_params_dict(self) -> dict[str, Any]` that normalizes any legacy/alias fields (`target_table_name` -> `target_owner_name`, `partitions` -> `partition_names_csv`, `bucket_hash_column` -> `bucket_hash_col`, `sort_columns` -> `sort_columns_csv`, `partition_functions` -> `offload_partition_functions`, etc.) and filters to valid `EXPECTED_OFFLOAD_ARGS` keys, and call `data.to_params_dict()` in `OrchestrationController.execute_offload_command` (`src/goe/listener/controllers/orchestration.py:108`).
2. **`ListenerConfig` & `ColumnDetail` Schema Completeness (`Finding LIS-3`, `Finding CORE-3`)**:
   - Add optional `offload_options: dict[str, Any] | str | None = None`, `present_options: Any = None`, and `prepare_options: Any = None` to `ListenerConfig` (`src/goe/listener/schemas.py:40-50`).
   - Add `data_precision: int | None = None` to `ColumnDetail` in both `src/goe/listener/schemas.py:83-92` and `src/goe/persistence/schemas.py:68-77`, and pass both `data_precision=one_col.data_precision, data_scale=one_col.data_scale` in `OracleOrchestrationRepoClient.get_table_columns` (`src/goe/persistence/oracle/oracle_orchestration_repo_client.py:883-890`).
3. **`SystemController.get_table_partitions` & `SubPartitionDetail` Struct Compatibility (`Finding LIS-2`)**:
   - Add `partition_name: str = ""` and `partition_position: int = 0` to `SubPartitionDetail` (`src/goe/persistence/schemas.py:104-125`) matching `main:src/goe/listener/schemas/system.py:89-99`.
   - Normalize `subpartitions` items in `SystemController.get_table_partitions` (`src/goe/listener/controllers/system.py:77-90`) so both `SubPartitionDetail` (`msgspec.Struct`) instances and `dict`s are converted to `dict` before grouping by `"partition_name"`.
4. **`src/goe/util/serialization.py` Domain Fallback Hook (`Finding CORE-2`)**:
   - Delegate `serialize_object` and `serialize_object_bytes` in `src/goe/util/serialization.py` to `goe.util.json_tools` (which includes the `msgspec.json.Encoder(enc_hook=_default)` fallback for `ExecutionId` and `GenericPredicate`).

---

## 2. Requirements & Acceptance Criteria

- **REQ-C3-01**: `OffloadOptions` (`src/goe/listener/schemas.py`) must expose all canonical `EXPECTED_OFFLOAD_ARGS` fields and implement `to_params_dict()` that normalizes alias fields and emits only valid `EXPECTED_OFFLOAD_ARGS` keys; `OrchestrationController.execute_offload_command` must use `data.to_params_dict()`.
- **REQ-C3-02**: `ListenerConfig` (`src/goe/listener/schemas.py`) must include `offload_options: dict[str, Any] | str | None = None`, `present_options: Any = None`, and `prepare_options: Any = None`.
- **REQ-C3-03**: `ColumnDetail` (`src/goe/listener/schemas.py` and `src/goe/persistence/schemas.py`) must include `data_precision: int | None = None`, and `OracleOrchestrationRepoClient.get_table_columns` must populate both `data_precision` and `data_scale`.
- **REQ-C3-04**: `SubPartitionDetail` (`src/goe/persistence/schemas.py`) must include `partition_name: str = ""` and `partition_position: int = 0`, and `SystemController.get_table_partitions` (`src/goe/listener/controllers/system.py`) must group `SubPartitionDetail` structs and `dict`s without raising `AttributeError`.
- **REQ-C3-05**: `src/goe/util/serialization.py` must serialize GOE domain objects (`ExecutionId`, objects with `.dsl`) identically to `src/goe/util/json_tools.py`.

---

## Implementation Plan

### Phase 1: Listener & Persistence Schema Alignment [checkpoint: 3908785afe6181297d8ca67a6adc269ae0480ab8]

- [x] Task T1.1: [Listener `OffloadOptions` & `ListenerConfig` Schema Alignment](tasks/T1.1.md) (`depends_on`: `[]`; `files`: `src/goe/listener/schemas.py`, `src/goe/listener/controllers/orchestration.py`; `tests`: `tests/unit/listener/test_offload_options_schema.py`) — `3dacccd8756a529ef88bc2e9993fff57c80bf12b`
- [x] Task T1.2: [`SystemController.get_table_partitions`, Persistence Schemas, and `serialization.py` Parity](tasks/T1.2.md) (`depends_on`: `["listener_and_persistence_schema_alignment_20261004:T1.1"]`; `files`: `src/goe/listener/controllers/system.py`, `src/goe/persistence/schemas.py`, `src/goe/persistence/oracle/oracle_orchestration_repo_client.py`, `src/goe/util/serialization.py`; `tests`: `tests/unit/listener/test_asgi.py`, `tests/unit/persistence/test_schemas.py`, `tests/unit/util/test_json_tools.py`) — `3908785afe6181297d8ca67a6adc269ae0480ab8`

---

## 4. Requirement-to-Task & Test Traceability Matrix

| Requirement ID | Description | Task ID | Target Source Files | Verification Test Files |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-C3-01** | `OffloadOptions` canonical fields, `to_params_dict()`, and `OrchestrationController.execute_offload_command` integration | `T1.1` | `src/goe/listener/schemas.py`, `src/goe/listener/controllers/orchestration.py` | `tests/unit/listener/test_offload_options_schema.py` |
| **REQ-C3-02** | `ListenerConfig` optional `offload_options`, `present_options`, `prepare_options` fields | `T1.1` | `src/goe/listener/schemas.py` | `tests/unit/listener/test_offload_options_schema.py` |
| **REQ-C3-03** | `ColumnDetail` `data_precision` field in Listener and Persistence schemas and `OracleOrchestrationRepoClient` | `T1.1`, `T1.2` | `src/goe/listener/schemas.py`, `src/goe/persistence/schemas.py`, `src/goe/persistence/oracle/oracle_orchestration_repo_client.py` | `tests/unit/persistence/test_schemas.py` |
| **REQ-C3-04** | `SubPartitionDetail` `partition_name`/`partition_position` and `SystemController.get_table_partitions` struct normalization | `T1.2` | `src/goe/persistence/schemas.py`, `src/goe/listener/controllers/system.py` | `tests/unit/listener/test_asgi.py`, `tests/unit/persistence/test_schemas.py` |
| **REQ-C3-05** | `src/goe/util/serialization.py` fallback encoder parity with `json_tools.py` | `T1.2` | `src/goe/util/serialization.py` | `tests/unit/util/test_json_tools.py` |

---

## Continuity Snapshot

- **Active Flow**: `listener_and_persistence_schema_alignment_20261004`
- **Lifecycle State**: `completed`
- **Current Task**: `null`
- **Claimant**: `null`
- **Last Verified Checkpoint**: `3908785afe6181297d8ca67a6adc269ae0480ab8`
- **Decisions**: Align `OffloadOptions` with `EXPECTED_OFFLOAD_ARGS` without importing `goe.goe` in `src/goe/listener/schemas.py` (avoiding circular import through `goe.offload.offload_messages`); add `data_precision` to `ColumnDetail`; add `partition_name` and `partition_position` to `SubPartitionDetail` and normalize struct instances in `get_table_partitions`; delegate `serialization.py` to `json_tools.py`.
- **Recent Discoveries**: Completed `code-reviewer` and `quality-reviewer` passes with 0 findings on `ff03d608c422bac2096653922512523bc9b83fcc..3908785afe6181297d8ca67a6adc269ae0480ab8`.
- **Blockers & Unblock Conditions**: None
- **Next Exact Step**: None — Flow and parent PRD `v2_main_alignment_remediation_20261004` completed
- **Plan Identity**: `plan_revision: 1`, `plan_commit: null`
- **State Identity**: `revision: 5`, `last_operation: 20261004T182730Z-flow-completion-complete-c3-and-prd-00`, `operation_targets: ["spec.md"]`
- **Relevant Knowledge Paths**: `.agents/bundles/knowledge/listener/rest-api.md`, `.agents/bundles/knowledge/patterns/serialization-and-utils.md`



