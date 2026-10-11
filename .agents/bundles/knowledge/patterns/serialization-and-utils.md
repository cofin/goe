---
type: Reference
title: Serialization & Utility Re-Export Patterns
description: High-performance msgspec.Struct serialization and sqlspec.utils re-export conventions across src/goe/util/
tags:
  - pattern
  - serialization
  - msgspec
  - sqlspec
  - utilities
updated_at: "2026-10-11T15:09:00Z"
---

# Serialization & Utility Re-Export Patterns

## `sqlspec.utils` Module Re-Exports (`src/goe/util/`)

Utility modules under `src/goe/util/` re-export `sqlspec.utils` primitives directly while delegating custom GOE domain object serialization (`ExecutionId`, `.dsl` predicate objects) through `goe.util.json_tools`:

- [`src/goe/util/json_tools.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/json_tools.py): Canonical JSON module — `serialize_object`, `serialize_object_bytes`, `deserialize_object`, `encode_datetime_object`, `convert_field_to_camel_case` (`msgspec.json.Encoder(enc_hook=_default)` fallback for `.dsl` and `.id`). `DEFAULT_TYPE_ENCODERS` comes from `sqlspec.utils.serializers`.
- [`src/goe/util/sync_tools.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/sync_tools.py): Re-exports `async_`, `await_`, `ensure_async_`, `run_`, and `CapacityLimiter` from `sqlspec.utils.sync_tools`, alongside `Portal` and `get_global_portal` from `sqlspec.utils.portal`.

## Typed `msgspec.Struct` Schemas (`src/goe/persistence/schemas.py` & `src/goe/listener/schemas.py`)

- Define repository metadata, telemetry payloads, and REST request/response DTOs as `msgspec.Struct` models (`StepDetailSchema`, `CommandExecutionSchema`, `OffloadMetadataSchema`, `LogEventSchema`, `PartitionMetadataSchema`, `ColumnDetail` with `data_precision` and `data_scale`, `PartitionDetail`, and `SubPartitionDetail` with `partition_name` and `partition_position`).
- Avoid importing `goe.goe` inside `src/goe/listener/schemas.py` (keeps the listener schema module free of the heavy `goe.goe` import graph). Instead, `OffloadOptions.to_params_dict()` normalizes and removes legacy alias keys directly so only canonical `EXPECTED_OFFLOAD_ARGS` keys are passed to `OffloadOperation.from_dict`.
- Use `msgspec` encoders/decoders across `src/goe/persistence/orchestration_repo_client.py`, `src/goe/offload/offload_messages.py`, and Listener controllers; never introduce `orjson` or Pydantic v1 models.

## Idiomatic Patterns & Gotchas

### 1. Heterogeneous Struct vs. Dict Traversal
`msgspec.Struct` instances do not implement dictionary methods (`.get()`, `.pop()`). When consuming lists from repository clients that mix dictionaries and structs (such as table partition and subpartition queries):
```python
normalized = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in (items or [])]
```
Calling `item.get(...)` directly on a raw `msgspec.Struct` raises `AttributeError`.

### 2. Parameter Whitelisting (`EXPECTED_OFFLOAD_ARGS`)
`OffloadOperation.from_dict` (`src/goe/goe.py:2061`) enforces an exact whitelist assertion: `all(k in EXPECTED_OFFLOAD_ARGS for k in operation_dict)`. Extraneous keys, diagnostic flags (`quiet`, `verbose`), or UI convenience aliases must be mapped or pruned at the API/CLI boundary via `OffloadOptions.to_params_dict()` before reaching the runner.

### 3. Domain Object Serialization Fallback
Standard JSON serializers fail on `ExecutionId` instances and `.dsl` expression trees. `goe.util.json_tools.serialize_object` configures `msgspec.json.Encoder(enc_hook=_default)` to handle:
- `ExecutionId`: Serialized to standard UUID string representation.
- Predicates / Generic Predicate: Serialized via `obj.dsl`.
- `Decimal`, `datetime`, `date`: Serialized to ISO strings / numeric primitives.
- `numpy.ndarray`, `numpy.generic`: Serialized via `.tolist()`.

