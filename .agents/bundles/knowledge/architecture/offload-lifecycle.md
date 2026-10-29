---
type: Architecture
title: Offload Execution Lifecycle
description: Detailed operational phases of the data offloading algorithm from pre-flight checks to verification
tags:
  - architecture
  - offload
  - lifecycle
  - phases
  - data-flow
---

# Offload Execution Lifecycle

Data offloading in GOE executes through a stateless 4-stage pipeline (`OffloadPipeline` in `src/goe/orchestration/pipeline.py` and `src/goe/orchestration/stages/{discovery,boundary,plan_resolution,executor}.py`).

```
Stage 1: DiscoveryStage (`src/goe/orchestration/stages/discovery.py`) -> DiscoveryResult
    │
Stage 2: BoundaryStage (`src/goe/orchestration/stages/boundary.py`) -> BoundaryResult (STEP_FIND_OFFLOAD_DATA)
    │
Stage 3: PlanResolutionStage (`src/goe/orchestration/stages/plan_resolution.py`) -> OffloadPlan (STEP_ANALYZE_DATA_TYPES)
    │
Stage 4: OffloadPlanExecutor (`src/goe/orchestration/stages/executor.py`) -> OffloadExecutionResult
    ├── Target Table Lifecycle & DDL Execution (STEP_CREATE_TABLE)
    ├── Staging Setup & Data Transport (STEP_STAGING_SETUP, STEP_STAGING_TRANSPORT)
    ├── Staging Validation, Type Casting & Final Load (STEP_VALIDATE_DATA, STEP_VALIDATE_CASTS, STEP_FINAL_LOAD, STEP_STAGING_CLEANUP)
    └── Metadata Persistence & Verification (STEP_SAVE_METADATA, STEP_VERIFY_EXPORTED_DATA)
```

## Detailed Phase Walkthrough

### Stage 1: Discovery & Pre-Execution Validation (`DiscoveryStage`)
1. **Component Version Verification**: Compares the Oracle PL/SQL package version (`OFFLOAD.VERSION`) against the local binary build hash.
2. **Identifier Safety & Data Type Compatibility**: Validates database, schema, and table names against target platform limits and pre-scans source columns into an immutable `DiscoveryResult(FrozenBaseStruct)`.

### Stage 2: Partition Boundary Calculation (`BoundaryStage`, `STEP_FIND_OFFLOAD_DATA`)
Implemented in `src/goe/orchestration/stages/boundary.py`:
- **IPA `RANGE` (`RANGE_HIGH_VALUE`)**: Queries `ALL_TAB_PARTITIONS`, decodes partition high values, resolves the high-water mark (`OffloadBoundaryRule`), and separates offloaded vs append partitions.
- **IPA `LIST` (`LIST_HIGH_VALUE`)**: Tracks offloaded list value sets and computes incremental partition chunks.
- **Predicate-Based Offload (`PBO`)**: Compiles `--offload-predicate` AST filters (`GenericPredicate`) and merges prior hybrid predicates without mutating source table instances.
- **Full-Table (`RBO`) & Chunking**: Computes `100:0` or `90:10` rules and splits large partition sets into bounded `PartitionChunkSpec` slices based on `--max-offload-chunk-size` or `--max-offload-chunk-count`, returning an immutable `BoundaryResult(FrozenBaseStruct)`.

### Phase 3: Canonical Type Transformation (`STEP_ANALYZE_DATA_TYPES`)
- Translates source columns to `CanonicalColumn` instances.
- Detects unconstrained types (`NUMBER(*,*)`) and executes data sampling (`sample_rdbms_data_types`) to determine actual precision/scale.
- Produces target-specific backend column definitions.

### Phase 4: Target Table Lifecycle (`STEP_CREATE_TABLE`)
- If target table does not exist: executes `CREATE TABLE` with configured partition schemes (e.g. `PARTITION BY DATE(col)`) and clustering keys.
- If `--reset-backend-table` is set: drops and recreates the target table.
- If target exists: verifies schema compatibility against prior offload metadata.

### Phase 5: Staging Setup & Transport (`STEP_STAGING_TRANSPORT`)
1. **Snapshot SCN Capture**: Captures Flashback SCN on Oracle via `SELECT CURRENT_SCN FROM V$DATABASE`.
2. **Staging Preparation**: Prepares cloud storage staging location (`OFFLOAD_FS_CONTAINER/OFFLOAD_FS_PREFIX/...`).
3. **Distributed Transport**: Launches PySpark job on Dataproc / Livy with `GOETaskListener` to extract JDBC slices in parallel (using `MOD` hash, `ID_RANGE`, or native partition slicing) and writes Avro/Parquet chunks to staging.

### Phase 6: Validation, Casting & Final Load (`STEP_FINAL_LOAD`)
1. **Staging Validation (`STEP_VALIDATE_DATA`)**: Compares extracted row counts against source RDBMS expectations.
2. **Type Casting Validation (`STEP_VALIDATE_CASTS`)**: Executes safe cast checks (`SAFE_CAST` / `TRY_CAST`) to guarantee no runtime data truncation.
3. **Final Load (`STEP_FINAL_LOAD`)**: Executes backend native ingestion (`INSERT INTO target SELECT ... FROM staging` or `COPY INTO`).
4. **Staging Cleanup (`STEP_STAGING_CLEANUP`)**: Purges temporary staging files from cloud storage.

### Phase 7: Metadata Persistence & Verification
1. **Metadata Save (`STEP_SAVE_METADATA`)**: Persists updated HWM, partition bounds, sort columns, SCN snapshot, and execution ID to `GOE_REPO`.
2. **Verification (`STEP_VERIFY_EXPORTED_DATA`)**:
   - `minus` mode: Compares source vs target row counts for the offloaded slice.
   - `aggregate` mode: Executes deep aggregation checksums (`COUNT`, `SUM`, `MIN`, `MAX`) across source and target columns.
