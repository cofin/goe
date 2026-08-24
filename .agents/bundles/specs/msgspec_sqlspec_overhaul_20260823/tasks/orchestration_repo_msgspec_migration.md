---
type: Task
id: msgspec_sqlspec_overhaul_20260823:orchestration_repo_msgspec_migration
title: Migrate OrchestrationRepoClient JSON serialization to msgspec
description: Migrate OrchestrationRepoClient JSON serialization and query result parsing to msgspec.
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-24T21:45:00Z"
tags:
  - migration
  - persistence
  - msgspec
  - repository
depends_on:
  - msgspec_sqlspec_overhaul_20260823:json_tools_msgspec_migration
files:
  - src/goe/persistence/orchestration_repo_client.py
  - src/goe/persistence/oracle/oracle_orchestration_repo_client.py
  - src/goe/persistence/teradata/teradata_orchestration_repo_client.py
tests:
  - tests/unit/persistence/test_orchestration_repo_client.py
verification_strategy: characterization
---

# Task: Migrate OrchestrationRepoClient JSON serialization to msgspec

## Objective
Update `src/goe/persistence/orchestration_repo_client.py` and backend-specific repository clients (`oracle_orchestration_repo_client.py`, `teradata_orchestration_repo_client.py`) to serialize and parse JSON options, parameters, and step details with `msgspec`, eliminating all legacy `json.dumps`/`json.loads` calls and removing `orjson` references.

## Target File Changes

### 1. `src/goe/persistence/orchestration_repo_client.py`
- Re-implement `type_safe_json_dumps` to call `serialize_object(d)`.
- Implement `type_safe_json_loads(payload)` to call `deserialize_object(payload)`.
- Update `_metadata_dict_to_json_string` and `_prepare_command_parameters`.

### 2. Backend Repo Clients
- Update `oracle_orchestration_repo_client.py` and `teradata_orchestration_repo_client.py` to import `deserialize_object` and `serialize_object` from `goe.util.json_tools`.

## Itemized Checklist
- [ ] Update `type_safe_json_dumps` and add `type_safe_json_loads` in `orchestration_repo_client.py`.
- [ ] Update `_metadata_dict_to_json_string` and `_prepare_command_parameters`.
- [ ] Update Oracle and Teradata repo clients to use `deserialize_object`/`serialize_object`.
- [ ] Run `tests/unit/persistence/test_orchestration_repo_client.py`.

## Verification Strategy
- **Strategy**: `characterization`
- **CLI Command**:
  ```bash
  export GOOGLE_API_USE_CLIENT_CERTIFICATE=false && uv run pytest tests/unit/persistence/test_orchestration_repo_client.py -v
  ```
- **Expected Output**: Repository serialization tests pass 100% green.\n