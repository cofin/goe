---
type: Spec
flow_id: offload_plan_resolution_and_stateless_executor_20261024
title: "Chapter 10.3: OffloadPlan Resolution and Stateless Executor"
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
description: "Implement SchemaAndTransportPlanningStage, OffloadPlanExecutor, and OffloadPipeline while retiring the mutable OffloadOperation and procedural execution.py monoliths."
tags: [refactor, orchestration, offload, executor, pipeline]
parent_prd: prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024
depends_on:
  - offload_plan_discovery_and_boundary_stages_20261024
research:
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
---

# Chapter 10.3: OffloadPlan Resolution and Stateless Executor

## Specification

### 1. Overview and Goals

At HEAD `d6a02fe`, `src/goe/orchestration/operation.py` (1,735 LOC) and `src/goe/orchestration/execution.py` (677 LOC) interleave option normalization, data type sampling, target table DDL creation, transport staging, backend ingestion, verification, and metadata persistence inside mutable `OffloadOperation` state and procedural functions (`offload_table`, `run_offload`, `verify_offload_by_backend_count`, `verify_offload_by_agg`).

Building on the immutable models, `SourceDiscoveryStage`, and `BoundaryResolutionStage` delivered in Chapter 10.2, this chapter completes the staged offload architecture:

1. **Schema and Transport Planning Stage (`src/goe/orchestration/stages/plan_resolution.py`)**: Implements `SchemaAndTransportPlanningStage` to compute `SchemaEvolutionPlan`, `StagingTransportPlan`, `BackendLoadPlan`, and `planned_metadata` (`OffloadMetadata`) into a complete immutable `OffloadPlan(FrozenBaseStruct)` before any DDL or transport side effects execute.
2. **Stateless Plan Executor (`src/goe/orchestration/stages/executor.py`)**: Implements `OffloadPlanExecutor` to acquire `FileOrchestrationLock` (`OrchestrationLockInterface`), execute target DDL (`STEP_CREATE_TABLE`), run chunked transport staging (`STEP_STAGING_TRANSPORT`), execute `BackendIngestStrategy` (`STEP_FINAL_LOAD`), run `CrossDbValidator` / `BackendCountValidator` verification (`STEP_VERIFY_EXPORTED_DATA`), and persist `OffloadMetadata` via `OracleRepositoryService` (`STEP_SAVE_METADATA`), returning an immutable `OffloadExecutionReport`.
3. **End-to-End Offload Pipeline (`src/goe/orchestration/pipeline.py`)**: Replaces `src/goe/orchestration/operation.py` and `src/goe/orchestration/execution.py` with `OffloadPipeline` orchestrating `SourceDiscoveryStage -> BoundaryResolutionStage -> SchemaAndTransportPlanningStage -> OffloadPlanExecutor`, supporting side-effect-free `--dry-run` (`execute=False`) and MCP `plan_offload_dry_run` inspection while keeping `tests/unit/characterization/test_offload_bigquery_golden.py` and `tests/unit/orchestration/test_goe_orchestration_characterization.py` 100% green.

### 2. Code Analysis Summary

Line references reflect HEAD `d6a02fe`. Earlier PRDs provide `OffloadOperationOptions` (`src/goe/config/option_registry.py`), `ColumnDialectMapper` (`src/goe/offload/schema/`), `CanonicalTypeRegistry` and `BackendIngestStrategy` (`src/goe/backend/`), `DuckDBTransportEngine` and `TransportPlanner` (`src/goe/transport/`), `CrossDbValidator` (`src/goe/offload/validation/`), and `OracleRepositoryService` (`src/goe/persistence/oracle_repo_service.py`).

- `src/goe/orchestration/operation.py:488-1735` defines `BaseOperation` and `OffloadOperation`, mixing CLI option normalization (`:690-1160`) with database connections (`validate_sort_columns` at `:1163-1208`, `set_Bucket_from_backend_table` at `:1295-1340`) and mutable runtime properties (`inflight_offload_predicate`, `synthetic_partition_digits`, `offload_type`).
- `src/goe/orchestration/execution.py:82-370` implements `incremental_offload_partition_overrides`, `verify_offload_by_backend_count`, `verify_offload_by_agg`, and `run_offload`; `:375-677` implements `offload_table`.
- `src/goe/offload/offload.py:1-510` contains procedural step helpers (`create_final_backend_table_step`, `drop_backend_table_step`, `create_ddl_file_step`, `get_offload_data_manager`, `offload_backend_db_message`) called by `execution.py`.
- `src/goe/goe.py:1-60` is a legacy facade re-exporting symbols from `src/goe/orchestration/{constants,logging_init,operation,execution}.py`.
- `src/goe/orchestration/orchestration_lock.py:1-95` defines `OrchestrationLockInterface`, `FileLockOrchestrationLock`, and `orchestration_lock_for_table`.

### 3. Requirements

- **R1**: Implement `SchemaAndTransportPlanningStage` in `src/goe/orchestration/stages/plan_resolution.py` to resolve canonical column mappings (`STEP_ANALYZE_DATA_TYPES`), synthetic partition overrides (`incremental_offload_partition_overrides`), target table DDL (`SchemaEvolutionPlan`), transport method and chunk slicing (`StagingTransportPlan`), backend ingestion strategy (`BackendLoadPlan`), and target `OffloadMetadata` into a complete `OffloadPlan` without executing target DDL or transport I/O.
- **R2**: Implement `OffloadPlanExecutor` in `src/goe/orchestration/stages/executor.py` to execute an `OffloadPlan` deterministically under `OrchestrationLockInterface`, emitting exact `command_steps` (`STEP_CREATE_TABLE`, `STEP_STAGING_SETUP`, `STEP_STAGING_TRANSPORT`, `STEP_VALIDATE_DATA`, `STEP_VALIDATE_CASTS`, `STEP_FINAL_LOAD`, `STEP_STAGING_CLEANUP`, `STEP_SAVE_METADATA`, `STEP_VERIFY_EXPORTED_DATA`) through `ExecutionContext` and returning `OffloadExecutionReport`. When `plan.execute` is `False`, `OffloadPlanExecutor` performs dry-run rendering without mutating backend tables, staging storage, or repository metadata.
- **R3**: Implement `OffloadPipeline` in `src/goe/orchestration/pipeline.py` chaining `SourceDiscoveryStage -> BoundaryResolutionStage -> SchemaAndTransportPlanningStage -> OffloadPlanExecutor`, wire `src/goe/offload/offload.py`, `src/goe/goe.py`, and `src/goe/cli/commands/offload.py` to `OffloadPipeline`, and delete `src/goe/orchestration/operation.py` and `src/goe/orchestration/execution.py`.
- **R4**: Keep `tests/unit/characterization/test_offload_bigquery_golden.py` and `tests/unit/orchestration/test_goe_orchestration_characterization.py` 100% green.
- **Non-functional**: Zero inline `#` comments, top-level imports only, public symbols before private `_` helpers, and full compliance with `ruff`, `mypy src/goe`, and `tools/verify_architecture.py`.
- **Risks and mitigations**: Golden characterization tests assert exact step order and console messages. Mitigated by preserving `command_steps` step constants and message text inside `SchemaAndTransportPlanningStage` and `OffloadPlanExecutor`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/orchestration/stages/test_plan_resolution.py` |
| R2 | 1.2 | `tests/unit/orchestration/stages/test_executor.py` |
| R3 | 1.3 | `tests/unit/orchestration/test_pipeline.py` |
| R4 | 1.3 | `tests/unit/characterization/test_offload_bigquery_golden.py`, `tests/unit/orchestration/test_goe_orchestration_characterization.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/orchestration/stages/test_plan_resolution.py tests/unit/orchestration/stages/test_executor.py tests/unit/orchestration/test_pipeline.py -v
uv run pytest tests/unit/characterization/test_offload_bigquery_golden.py tests/unit/orchestration/test_goe_orchestration_characterization.py -v
uv run pytest tests/unit/orchestration tests/unit/offload -q
uv run ruff format --check src/goe tests/unit
uv run ruff check src/goe tests/unit
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Plan Resolution, Stateless Executor, and Pipeline Replacement

- [ ] 1.1 Implement `SchemaAndTransportPlanningStage` in `src/goe/orchestration/stages/plan_resolution.py` ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement `OffloadPlanExecutor` in `src/goe/orchestration/stages/executor.py` ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Replace `operation.py` and `execution.py` with `OffloadPipeline` and verify golden characterization suites ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `offload_plan_resolution_and_stateless_executor_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `SchemaAndTransportPlanningStage` constructs the complete `OffloadPlan(FrozenBaseStruct)` before any target DDL or staging side effects occur; `OffloadPlanExecutor` is stateless and acquires `OrchestrationLockInterface` around plan execution; `operation.py` and `execution.py` are retired in Task 1.3.
- **Discoveries**: none yet.
- **Blockers**: Chapter 10.2 (`offload_plan_discovery_and_boundary_stages_20261024`) must complete first.
- **Next exact step**: execute task `1.1` (`offload_plan_resolution_and_stateless_executor_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/architecture/orchestration.md`, `.agents/bundles/knowledge/architecture/offload-lifecycle.md`, `.agents/bundles/knowledge/workflow.md`.
