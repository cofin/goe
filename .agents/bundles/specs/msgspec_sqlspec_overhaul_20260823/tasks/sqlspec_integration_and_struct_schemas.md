---
type: Task
id: msgspec_sqlspec_overhaul_20260823:sqlspec_integration_and_struct_schemas
title: Integrate SQLSpec Library & Define msgspec Struct Schemas
description: Integrate SQLSpec database abstraction library and define typed msgspec.Struct models for schemas.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
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
  - tests/unit
verification_strategy: static_validation
---

# Task: Integrate SQLSpec Library & Define msgspec Struct Schemas

## Objective
Integrate `sqlspec[duckdb,performance,asyncpg,mypyc,fsspec,uuid,adbc,oracledb,adk]>=0.61.0` into the project dependency tree and define typed `msgspec.Struct` models for execution metadata, system state, and schema definitions.

## Implementation Details

1. Add `sqlspec` to `pyproject.toml` dependencies and lockfile.
2. Create `src/goe/persistence/schemas.py` defining core typed `msgspec.Struct` models:
   - `CommandExecutionSchema` (fields: `id`, `command`, `status`, `start_time`, `end_time`, `options`, `messages`).
   - `OffloadMetadataSchema` (fields: `source_table`, `target_table`, `offload_mode`, `columns`, `partitions`).
3. Provide decoder/encoder helper methods on schemas.

## Verification
- **Strategy**: `static_validation`
- **Initial Evidence**: Absence of `src/goe/persistence/schemas.py` and `sqlspec` dependency.
- **Final Evidence**: `uv run python -c "import sqlspec, msgspec; from goe.persistence.schemas import CommandExecutionSchema; print('SQLSpec & Structs OK')"` executes successfully.
