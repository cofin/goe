---
type: Task
id: msgspec_sqlspec_overhaul_20260823:orchestration_repo_msgspec_migration
title: Migrate OrchestrationRepoClient JSON serialization to msgspec
description: Migrate OrchestrationRepoClient JSON serialization and query result parsing to msgspec.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - migration
  - persistence
  - msgspec
  - repository
depends_on:
  - msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
files:
  - src/goe/persistence/orchestration_repo_client.py
tests:
  - tests/unit
verification_strategy: characterization
---

# Task: Migrate OrchestrationRepoClient JSON serialization to msgspec

## Objective
Update `src/goe/persistence/orchestration_repo_client.py` to use `msgspec` for `type_safe_json_dumps` and JSON string extraction, eliminating `orjson` and `json.dumps`.

## Implementation Details

1. Define module-level `_msgspec_json_encoder = msgspec.json.Encoder(enc_hook=_default)`.
2. Update `type_safe_json_dumps(obj)` to use `_msgspec_json_encoder.encode(obj).decode("utf-8")`.
3. Update `type_safe_json_loads(payload)` to use `msgspec.json.decode(payload)`.
4. Ensure repository queries storing command execution options and metadata JSON strings execute identically.

## Verification
- **Strategy**: `characterization`
- **Initial Evidence**: Baseline tests passing for repository client.
- **Final Evidence**: `uv run pytest tests/unit` passing 100% green without `orjson` dependency.
