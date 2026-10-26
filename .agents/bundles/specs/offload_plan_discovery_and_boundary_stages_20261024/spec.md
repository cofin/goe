---
type: Spec
flow_id: offload_plan_discovery_and_boundary_stages_20261024
title: "Chapter 10.2: OffloadPlan Discovery and Boundary Stages"
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
description: "Define immutable OffloadPlan value objects and implement pure SourceDiscoveryStage and BoundaryResolutionStage while retiring the mutable OffloadSourceData hierarchy."
tags: [refactor, orchestration, offload, ipa, planning]
parent_prd: prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024
depends_on:
  - execution_context_and_concurrency_safety_20261024
research:
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
---

# Chapter 10.2: OffloadPlan Discovery and Boundary Stages

## Specification

### 1. Overview and Goals

Offload planning currently interleaves frontend catalog queries, high-value watermark decoding, predicate AST parsing, and in-place mutations on `OffloadOperation` (`src/goe/orchestration/operation.py`) and `OffloadSourceDataInterface` subclasses (`src/goe/offload/source_data/`). This coupling prevents side-effect-free dry-run inspection, complicates unit testing of Incremental Partition Append (`IPA`) boundary rules, and mutates source table instances during planning.

This chapter establishes the immutable data model for staged offload planning and implements the first two pure planning stages:

1. **Orchestration Plan Models (`src/goe/orchestration/models.py`)**: Defines `SourcePartitionSlice`, `DiscoveryState`, `PriorMetadataState`, `PartitionBoundaryPlan`, `PredicatePlan`, `SchemaEvolutionPlan`, `StagingTransportPlan`, `BackendLoadPlan`, `OffloadPlan`, and `OffloadExecutionReport` as `FrozenBaseStruct` value objects (`frozen=True, gc=False`), with `SourcePartitionSlice` additionally using `array_like=True` for compact partition-slice tuples.
2. **Source Discovery Stage (`src/goe/orchestration/stages/discovery.py`)**: Implements `SourceDiscoveryStage` to hydrate the frontend `OracleTableSnapshot` (or MSSQL frontend table metadata), verify table eligibility, capture a snapshot-consistent Oracle SCN (`CURRENT_SCN`), and load prior `OffloadMetadata` and backend table state into an immutable `DiscoveryState` and `PriorMetadataState`.
3. **Boundary Resolution Stage (`src/goe/orchestration/stages/boundary.py`)**: Implements `BoundaryResolutionStage` to resolve `FULL`, `INCREMENTAL` (`100/0`, `90/10`, `100/10`), `RANGE`, `LIST`, `LIST_AS_RANGE`, composite `SUBPARTITION`, and predicate-based (`PBO`) offload boundaries (`--older-than-date`, `--older-than-days`, `--less-than-value`, `--equal-to-values`, `--offload-predicate`) into `PartitionBoundaryPlan` and `PredicatePlan` via `PredicateCompiler` without mutating source table instances, retiring `src/goe/offload/offload_source_data.py` and `src/goe/offload/source_data/` (2,272 LOC).

### 2. Code Analysis Summary

Line references reflect HEAD `d6a02fe`. Earlier PRDs (PRDs 5–9 and Chapter 10.1) provide `FrozenBaseStruct` (`src/goe/typing.py`), `ExecutionContext` (`src/goe/orchestration/context.py`), `OracleTableCatalogSnapshot` and `OffloadMetadata` (`src/goe/persistence/models.py` and `src/goe/frontend/oracle/`), and `PredicateCompiler` (`src/goe/offload/sql_ast/predicate_compiler.py`).

- `src/goe/offload/offload_source_data.py:1-47` is a definition-free facade re-exporting symbols from `src/goe/offload/source_data/{base,factory,ipa_range}.py`.
- `src/goe/offload/source_data/base.py:1-860` defines `OffloadSourceDataInterface`, `OffloadSourcePartition`, `OffloadSourcePartitions`, `get_offload_type_for_config`, and `is_default_partition`, holding mutable state across `find_offload_partitions()`, `get_offload_Partitions_to_process()`, and `offload_by_subpartition_capable()`.
- `src/goe/offload/source_data/factory.py:26-163` (`offload_source_data_factory`) branches on `offload_operation.offload_predicate`, `offload_operation.ipa_predicate_type`, and `offload_source_table.partition_type` (`RANGE`, `LIST`, non-partitioned, or unsupported partition data types) to instantiate `OffloadSourceDataPredicate`, `OffloadSourceDataFull`, `OffloadSourceDataFullPartitioned`, `OffloadSourceDataIpaRange`, `OffloadSourceDataIpaListAsRange`, or `OffloadSourceDataIpaList`.
- `src/goe/offload/source_data/ipa_range.py:1-585`, `src/goe/offload/source_data/ipa_list.py:1-342`, `src/goe/offload/source_data/predicate.py:1-220`, and `src/goe/offload/source_data/full.py:1-102` implement partition watermark comparison, `HIGH_VALUE` literal comparison, chunk slicing by `--max-offload-chunk-size` and `--max-offload-chunk-count`, and predicate compilation while mutating `offload_operation.inflight_offload_predicate`, `offload_operation.offload_type`, and `offload_source_table` attributes.
- `src/goe/orchestration/execution.py:375-470` (`offload_table`) and `src/goe/offload/offload.py:210-390` (`get_offload_data_manager`, `get_prior_offloaded_hv`, `get_current_offload_hv`, `offload_type_force_effects`) coordinate prior metadata lookup, SCN capture, and boundary calculation during procedural execution.

### 3. Requirements

- **R1**: Define all staged orchestration value objects (`SourcePartitionSlice`, `DiscoveryState`, `PriorMetadataState`, `PartitionBoundaryPlan`, `PredicatePlan`, `SchemaEvolutionPlan`, `StagingTransportPlan`, `BackendLoadPlan`, `OffloadPlan`, `OffloadExecutionReport`) in `src/goe/orchestration/models.py` inheriting from `FrozenBaseStruct` (`frozen=True, gc=False`), with `SourcePartitionSlice` configured with `array_like=True, frozen=True, gc=False` and round-tripping cleanly through `goe.util.serializers`.
- **R2**: Implement `SourceDiscoveryStage` in `src/goe/orchestration/stages/discovery.py` to query the frontend table snapshot, validate table structure and offload eligibility, capture a consistent snapshot SCN when supported, fetch prior `OffloadMetadata` from `OracleRepositoryService`, and return `(DiscoveryState, PriorMetadataState)` without mutating input options or table snapshots.
- **R3**: Implement `BoundaryResolutionStage` in `src/goe/orchestration/stages/boundary.py` preserving all IPA rules (`100/0`, `90/10`, `100/10`, `RANGE`, `LIST`, `LIST_AS_RANGE`, composite `SUBPARTITION`, `PBO`, `--older-than-date`, `--older-than-days`, `--less-than-value`, `--equal-to-values`, `--offload-predicate`, `--reset-backend-table`, `--reset-hybrid-view`, `--max-offload-chunk-size`, `--max-offload-chunk-count`) and returning `(PartitionBoundaryPlan, PredicatePlan)` without mutating source table instances.
- **R4**: Retire `src/goe/offload/offload_source_data.py` and `src/goe/offload/source_data/{__init__,base,predicate,full,ipa_range,ipa_list,factory}.py` in the same task that lands `BoundaryResolutionStage`, updating internal callers to import from `goe.orchestration.models` and `goe.orchestration.stages.boundary`.
- **Non-functional**: Zero inline `#` comments, top-level imports only, public symbols defined before private `_` helpers, and full `mypy src/goe` and `tools/verify_architecture.py` compliance.
- **Risks and mitigations**: Subtle boundary off-by-one regressions in Oracle `RANGE` non-inclusive upper bounds (`< HIGH_VALUE`) vs `LIST` inclusive tuple sets (`IN (...)`). Mitigated by comprehensive parameterized unit tests covering every IPA transition (`100/0 -> 90/10 -> 100/10`), default/MAXVALUE partition rejection, and partition chunk grouping.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/orchestration/test_models.py` |
| R2 | 1.2 | `tests/unit/orchestration/stages/test_discovery.py` |
| R3 | 1.3 | `tests/unit/orchestration/stages/test_boundary.py` |
| R4 | 1.3 | `tests/unit/orchestration/stages/test_boundary.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/orchestration/test_models.py tests/unit/orchestration/stages/test_discovery.py tests/unit/orchestration/stages/test_boundary.py -v
uv run pytest tests/unit/characterization -q
uv run ruff format --check src/goe/orchestration tests/unit/orchestration
uv run ruff check src/goe/orchestration tests/unit/orchestration
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Staged Models, Discovery, and Boundary Resolution

- [ ] 1.1 Define immutable OffloadPlan and stage value objects in `src/goe/orchestration/models.py` ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement `SourceDiscoveryStage` in `src/goe/orchestration/stages/discovery.py` ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Implement `BoundaryResolutionStage` in `src/goe/orchestration/stages/boundary.py` and retire `offload_source_data` ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `offload_plan_discovery_and_boundary_stages_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: All stage outputs are immutable `FrozenBaseStruct` structs in `src/goe/orchestration/models.py`; `SourcePartitionSlice` uses `array_like=True, frozen=True, gc=False` for minimal memory overhead on tables with tens of thousands of partitions; `BoundaryResolutionStage` replaces the `OffloadSourceDataInterface` class hierarchy completely.
- **Discoveries**: none yet.
- **Blockers**: Chapter 10.1 (`execution_context_and_concurrency_safety_20261024`) must complete first.
- **Next exact step**: execute task `1.1` (`offload_plan_discovery_and_boundary_stages_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/architecture/orchestration.md`, `.agents/bundles/knowledge/architecture/offload-lifecycle.md`, `.agents/bundles/knowledge/workflow.md`.
