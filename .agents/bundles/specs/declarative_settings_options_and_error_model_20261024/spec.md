---
type: Spec
flow_id: declarative_settings_options_and_error_model_20261024
title: "Chapter 5.3: Declarative Settings, Options, and Error Model"
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
description: "Establish the canonical GOEError exception hierarchy, side-effect-free GOESettings and sub-config structs, typed OffloadOptions and TestModeFaults structs, and composable Click option-group decorators across all CLI commands."
tags: [refactor, configuration, cli, typing]
parent_prd: prd_05_foundation_typing_settings_and_adapter_reduction_20261024
depends_on: [core_typing_serializers_platform_and_architecture_gate_20261024]
research:
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/goe-architecture-redesign.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 5.3: Declarative Settings, Options, and Error Model

## Specification

### 1. Overview and Goals

This chapter replaces imperative, side-effect-heavy configuration loading and duplicated CLI/Listener option schemas with a declarative, immutable model built on `FrozenBaseStruct` from `goe.typing`:

1. **Canonical Error Hierarchy (`src/goe/exceptions.py`)**: Replace the flat two-class `src/goe/exceptions.py` module with a structured `GOEError` root hierarchy (`ConfigurationError`, `ValidationError`, `AuthenticationError`, `FrontendError`, `BackendError`, `TransportError`, `PersistenceError`, `OrchestrationError`) carrying structured `code`, `details`, and `exit_code` attributes while keeping CLI exit code semantics (`0`, `1`, `2`) intact.
2. **Side-Effect-Free Settings (`src/goe/config/settings.py`)**: Introduce immutable `GOESettings(FrozenBaseStruct)` and typed domain sub-configs (`OracleConfig`, `BigQueryConfig`, `SnowflakeConfig`, `SynapseConfig`, `HadoopConfig`, `SparkTransportConfig`, `ListenerConfig`, `ObservabilityConfig`) validated via `msgspec.Meta` constraints and loaded from environment variables and tiered `offload.env` discovery (`src/goe/config/config_file.py`). Settings construction performs zero network I/O, zero `oracledb.init_oracle_client()` calls, and zero `random.choice()` mutations of multi-host CSV lists, retiring `src/goe/config/orchestration_config.py`, `src/goe/config/orchestration_defaults.py`, `src/goe/config/config_validation_functions.py`, and `src/goe/config/option_descriptions.py`.
3. **Typed Operational Options (`src/goe/config/options.py`)**: Replace mutable `Namespace`-based option objects, `from_options_dict`, Listener `OffloadOptions` duplication, and string-parsed `--dev-error` tokens with `OffloadOptions(FrozenBaseStruct)` and `TestModeFaults(FrozenBaseStruct)` backed by a declarative `OptionSpec(FrozenBaseStruct)` catalog in `src/goe/config/option_registry.py`.
4. **Composable CLI Option Decorators (`src/goe/cli/options.py`)**: Replace `src/goe/cli/config.py` and imperative flag registration across `src/goe/cli/commands/{offload,connect,validate,sync,report,listener,logmgr}.py` with composable Click option-group decorators (`@common_options`, `@table_target_options`, `@partition_options`, `@transport_options`, `@column_transform_options`) including the missing OpenTelemetry CLI flags and aligned Listener port (`8000`) and heartbeat (`60s`) defaults.

### 2. Code Analysis Summary

- `src/goe/exceptions.py:1-28`: Defines only `OffloadException` and `OffloadOptionError` (`OptionValueError = OffloadOptionError`). Subsystem exceptions are scattered across ~45 files with inconsistent base classes, preventing uniform CLI exit-code mapping and Listener HTTP problem detail serialization.
- `src/goe/config/config_file.py:25-98`: Implements `find_environment_file()` and `load_env()` with tiered `offload.env` discovery (`GOE_CONFIG_FILE` / `OFFLOAD_ENV_FILE`, `$OFFLOAD_HOME/conf/offload.env`, upward `dotenv.find_dotenv()`, and `/opt/goe/offload/conf/offload.env` / `/u01/app/goe/offload/conf/offload.env`) and automatic `OFFLOAD_HOME` derivation when parent directory is `conf`.
- `src/goe/config/orchestration_config.py:120-290`: `OrchestrationConfig.__init__` connects to live databases, invokes global `oracledb.init_oracle_client()`, and mutates multi-host CSV strings in place via `random.choice()`. `src/goe/orchestration/execution.py:442` mutates `OrchestrationConfig` at runtime via `override_offload_dfs_config(...)`.
- `src/goe/config/orchestration_defaults.py`, `src/goe/config/config_validation_functions.py`, `src/goe/config/option_descriptions.py`: Separate defaults, imperative validators, and help text strings from the config schema.
- `src/goe/cli/common.py` and `src/goe/cli/commands/{offload,connect,validate,sync,report,listener,logmgr}.py`: Duplicate option definitions across CLI commands, `src/goe/cli/config.py`, `src/goe/orchestration/cli_entry_points.py`, and `src/goe/listener/schemas.py:OffloadOptions`, while omitting 5 OpenTelemetry settings and letting Listener port (`8085` vs `8000`) and heartbeat (`30s` vs `60s`) defaults drift from `src/goe/listener/config/application.py:27`.

### 3. Requirements

- **R1 (Canonical Exception Hierarchy)**: `src/goe/exceptions.py` must define `GOEError(Exception)` as the root exception with `code: str`, `details: dict[str, object]`, and `exit_code: int = 1`, along with domain subclasses `ConfigurationError(exit_code=2)`, `ValidationError(exit_code=2)`, `AuthenticationError(exit_code=1)`, `FrontendError(exit_code=1)`, `BackendError(exit_code=1)`, `TransportError(exit_code=1)`, `PersistenceError(exit_code=1)`, and `OrchestrationError(exit_code=1)`.
- **R2 (Side-Effect-Free Declarative Settings)**: `src/goe/config/settings.py` must define `GOESettings(FrozenBaseStruct)` and sub-configs (`OracleConfig`, `BigQueryConfig`, `SnowflakeConfig`, `SynapseConfig`, `HadoopConfig`, `SparkTransportConfig`, `ListenerConfig`, `ObservabilityConfig`) using `msgspec.Meta` constraints and `GOESettings.from_env()` integrated with `src/goe/config/config_file.py`. Construction must never open network sockets, initialize Oracle Thick client globally, or mutate host lists with `random.choice()`. `src/goe/config/orchestration_config.py`, `src/goe/config/orchestration_defaults.py`, `src/goe/config/config_validation_functions.py`, and `src/goe/config/option_descriptions.py` must be deleted, and `templates/conf/offload.env.template.*` must be reconciled with `GOESettings`.
- **R3 (Typed OffloadOptions and TestModeFaults)**: `src/goe/config/options.py` must define `OffloadOptions(FrozenBaseStruct)` and `TestModeFaults(FrozenBaseStruct)` backed by `OptionSpec(FrozenBaseStruct)` in `src/goe/config/option_registry.py`, replacing `from_options_dict`, string-parsed `--dev-error` tokens, and `src/goe/listener/schemas.py:OffloadOptions`, while aligning `src/goe/listener/config/application.py` with `ListenerConfig`.
- **R4 (Composable CLI Option Group Decorators)**: `src/goe/cli/options.py` must provide `@common_options`, `@table_target_options`, `@partition_options`, `@transport_options`, and `@column_transform_options` decorators derived from `OptionSpec`, wire them into `src/goe/cli/commands/{offload,connect,validate,sync,report,listener,logmgr}.py` and `src/goe/orchestration/cli_entry_points.py`, expose all OpenTelemetry flags in `src/goe/cli/common.py`, and delete `src/goe/cli/config.py`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | `1.1` | `uv run pytest tests/unit/test_exceptions.py -v` |
| R2 | `1.2` | `uv run pytest tests/unit/config/test_settings.py -v` |
| R3 | `1.3` | `uv run pytest tests/unit/config/test_options.py -v` |
| R4 | `1.4` | `uv run pytest tests/unit/cli/test_cli_options.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/test_exceptions.py tests/unit/config/test_settings.py tests/unit/config/test_options.py tests/unit/cli/test_cli_options.py -v
uv run ruff format --check src/goe/exceptions.py src/goe/config src/goe/cli src/goe/listener/schemas.py src/goe/listener/config/application.py src/goe/orchestration/cli_entry_points.py tests/unit/test_exceptions.py tests/unit/config tests/unit/cli
uv run ruff check src/goe/exceptions.py src/goe/config src/goe/cli src/goe/listener/schemas.py src/goe/listener/config/application.py src/goe/orchestration/cli_entry_points.py tests/unit/test_exceptions.py tests/unit/config tests/unit/cli
uv run mypy src/goe
uv run python tools/verify_architecture.py
uv run python -c "import ast,sys; is_priv=lambda n:n.startswith('_') and not (n.startswith('__') and n.endswith('__')); bad=[(p,getattr(s,'name','<module>'),f.name) for p in sys.argv[1:] for s in ast.walk(ast.parse(open(p).read())) if isinstance(s,(ast.Module,ast.ClassDef)) for funcs in [[n for n in s.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]] for i,f in enumerate(funcs) if not is_priv(f.name) and any(is_priv(g.name) for g in funcs[:i])]; assert not bad, bad" src/goe/exceptions.py src/goe/config/settings.py src/goe/config/options.py src/goe/config/option_registry.py src/goe/cli/options.py
```

## Implementation Plan

### Phase 1: Error Model, Declarative Settings, Options, and CLI Option Decorators

- [ ] 1.1 Establish canonical `GOEError` exception hierarchy in `src/goe/exceptions.py` ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement side-effect-free `GOESettings` and domain config structs in `src/goe/config/settings.py` ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Implement `OffloadOptions`, `TestModeFaults`, and `OptionSpec` registry in `src/goe/config/options.py` ([tasks/1.3.md](tasks/1.3.md))
- [ ] 1.4 Build composable Click option-group decorators in `src/goe/cli/options.py` and wire CLI commands ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `declarative_settings_options_and_error_model_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `GOESettings` and `OffloadOptions` inherit from `FrozenBaseStruct`; settings construction performs zero network I/O, zero Oracle Thick client initialization, and zero `random.choice()` host mutation; `GOEError` carries `exit_code` (`1` for operational errors, `2` for configuration/validation errors).
- **Discoveries**: none yet.
- **Blockers**: `core_typing_serializers_platform_and_architecture_gate_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`declarative_settings_options_and_error_model_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `AGENTS.md`, `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/operations/configuration-and-env.md`, `.agents/bundles/knowledge/standards/python.md`.
