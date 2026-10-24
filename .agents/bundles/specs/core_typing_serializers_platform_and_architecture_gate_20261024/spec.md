---
type: Spec
flow_id: core_typing_serializers_platform_and_architecture_gate_20261024
title: "Chapter 5.2: Core Typing, Serializers, Platform Utilities, and Architecture Gate"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T16:45:00Z
description: "Introduces GC-exempt msgspec base structs, centralized JSON serializers, cached optional module loading, bounded concurrency and subprocess helpers, platform worker and table locking primitives, and the AST architecture verifier."
tags: [refactor, typing, serializers, platform, tooling]
parent_prd: prd_05_foundation_typing_settings_and_adapter_reduction_20261024
depends_on:
  - adapter_reduction_and_adapter_registry_20261024
research:
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/goe-architecture-redesign.md
---

# Chapter 5.2: Core Typing, Serializers, Platform Utilities, and Architecture Gate

## Specification

### 1. Overview and Goals

1. Create `src/goe/typing.py` defining `BaseStruct`, `FrozenBaseStruct`, `WireFrameStruct`, `CamelStruct`, `FrozenCamelStruct`, `UnsetType`, `UNSET`, and `filter_unset` on `msgspec==0.22.0` with `gc=False` so value objects bypass cyclic garbage-collection tracking.
2. Create `src/goe/serializers.py` providing `encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, and `decode_json` backed by reusable `msgspec.json.Encoder` and `msgspec.json.Decoder` instances with deterministic `Decimal`, `datetime`/`date`, `Path`, `UUID`, and `ExecutionId` hooks, and retire `src/goe/util/json_tools.py`.
3. Create `src/goe/util/module_loader.py` (`import_optional`, `ensure_module`, `module_available`, `lazy_exports`), `src/goe/util/string_utils.py`, `src/goe/util/concurrency.py` (`run_bounded`), and `src/goe/util/subprocess_utils.py` (`CommandResult(FrozenBaseStruct)`, `run_checked_cmd`), and switch `LazyTarget.load()` in `src/goe/offload/registry.py` and `src/goe/cli/_lazy.py` onto `module_loader`.
4. Create `src/goe/platform/worker.py` (`LocalProcessWorker` using `run_checked_cmd` and `tempfile.SpooledTemporaryFile`, plus container-aware `CgroupQuota` and `LameDuckController`) and `src/goe/platform/locking.py` (`FileOrchestrationLock` using `filelock.FileLock`), retiring `src/goe/util/local_manager.py`, `src/goe/orchestration/orchestration_lock.py`, and `src/goe/orchestration/factory/orchestration_lock_factory.py`.
5. Create `tools/verify_architecture.py` and `tools/architecture_baseline.toml` wired into `Makefile` `lint` to enforce AST boundaries across `src/goe/` and `tests/unit/`.

### 2. Code Analysis Summary

- `src/goe/util/json_tools.py:1-56` wraps `json.loads` and `json.dumps` for JSON validation and formatting; called by `src/goe/offload/bigquery/bigquery_backend_table.py:25`, `src/goe/offload/snowflake/snowflake_backend_table.py:28`, and `src/goe/offload/microsoft/synapse_backend_table.py:25`.
- `src/goe/offload/registry.py:89-119` (added in Chapter 5.1 task 1.1) defines `LazyTarget` and `AdapterEntry` directly on `msgspec.Struct, frozen=True, gc=False` and calls `importlib.import_module(self.module)` in `LazyTarget.load()`.
- `src/goe/cli/_lazy.py:1-60` implements lazy subcommand loading for `rich-click` and can delegate optional module importing to `goe.util.module_loader`.
- `src/goe/orchestration/orchestration_lock.py:1-115` defines `OrchestrationLockTimeout`, `OrchestrationLockInterface`, `FileLockOrchestrationLock`, `orchestration_lock_for_table`, and `orchestration_lock_from_hybrid_metadata` using `filelock.FileLock` in `$OFFLOAD_HOME/run/`. Callers are `src/goe/orchestration/execution.py:30`, `src/goe/orchestration/operation.py:48`, `src/goe/listener/controllers/orchestration.py:21`, and `src/goe/schema_sync/schema_sync.py:28`.
- `Makefile:1-55` defines `lint` running `uv run ruff check` and `uv run mypy src/goe`.

### 3. Requirements

- R1: `src/goe/typing.py` defines `BaseStruct(msgspec.Struct, gc=False)`, `FrozenBaseStruct(msgspec.Struct, frozen=True, gc=False)`, `WireFrameStruct(msgspec.Struct, frozen=True, gc=False, array_like=True)`, `CamelStruct(msgspec.Struct, rename="camel", gc=False)`, `FrozenCamelStruct(msgspec.Struct, rename="camel", frozen=True, gc=False)`, `UnsetType`, `UNSET`, and `filter_unset(mapping_or_struct)`.
- R2: `src/goe/serializers.py` defines `encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, and `decode_json` with type-checked `type[T]` decoding and custom encoding hooks; `src/goe/util/json_tools.py` is deleted and its callers migrate to `goe.serializers`.
- R3: `src/goe/util/module_loader.py` provides `import_optional`, `ensure_module`, `module_available`, and `lazy_exports`; `src/goe/util/string_utils.py`, `src/goe/util/concurrency.py` (`run_bounded`), and `src/goe/util/subprocess_utils.py` (`CommandResult(FrozenBaseStruct)`, `run_checked_cmd`) provide typed foundational helpers; `src/goe/offload/registry.py` `LazyTarget.load()` uses `ensure_module(self.module, extra=self.extra)`.
- R4: `src/goe/platform/worker.py` provides `LocalProcessWorker` (using `run_checked_cmd` and `tempfile.SpooledTemporaryFile`), `CgroupQuota`, and `LameDuckController`; `src/goe/platform/locking.py` provides `FileOrchestrationLock` (aliased as `FileLockOrchestrationLock` only within `locking.py` if needed by callers, or callers migrated directly to `FileOrchestrationLock`), `OrchestrationLockInterface`, `OrchestrationLockTimeout`, `orchestration_lock_for_table`, and `orchestration_lock_from_hybrid_metadata`; `src/goe/util/local_manager.py`, `src/goe/orchestration/orchestration_lock.py`, and `src/goe/orchestration/factory/orchestration_lock_factory.py` do not exist after task 1.3.
- R5: `tools/verify_architecture.py` parses `src/goe/` and `tests/unit/` with `ast` and `tokenize` to enforce: (a) zero raw `json.dumps`/`json.loads`/`msgspec.json` calls outside `src/goe/serializers.py`, (b) zero `sqlglot` imports outside `src/goe/offload/sql_ast/`, (c) zero `import oracledb` outside `src/goe/persistence/oracle/` and `src/goe/offload/oracle/`, (d) zero function-scoped `import` / `from ... import` statements outside documented circular/optional exemptions, (e) public functions/methods before private `_` helpers in every module and class, and (f) zero `#` comments inside function or method bodies, honoring only pre-existing baseline entries in `tools/architecture_baseline.toml` and failing when new violations appear or when stale baseline entries are cleared.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.1 | `tests/unit/test_typing.py` |
| R2 | 1.1 | `tests/unit/test_serializers.py` |
| R3 | 1.2 | `tests/unit/util/test_module_loader.py`, `tests/unit/util/test_string_utils.py`, `tests/unit/util/test_concurrency.py`, `tests/unit/util/test_subprocess_utils.py`, `tests/unit/offload/test_registry.py` |
| R4 | 1.3 | `tests/unit/platform/test_worker.py`, `tests/unit/platform/test_locking.py` |
| R5 | 1.4 | `tests/unit/tools/test_verify_architecture.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/test_typing.py tests/unit/test_serializers.py tests/unit/util/test_module_loader.py tests/unit/util/test_string_utils.py tests/unit/util/test_concurrency.py tests/unit/util/test_subprocess_utils.py tests/unit/offload/test_registry.py tests/unit/platform/test_worker.py tests/unit/platform/test_locking.py tests/unit/tools/test_verify_architecture.py -v
uv run ruff format --check src/goe tests/unit tools
uv run ruff check src/goe tests/unit tools
uv run mypy src/goe
uv run python tools/verify_architecture.py
uv run pytest tests/unit -q
```

## Implementation Plan

### Phase 1: Core Typing, Serializers, and Foundational Utilities
- [ ] 1.1 Add GC-exempt msgspec base structs and centralized JSON serializers ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Add module loader, string, bounded concurrency, and subprocess utilities ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: Platform Primitives and Architecture Verifier
- [ ] 1.3 Add platform process worker and file orchestration locking ([tasks/1.3.md](tasks/1.3.md))
- [ ] 1.4 Add the AST architecture boundary verifier and wire it into make lint ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `core_typing_serializers_platform_and_architecture_gate_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `goe.typing` and `goe.serializers` live at the package root (`src/goe/typing.py`, `src/goe/serializers.py`); `src/goe/platform/{worker,locking}.py` houses process worker, cgroup/drain helpers, and file-based table locks; `tools/verify_architecture.py` enforces the six AST and token rules against `tools/architecture_baseline.toml`.
- **Discoveries**: none yet.
- **Blockers**: `adapter_reduction_and_adapter_registry_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`core_typing_serializers_platform_and_architecture_gate_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `AGENTS.md`, `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/standards/python.md`, `.agents/bundles/knowledge/standards/testing.md`.
