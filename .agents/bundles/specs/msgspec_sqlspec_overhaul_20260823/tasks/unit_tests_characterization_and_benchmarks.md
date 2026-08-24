---
type: Task
id: msgspec_sqlspec_overhaul_20260823:unit_tests_characterization_and_benchmarks
title: Verify Unit Tests & Characterization for Msgspec/SQLSpec Migration
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - task
  - testing
  - characterization
  - msgspec
depends_on:
  - msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
  - msgspec_sqlspec_overhaul_20260823:orchestration_repo_msgspec_migration
  - msgspec_sqlspec_overhaul_20260823:offload_messages_msgspec_migration
  - msgspec_sqlspec_overhaul_20260823:sqlspec_integration_and_struct_schemas
files:
  - tests/unit/
tests:
  - tests/unit
verification_strategy: characterization
---

# Task: Verify Unit Tests & Characterization for Msgspec/SQLSpec Migration

## Objective
Run the complete unit test suite and assert 100% green execution, proving that the removal of `orjson` and adoption of `msgspec` and `sqlspec` maintains total runtime compatibility and prevents data corruption.

## Implementation Details

1. Run `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit`.
2. Ensure all tests passing on baseline continue to pass with `msgspec`.
3. Verify zero remaining occurrences of `orjson` in `src/goe/`.

## Verification
- **Strategy**: `characterization`
- **Initial Evidence**: Baseline run of unit tests.
- **Final Evidence**: `uv run pytest tests/unit` passes 100% green; `git grep -i "orjson" src/` returns 0 results.
