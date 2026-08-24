---
type: Spec
flow_id: msgspec_sqlspec_overhaul_20260823
title: High-Performance Msgspec Serialization & SQLSpec Data Layer
state: planned
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
description: Complete elimination of orjson in favor of msgspec encoders/decoders and typed Struct models, alongside SQLSpec data abstraction integration.
tags:
  - spec
  - msgspec
  - sqlspec
  - serialization
  - persistence
parent_prd: modernization_overhaul_20260823
research:
  - modernization_overhaul_20260822
---

# Flow: High-Performance Msgspec Serialization & SQLSpec Data Layer

**Flow ID:** `msgspec_sqlspec_overhaul_20260823`

## Specification

### Code Analysis Summary
- **Current Serialization**: `orjson` used in `src/goe/util/json_tools.py`, `src/goe/persistence/orchestration_repo_client.py`, and `src/goe/offload/offload_messages.py`.
- **Existing Prior Art**: Branch `origin/msgspec` contains initial implementation replacing `orjson` with `msgspec.json.Encoder(enc_hook=_default)`.
- **Complex Domain Types**: `Decimal`, `datetime.datetime`, `datetime.date`, `ExecutionId`, `GenericPredicate` (dsl), and NumPy scalar/array types require custom encoding hooks.
- **Data Layer Architecture**: `sqlspec` (`sqlspec[duckdb,performance,asyncpg,mypyc,fsspec,uuid,adbc,oracledb,adk]>=0.61.0`) provides typed database drivers, query builders, and ADK stores.

### Requirements

#### Functional Requirements
1. Remove all dependencies on `orjson` across the entire codebase.
2. Implement robust `msgspec` encoding and decoding in `src/goe/util/json_tools.py` with custom `enc_hook` handling all domain types.
3. Update `src/goe/persistence/orchestration_repo_client.py` to use `msgspec` for all repository state serialization.
4. Update `src/goe/offload/offload_messages.py` Redis pub/sub message encoding to use `msgspec`.
5. Integrate `sqlspec` into core database querying and persistence modules.
6. Convert core data transfer and telemetry schemas into typed `msgspec.Struct` classes.

#### Non-Functional Requirements
- 100% backward compatibility for serialized JSON payloads in existing metadata repositories and Redis channels.
- Zero test regression across `tests/unit/`.

---

## Implementation Plan

### Phase 1: Core Msgspec Serialization Engine
- [ ] `json_tools_msgspec_migration`: Modernize `src/goe/util/json_tools.py` with `msgspec.json.Encoder(enc_hook=_default)` and `Decoder`.

### Phase 2: Repository Persistence & Messaging Migration
- [ ] `orchestration_repo_msgspec_migration`: Update `src/goe/persistence/orchestration_repo_client.py` to serialize with `msgspec`.
- [ ] `offload_messages_msgspec_migration`: Update `src/goe/offload/offload_messages.py` Redis publisher to use `msgspec`.

### Phase 3: SQLSpec Integration & Struct Schemas
- [ ] `sqlspec_integration_and_struct_schemas`: Integrate `sqlspec` library and define `msgspec.Struct` models for execution metadata and messages.

### Phase 4: Verification & Characterization Testing
- [ ] `unit_tests_characterization_and_benchmarks`: Verify all unit tests pass with `msgspec` and assert zero data corruption on complex types.
