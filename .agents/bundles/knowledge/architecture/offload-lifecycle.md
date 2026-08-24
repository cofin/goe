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

Data offloading in GOE executes through a structured, multi-phase lifecycle implemented in `src/goe/goe.py`.

```
Phase 1: Pre-Execution Validation & Target Resolution
    │
Phase 2: Partition Discovery & Scope Analysis (STEP_FIND_OFFLOAD_DATA)
    │
Phase 3: Canonical Type Transformation (STEP_ANALYZE_DATA_TYPES)
    │
Phase 4: Target Table Lifecycle & DDL Execution (STEP_CREATE_TABLE)
    │
Phase 5: Staging Setup & Data Transport (STEP_STAGING_TRANSPORT)
    │
Phase 6: Staging Validation, Type Casting & Final Load (STEP_FINAL_LOAD)
    │
Phase 7: Metadata Persistence & Verification (STEP_SAVE_METADATA & VERIFY)
```

## Detailed Phase Walkthrough

### Phase 1: Pre-Execution Validation & Target Resolution
1. **Component Version Verification**: Compares the Oracle PL/SQL package version (`OFFLOAD.VERSION`) against the local binary build hash.
2. **Identifier Safety**: Validates database, schema, and table names against target platform reserved keywords and length limits.
3. **Data Type Compatibility**: Pre-scans source columns to identify unsupported RDBMS datatypes or unsupported timestamp scales.

### Phase 2: Partition Discovery & Scope Analysis (`STEP_FIND_OFFLOAD_DATA`)
Implemented via `get_offload_data_manager()`:
- **`OffloadSourceDataIpaRange`**: Range partition append. Queries `ALL_TAB_PARTITIONS`, decodes high values, checks high-water mark (HWM), and identifies active vs dormant partitions.
- **`OffloadSourceDataIpaList`**: List partition append. Tracks offloaded value sets.
- **`OffloadSourceDataPredicate`**: Predicate-based offload. Parses arbitrary WHERE clauses using AST parser and injects synthetic partition filters.
- **Chunking**: Splits large partition sets into manageable chunks based on `--max-offload-chunk-size` (bytes) or `--max-offload-chunk-count` (count).

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
