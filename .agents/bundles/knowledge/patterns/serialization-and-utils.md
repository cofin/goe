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
updated_at: "2026-10-04T18:27:30Z"
---

# Serialization & Utility Re-Export Patterns

## `sqlspec.utils` Module Re-Exports (`src/goe/util/`)

Utility modules under `src/goe/util/` re-export `sqlspec.utils` primitives directly while delegating custom GOE domain object serialization (`ExecutionId`, `.dsl` predicate objects) through `goe.util.json_tools`:

- [`src/goe/util/serialization.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/serialization.py): Re-exports `to_json`, `from_json`, `schema_dump`, and `DEFAULT_TYPE_ENCODERS` from `sqlspec.utils.serializers`, and delegates `serialize_object` and `serialize_object_bytes` to [`src/goe/util/json_tools.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/json_tools.py) (`msgspec.json.Encoder(enc_hook=_default)` fallback for `.dsl` and `.id` domain objects).
- [`src/goe/util/sync_tools.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/sync_tools.py): Re-exports `async_`, `await_`, `ensure_async_`, `run_`, and `CapacityLimiter` from `sqlspec.utils.sync_tools`, alongside `Portal` and `get_global_portal` from `sqlspec.utils.portal`.
- [`src/goe/util/text.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/text.py): Re-exports `camelize`, `pascalize`, `snake_case`, `kebabize`, `slugify`, `quote_identifier`, and `split_qualified_identifier` from `sqlspec.utils.text`.
- [`src/goe/util/env.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/env.py): Re-exports `get_env`, `get_env_with_aliases`, `get_config_val`, and `is_env_set` from `sqlspec.utils.env`.
- [`src/goe/util/uuids.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/uuids.py): Re-exports `uuid4`, `uuid7`, and `nanoid` from `sqlspec.utils.uuids`.

## Typed `msgspec.Struct` Schemas (`src/goe/persistence/schemas.py` & `src/goe/listener/schemas.py`)

- Define repository metadata, telemetry payloads, and REST request/response DTOs as `msgspec.Struct` models (`StepDetailSchema`, `CommandExecutionSchema`, `OffloadMetadataSchema`, `LogEventSchema`, `PartitionMetadataSchema`, `ColumnDetail` with `data_precision` and `data_scale`, `PartitionDetail`, and `SubPartitionDetail` with `partition_name` and `partition_position`).
- Avoid importing `goe.goe` inside `src/goe/listener/schemas.py` (which would trigger a circular import via `goe.offload.offload_messages` -> `goe.listener.utils.cache`). Instead, `OffloadOptions.to_params_dict()` normalizes and removes legacy alias keys directly so only canonical `EXPECTED_OFFLOAD_ARGS` keys are passed to `OffloadOperation.from_dict`.
- Use `msgspec` encoders/decoders across `src/goe/persistence/orchestration_repo_client.py`, `src/goe/offload/offload_messages.py`, and Listener controllers; never introduce `orjson` or Pydantic v1 models.

