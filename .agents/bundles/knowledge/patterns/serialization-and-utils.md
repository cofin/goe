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
updated_at: "2026-10-12T15:50:00Z"
---

# Serialization & Utility Re-Export Patterns

## `sqlspec.utils` Module Re-Exports (`src/goe/util/`)

Utility modules under `src/goe/util/` re-export `sqlspec.utils` primitives directly while delegating custom GOE domain object serialization (`ExecutionId`, `.dsl` predicate objects) through `goe.util.json_tools`:

- [`src/goe/util/json_tools.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/json_tools.py): Canonical JSON module — `serialize_object`, `serialize_object_bytes`, `deserialize_object`, `encode_datetime_object`, `convert_field_to_camel_case` (`msgspec.json.Encoder(enc_hook=_default)` fallback for `.dsl` and `.id`). `DEFAULT_TYPE_ENCODERS` comes from `sqlspec.utils.serializers`.
- [`src/goe/util/sync_tools.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/util/sync_tools.py): Re-exports `async_`, `await_`, `ensure_async_`, `run_`, and `CapacityLimiter` from `sqlspec.utils.sync_tools`, alongside `Portal` and `get_global_portal` from `sqlspec.utils.portal`.

## Typed `msgspec.Struct` Option Hierarchy (`src/goe/config/options.py`)

[`src/goe/config/options.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/config/options.py) is an acyclic import leaf (importing only stdlib, `msgspec`, `goe.lib.schemas.BaseStruct`, and `goe.config.orchestration_defaults`) that replaces legacy `optparse.OptionParser` builders and `optparse.Values` bags across all CLI commands, orchestration runners, and the Listener service:

- **`BaseOptionStruct`** (`kw_only=True`, slot-backed without `dict=True`): Provides `from_mapping(cls, mapping: Mapping[str, Any]) -> Self`, `to_dict(self) -> dict[str, Any]` (`msgspec.structs.asdict`), and `__contains__(self, key: object) -> bool`. Because `dict=True` is omitted, undeclared attribute writes raise `AttributeError` and `from_mapping` raises `TypeError` on unknown keys, ensuring `copy.copy`/`copy.deepcopy` preserve 100% of fields.
- **7 Command Option Structs** (each declares `kw_only=True` and uses `msgspec.field(default_factory=orchestration_defaults.<name>_default)` for environment-backed defaults):
  - `CommonOptions`: 14 global/common flags (`quiet`, `verbose`, `vverbose`, `ansi`, `log_path`, `log_level`, `no_version_check`, `error_before_step`, `error_after_step`, `error_on_token`, `suppress_stdout`, `version`, `target`, `db_type`).
  - `TableOperationOptions(CommonOptions)`: 40 table-level options plus 7 derived normaliser fields (`owner`, `table_name`, `target_owner`, `target_name`, `hybrid_owner`, `hybrid_view`, `storage_table`).
  - `OffloadOperationOptions(TableOperationOptions)`: 42 offload-specific fields plus `operation_name: str = "offload"`.
  - `AggValidateOptions(TableOperationOptions)`: 7 cross-database validation fields (`filters`, `selects`, `clauses`, `as_of_scn`, `execute`, `dev_log_level`, `target_owner_name`).
  - `ConnectOptions(CommonOptions)`: `create_backend_db`, `upgrade_environment_file`, `hadoop_host`, `hdfs_host`.
  - `StatusReportOptions(CommonOptions)`: 9 report options (`report_directory` defaults to `None` and resolves lazily via `default_report_directory()` inside `_normalise_osr_options` so runtime `OFFLOAD_HOME` changes are respected).
  - `SchemaSyncOptions(CommonOptions)`: `include_objects`, `Auto` (`bool`), and normalization targets.
- **Shared Offload Keys & Listener Aliases**: `EXPECTED_OFFLOAD_ARGS` (85-key `tuple[str, ...]`), `LISTENER_OFFLOAD_RENAME_ALIASES`, and `LISTENER_OFFLOAD_CSV_ALIASES` live in `src/goe/config/options.py` and are imported by both `src/goe/orchestration/` and `src/goe/listener/schemas.py`.
- **Canonical Option Exception**: [`src/goe/exceptions.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/exceptions.py) exports `OptionValueError = OffloadOptionError`; zero `optparse` imports exist in `src/goe/`.

## Typed `msgspec.Struct` Persistence & REST Schemas (`src/goe/persistence/schemas.py` & `src/goe/listener/schemas.py`)

- Define repository metadata, telemetry payloads, and REST request/response DTOs as `msgspec.Struct` models (`StepDetailSchema`, `CommandExecutionSchema`, `OffloadMetadataSchema`, `LogEventSchema`, `PartitionMetadataSchema`, `ColumnDetail` with `data_precision` and `data_scale`, `PartitionDetail`, and `SubPartitionDetail` with `partition_name` and `partition_position`).
- In [`src/goe/listener/schemas.py`](file:///usr/local/google/home/codyfincher/code/gluent/next-goe/src/goe/listener/schemas.py), `OffloadOptions` preserves REST wire defaults (`execute: bool = True` and `None` unset sentinels) so `to_params_dict()` records only caller-supplied parameters in `COMMAND_EXECUTION.COMMAND_INPUT`, while `to_operation_options() -> OffloadOperationOptions` hydrates omitted fields from the canonical `OffloadOperationOptions` defaults (`test_offload_options_fields_track_expected_offload_args` enforces 100% field parity).
- Use `msgspec` encoders/decoders across `src/goe/persistence/orchestration_repo_client.py`, `src/goe/offload/offload_messages.py`, and Listener controllers; never introduce `orjson` or Pydantic v1 models.

## Idiomatic Patterns & Gotchas

### 1. Heterogeneous Struct vs. Dict Traversal
`msgspec.Struct` instances do not implement dictionary methods (`.get()`, `.pop()`). When consuming lists from repository clients that mix dictionaries and structs (such as table partition and subpartition queries):
```python
normalized = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in (items or [])]
```
Calling `item.get(...)` directly on a raw `msgspec.Struct` raises `AttributeError`.

### 2. Parameter Whitelisting (`EXPECTED_OFFLOAD_ARGS`)
`OffloadOperation.from_dict` (`src/goe/orchestration/operation.py`) enforces an exact whitelist assertion: `all(k in EXPECTED_OFFLOAD_ARGS for k in operation_dict)`. Extraneous keys, diagnostic flags (`quiet`, `verbose`), or UI convenience aliases must be mapped or pruned at the API/CLI boundary via `OffloadOptions.to_params_dict()` before reaching the runner.

### 3. Domain Object Serialization Fallback
Standard JSON serializers fail on `ExecutionId` instances and `.dsl` expression trees. `goe.util.json_tools.serialize_object` configures `msgspec.json.Encoder(enc_hook=_default)` to handle:
- `ExecutionId`: Serialized to standard UUID string representation.
- Predicates / Generic Predicate: Serialized via `obj.dsl`.
- `Decimal`, `datetime`, `date`: Serialized to ISO strings / numeric primitives.
- `numpy.ndarray`, `numpy.generic`: Serialized via `.tolist()`.


