---
type: Spec
flow_id: util_dissolution_dependency_and_lint_hygiene_20261024
title: "Chapter 5.4: Utility Dissolution, Dependencies, and Lint Hygiene"
state: completed
plan_revision: 1
plan_commit: null
state_revision: 1
current_task: null
last_operation: finish
operation_targets: ["1.1", "1.2", "1.3"]
last_verified_checkpoint: "1.3"
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T20:15:00Z
description: "Dissolve dead and misplaced modules in src/goe/util/, replace focused utility primitives, slim pyproject.toml dependencies and Ruff suppressions, and enforce strict mypy typing across core foundation packages."
tags: [refactor, configuration, typing, lint]
parent_prd: prd_05_foundation_typing_settings_and_adapter_reduction_20261024
depends_on: [declarative_settings_options_and_error_model_20261024]
research:
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/goe-architecture-redesign.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 5.4: Utility Dissolution, Dependencies, and Lint Hygiene

## Specification

### 1. Overview and Goals

This chapter dissolves the 5,906-LOC grab-bag `src/goe/util/` package, slims `pyproject.toml` dependencies, removes blanket Ruff rule suppressions, and enforces strict `mypy` checking across the core foundation packages:

1. **Utility Dissolution and Focused Primitives (`src/goe/util/`)**: Delete dead and redundant modules in `src/goe/util/` (`better_impyla.py`, `hs2_connection.py`, `ora_Query_from_env.py`, `misc_functions.py`, `simple_timer.py`, `git_functions.py`, `redis_client.py`, `hive_ddl_transform.py`, `kerberos.py`, `polling_thread.py`), relocate the Hive DDL transformation helper to `src/goe/offload/hadoop/hive_ddl.py`, relocate `password_tools.py` and `gcp_credentials.py` to `src/goe/config/`, replace `fsspec[gcs]` in `goe_log_fh.py` with `google.cloud.storage.Blob.open`, and route remaining callers to `goe/typing.py`, `goe/serializers.py`, and focused helpers `src/goe/util/{module_loader,string_utils,concurrency,subprocess_utils,retry}.py`.
2. **Dependency Slimming and Ruff Rule Hygiene (`pyproject.toml`)**: Remove unused and superseded dependencies (`orjson`, `pydantic`, `redis`, `PyYAML`, `tenacity`, `brotli`, `fsspec[gcs]`, `python-dateutil`, `azure-common`, and the `teradata` extra) from `pyproject.toml`, remove blanket Ruff rule suppressions (`BLE001`, `TRY*`, `PTH*`, `RET*`, `SIM*`, `C4*`, `PIE*`, `RUF*`, `E722`, `B006`, `B008`, `B012`, `B020`, `B023`, `B904`, `F504`, `F507`, `F811`), and fix all resulting violations in `src/goe/util/` and `src/goe/config/`.
3. **Strict Static Typing Gate**: Convert observability dataclasses in `src/goe/observability/{config,context,spans,_sdk,log_correlation}.py` to `FrozenBaseStruct` / `BaseStruct` and enforce strict `mypy` checking (`disallow_untyped_defs = true`, `disallow_any_generics = true`, `disallow_untyped_decorators = true`, `warn_return_any = true`) on `src/goe/typing.py`, `src/goe/serializers.py`, `src/goe/exceptions.py`, `src/goe/config/`, `src/goe/platform/`, and `src/goe/util/`.

### 2. Code Analysis Summary

- `src/goe/util/`: Contains 19 modules totaling 5,906 LOC, including 3,386 LOC of Hadoop/Hive/Impala helpers (`better_impyla.py`, `hs2_connection.py`, `hive_ddl_transform.py`, `hive_table_stats.py`), dead CLI scripts (`ora_Query_from_env.py`, `git_functions.py`, `redis_client.py`), trivial timing wrappers (`simple_timer.py`, 33 LOC), and a 723-LOC `misc_functions.py` catch-all.
- `src/goe/util/password_tools.py`: Implements AES-256-CBC + PKCS7 keyfile encryption/decryption that must remain byte-compatible with `$OFFLOAD_HOME` keyfiles and external C++ `pass_tool`, plus a 31-line `__main__` block to remove when relocating to `src/goe/config/password_tools.py`.
- `src/goe/util/goe_log_fh.py`: Uses `fsspec[gcs]` to stream logs to `gs://`, which is replaced by `google.cloud.storage.Blob.open("w")`.
- `pyproject.toml:25-115`: Declares unused packages (`PyYAML`, `tenacity`, `brotli`, `fsspec[gcs]`, `python-dateutil`, `azure-common`, `teradata` extra) and suppresses bug-masking Ruff rules at `pyproject.toml:230-271` (`E722`, `B006`, `B008`, `B012`, `B020`, `B023`, `B904`, `F504`, `F507`, `F811`, `RUF006`, `RUF012`, `RUF013`).
- `pyproject.toml:287-316`: Sets `disallow_untyped_defs = false` and `disallow_any_generics = false` globally without strict per-package enforcement on foundation modules.

### 3. Requirements

- **R1 (Utility Dissolution and Relocation)**: Delete `src/goe/util/{better_impyla,hs2_connection,ora_Query_from_env,misc_functions,simple_timer,git_functions,redis_client,hive_ddl_transform,kerberos,polling_thread}.py`, relocate Hive DDL transformation logic to `src/goe/offload/hadoop/hive_ddl.py`, and provide focused, well-typed primitives in `src/goe/util/{string_utils,concurrency,subprocess_utils,retry}.py`.
- **R2 (Dependency and Ruff Hygiene)**: Relocate `password_tools.py` and `gcp_credentials.py` to `src/goe/config/`, replace `fsspec` in `src/goe/util/goe_log_fh.py` with `google.cloud.storage.Blob.open`, remove unused dependencies and the `teradata` extra from `pyproject.toml`, remove blanket Ruff suppressions (`BLE001`, `TRY*`, `PTH*`, `RET*`, `SIM*`, `C4*`, `PIE*`, `RUF*`, `E722`, `B006`, `B008`, `B012`, `B020`, `B023`, `B904`, `F504`, `F507`, `F811`), and fix all resulting Ruff violations in `src/goe/util/` and `src/goe/config/`.
- **R3 (Strict Mypy Enforcement on Foundation Packages)**: Convert observability value objects to `FrozenBaseStruct` and pass `uv run mypy --strict` on `src/goe/typing.py`, `src/goe/serializers.py`, `src/goe/exceptions.py`, `src/goe/config/`, `src/goe/platform/`, and `src/goe/util/`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | `1.1` | `uv run pytest tests/unit/util/test_util_primitives.py -v` |
| R2 | `1.2` | `uv run pytest tests/unit/config/test_password_tools.py -v && uv run ruff check src/goe/util src/goe/config` |
| R3 | `1.3` | `uv run pytest tests/unit/test_strict_typing_gate.py -v && uv run mypy --strict src/goe/typing.py src/goe/serializers.py src/goe/exceptions.py src/goe/config src/goe/platform src/goe/util` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/util/test_util_primitives.py tests/unit/config/test_password_tools.py tests/unit/test_strict_typing_gate.py -v
uv run ruff format --check src/goe/typing.py src/goe/serializers.py src/goe/exceptions.py src/goe/config src/goe/platform src/goe/util src/goe/offload/hadoop/hive_ddl.py src/goe/observability tests/unit/util tests/unit/config
uv run ruff check src/goe/typing.py src/goe/serializers.py src/goe/exceptions.py src/goe/config src/goe/platform src/goe/util src/goe/offload/hadoop/hive_ddl.py src/goe/observability tests/unit/util tests/unit/config
uv run mypy --strict src/goe/typing.py src/goe/serializers.py src/goe/exceptions.py src/goe/config src/goe/platform src/goe/util
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Utility Dissolution, Dependency Cleanup, and Strict Foundation Typing

- [x] 1.1 Dissolve dead `src/goe/util/` modules, relocate `hive_ddl.py`, and create focused utility primitives ([tasks/1.1.md](tasks/1.1.md))
- [x] 1.2 Clean `pyproject.toml` dependencies and Ruff suppressions and fix `src/goe/util/` and `src/goe/config/` violations ([tasks/1.2.md](tasks/1.2.md))
- [x] 1.3 Enforce strict `mypy` across `typing.py`, `serializers.py`, `exceptions.py`, `config/`, `platform/`, and `util/` ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `util_dissolution_dependency_and_lint_hygiene_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `PasswordTools` retains 100% binary compatibility with AES-256-CBC + PKCS7 `$OFFLOAD_HOME` keyfiles; `GOELogFileHandle` uses `google.cloud.storage.Blob.open("w")` instead of `fsspec[gcs]`; foundation packages enforce `mypy --strict`.
- **Discoveries**: none yet.
- **Blockers**: `declarative_settings_options_and_error_model_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`util_dissolution_dependency_and_lint_hygiene_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `AGENTS.md`, `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/standards/python.md`, `.agents/bundles/knowledge/standards/testing.md`.
