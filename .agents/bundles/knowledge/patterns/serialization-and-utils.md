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
updated_at: "2026-10-25T15:50:00Z"
---

# Serialization & Utility Re-Export Patterns

## Core Typing, Serializers, and Platform Primitives (`src/goe/typing.py`, `src/goe/serializers.py`, `src/goe/util/`, `src/goe/platform/`)

- `src/goe/typing.py`: Canonical struct base classes (`BaseStruct` with `gc=False`, `FrozenBaseStruct` with `frozen=True, gc=False`, `WireFrameStruct` with `frozen=True, gc=False, array_like=True`, and `CamelCaseStruct` with `rename="camel"`), `UNSET` / `UnsetType`, and `convert_data` / `convert_to_dict`.
- `src/goe/serializers.py`: Canonical JSON module — `encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, `decode_json`, `encode_datetime_object`, and `convert_field_to_camel_case` (`msgspec.json.Encoder(enc_hook=_default)` handling `ExecutionId`, `.dsl`, `Decimal`, `datetime`/`date`, and `numpy.ndarray`/`numpy.generic`). Replaced legacy `src/goe/util/json_tools.py`.
- **Dissolved `src/goe/util/` (7 Modules Only)**:
  - `__init__.py`, `goe_log.py`, `goe_log_fh.py`
  - `src/goe/util/module_loader.py`: `import_string`, `module_to_os_path`, `ensure_optional_dependency`, `import_optional_dependency`, and `MissingOptionalDependencyError` (inherits from `(OffloadException, ModuleNotFoundError)`).
  - `src/goe/util/string_utils.py`: `camel_to_snake`, `snake_to_camel`, `camel_to_kebab`, `kebab_to_pascal`, plus GOE formatting/redaction/size-parsing helpers.
  - `src/goe/util/concurrency.py`: `async_`, `await_`, `ensure_async_`, `run_`, `CapacityLimiter`, `Portal`, `get_global_portal`, and context-preserving `parallel_map`.
  - `src/goe/util/subprocess_utils.py`: `run_os_cmd`, `SubprocessError`, and `format_shell_cmd`.
- `src/goe/platform/worker.py` & `src/goe/platform/locking.py`: Host/CPU/memory inspection and `OrchestrationLock` (`filelock` in `$OFFLOAD_HOME/run/`).

## Declarative Settings & Option Registry (`src/goe/config/settings.py`, `src/goe/config/option_registry.py`, `src/goe/config/options.py`)

- `src/goe/config/settings.py`: Frozen `GOESettings(FrozenBaseStruct)` loaded explicitly via `GOESettings.from_env(environ=..., env_file=...)` with backend validation and zero import-time side effects. `OrchestrationConfig` delegates to `GOESettings` without mutating `os.environ` or creating directories at construction time.
- `src/goe/config/option_registry.py`: Single declarative `OPTION_REGISTRY: tuple[OptionSpec, ...]` deriving `EXPECTED_OFFLOAD_ARGS`, `LISTENER_OFFLOAD_RENAME_ALIASES`, `LISTENER_OFFLOAD_CSV_ALIASES`, and CLI option flags (`src/goe/cli/options.py`).
- `src/goe/config/options.py`: Acyclic import leaf defining `BaseOptionStruct`, `TestModeFaults`, `OffloadOptions` (combining CLI defaults with Listener wire semantics via `to_params_dict()` and `to_operation_options()`), and the 7 command option structs:

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
- **Canonical Option Exception**: `src/goe/exceptions.py` exports `OptionValueError = OffloadOptionError`; zero `optparse` imports exist in `src/goe/`.

## Typed `msgspec.Struct` Persistence & REST Schemas (`src/goe/persistence/schemas.py` & `src/goe/listener/schemas.py`)

- Define repository metadata, telemetry payloads, and REST request/response DTOs as `msgspec.Struct` models (`StepDetailSchema`, `CommandExecutionSchema`, `OffloadMetadataSchema`, `LogEventSchema`, `PartitionMetadataSchema`, `ColumnDetail` with `data_precision` and `data_scale`, `PartitionDetail`, and `SubPartitionDetail` with `partition_name` and `partition_position`).
- In `src/goe/listener/schemas.py`, `OffloadOptions` preserves REST wire defaults (`execute: bool = True` and `None` unset sentinels) so `to_params_dict()` records only caller-supplied parameters in `COMMAND_EXECUTION.COMMAND_INPUT`, while `to_operation_options() -> OffloadOperationOptions` hydrates omitted fields from the canonical `OffloadOperationOptions` defaults (`test_offload_options_fields_track_expected_offload_args` enforces 100% field parity).
- Use `msgspec` encoders/decoders across `src/goe/persistence/orchestration_repo_client.py`, `src/goe/offload/offload_messages.py`, and Listener controllers; never introduce `orjson` or Pydantic v1 models.

## Idiomatic Patterns & Gotchas

### 1. Heterogeneous Struct vs. Dict Traversal
`msgspec.Struct` instances do not implement dictionary methods (`.get()`, `.pop()`). When consuming lists from repository clients that mix dictionaries and structs (such as table partition and subpartition queries):
```python
normalized = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in (items or [])]
```
Calling `item.get(...)` directly on a raw `msgspec.Struct` raises `AttributeError`.

### 2. Parameter Whitelisting (`EXPECTED_OFFLOAD_ARGS`)
`OffloadOperationOptions.from_mapping` (`src/goe/config/options.py`) and `OffloadPipeline` (`src/goe/orchestration/pipeline.py`) enforce an exact whitelist assertion against `EXPECTED_OFFLOAD_ARGS`. Extraneous keys, diagnostic flags (`quiet`, `verbose`), or UI convenience aliases must be mapped or pruned at the API/CLI boundary via `OffloadOptions.to_params_dict()` before reaching the runner.

### 3. Domain Object Serialization Fallback
Standard JSON serializers fail on `ExecutionId` instances and `.dsl` expression trees. `goe.serializers.encode_json` configures `msgspec.json.Encoder(enc_hook=_default)` to handle:
- `ExecutionId`: Serialized to standard UUID string representation.
- Predicates / Generic Predicate: Serialized via `obj.dsl`.
- `Decimal`, `datetime`, `date`: Serialized to ISO strings / numeric primitives.
- `numpy.ndarray`, `numpy.generic`: Serialized via `.tolist()`.


