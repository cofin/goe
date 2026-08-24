---
type: Task
id: msgspec_sqlspec_overhaul_20260823:sqlspec_integration_and_struct_schemas
title: Integrate SQLSpec Library & Define msgspec Struct Schemas
description: Integrate SQLSpec database abstraction library and define typed msgspec.Struct models for schemas.
state: closed
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T22:58:00Z"
tags:
  - feature
  - sqlspec
  - msgspec
  - schemas
depends_on:
  - msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
  - msgspec_sqlspec_overhaul_20260823:orchestration_repo_msgspec_migration
files:
  - pyproject.toml
  - src/goe/persistence/schemas.py
tests:
  - tests/unit/persistence/test_schemas.py
verification_strategy: static_validation
---

# Task: Integrate SQLSpec Library & Define msgspec Struct Schemas

## Objective
Add `sqlspec[performance,mypyc,oracledb,adbc,duckdb]>=0.61.0` and `msgspec>=0.19.0` to `pyproject.toml` (while removing `orjson`), and define typed `msgspec.Struct` models in `src/goe/persistence/schemas.py` for execution metadata and telemetry.

## Target File Changes

1. **`pyproject.toml`**: Add `msgspec` and `sqlspec[performance,mypyc,oracledb,adbc,duckdb]`, remove `orjson`.
2. **`src/goe/persistence/schemas.py`**:
   - `StepDetailSchema(msgspec.Struct)`
   - `CommandExecutionSchema(msgspec.Struct)`
   - `OffloadMetadataSchema(msgspec.Struct)`
   - `LogEventSchema(msgspec.Struct)`
   - `PartitionMetadataSchema(msgspec.Struct)`
   - `encode_schema` and `decode_schema` helper functions.

## Itemized Checklist
- [x] Update `pyproject.toml` with `msgspec` and `sqlspec`.
- [x] Create `src/goe/persistence/schemas.py`.
- [x] Create `tests/unit/persistence/test_schemas.py`.

## Verification Strategy
- **Strategy**: `static_validation`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/persistence/test_schemas.py -v
  ```
- **Expected Output**: Schema encoding/decoding tests pass green.\n