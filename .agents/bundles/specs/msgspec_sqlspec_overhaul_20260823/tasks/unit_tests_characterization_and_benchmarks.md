---
type: Task
id: msgspec_sqlspec_overhaul_20260823:unit_tests_characterization_and_benchmarks
title: Verify Unit Tests & Characterization for Msgspec/SQLSpec Migration
description: Verify unit test suite and characterization benchmarks for msgspec and sqlspec migration.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - test
  - testing
  - characterization
  - msgspec
  - sqlspec
depends_on:
  - msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
  - msgspec_sqlspec_overhaul_20260823:orchestration_repo_msgspec_migration
  - msgspec_sqlspec_overhaul_20260823:offload_messages_msgspec_migration
  - msgspec_sqlspec_overhaul_20260823:sqlspec_integration_and_struct_schemas
files:
  - tests/unit/util/test_json_tools.py
  - tests/unit/persistence/test_schemas.py
  - tests/unit/
tests:
  - tests/unit
verification_strategy: characterization
---

# Task: Verify Unit Tests & Characterization for Msgspec/SQLSpec Migration

## Objective
Implement dedicated test suites (`tests/unit/util/test_json_tools.py` and `tests/unit/persistence/test_schemas.py`) and execute the complete GOE unit test suite (`tests/unit/`), asserting 100% green execution and confirming 0 remaining references to `orjson` in the `src/` tree.

## Itemized Checklist
- [ ] Create `tests/unit/util/test_json_tools.py`.
- [ ] Create `tests/unit/persistence/test_schemas.py`.
- [ ] Run full unit test suite with `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit`.
- [ ] Assert 0 remaining `orjson` references via `git grep -i "orjson" src/`.

## Verification Strategy
- **Strategy**: `characterization`
- **CLI Commands**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit -v
  ! git grep -i "orjson" src/
  ```
- **Expected Output**: All unit tests pass 100% green.\n