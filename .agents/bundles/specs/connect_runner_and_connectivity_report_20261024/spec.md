---
type: Spec
flow_id: connect_runner_and_connectivity_report_20261024
title: "Chapter 5.5: Connect Runner and Connectivity Report"
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
description: "Replace imperative, global-state goe connect modules with immutable CheckDetail, CheckResult, and ConnectivityReport structs and a concurrent ConnectRunner shared by the CLI and Listener."
tags: [refactor, cli, adapters, typing]
parent_prd: prd_05_foundation_typing_settings_and_adapter_reduction_20261024
depends_on: [util_dissolution_dependency_and_lint_hygiene_20261024]
research:
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/goe-architecture-redesign.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 5.5: Connect Runner and Connectivity Report

## Specification

### 1. Overview and Goals

This chapter replaces the stateful, sequential `src/goe/connect/` modules with a stateless, concurrent connectivity verification architecture shared by the `goe connect` CLI command and the Listener `/api/v1/system/connectivity` endpoint:

1. **Immutable Connectivity Report Models (`src/goe/connect/models.py`)**: Define `CheckDetail`, `CheckResult`, and `ConnectivityReport` as `FrozenBaseStruct` subclasses with a deterministic text formatter matching the golden CLI output and JSON serialization via `goe.serializers`.
2. **Concurrent `ConnectRunner` (`src/goe/connect/runner.py`)**: Execute independent frontend (Oracle/MSSQL), backend (BigQuery/Snowflake/Synapse/Hadoop), storage/DFS (`GOEDfs`), transport (DuckDB 2.0 + `oracle` + `httpfs`, Spark, Dataproc, Livy, Thriftserver), SSH, and repository (`OFFLOAD_REPO`) connectivity probes concurrently via `run_bounded`, trapping `Exception` (and never `BaseException`) per probe so an individual host or service failure never aborts remaining probes. Delete `src/goe/connect/{connect,connect_frontend,connect_backend,connect_transport,connect_functions,connect_constants}.py`.
3. **CLI and Listener Wiring (`src/goe/cli/commands/connect.py`, `src/goe/listener/controllers/system.py`)**: Wire `goe connect` and Listener `GET /api/v1/system/connectivity` directly to `ConnectRunner`, eliminating subprocess shelling-out and thread-unsafe global `failures`/`warnings` flags.

### 2. Code Analysis Summary

- `src/goe/connect/connect.py:65-66`: Uses module-global `warnings: bool = False` and `failures: bool = False` flags mutated via `src/goe/connect/connect_functions.py` (`success()`, `warning()`, `failure()`), making concurrent or in-process Listener invocations thread-unsafe.
- `src/goe/connect/connect.py:73-119`: `test_ssh()` iterates over SSH hosts sequentially and raises on the first `subprocess.check_output` failure, aborting checks for all remaining hosts in the cluster (Defect Ledger item C.23).
- `src/goe/connect/connect.py:55-62`: Parses `/etc/os-release` by reading `lines[0]` rather than `PRETTY_NAME=`.
- `src/goe/connect/connect_frontend.py`: Concatenates raw strings into `SYS_CONTEXT` SQL queries instead of using bind parameters.
- `src/goe/connect/connect_transport.py`: Runs removed `run_sqoop_tests` and lacks a probe for DuckDB 2.0 + `oracle` + `httpfs` transport availability.

### 3. Requirements

- **R1 (Immutable Connectivity Models and Serializers)**: `src/goe/connect/models.py` must define `CheckDetail(FrozenBaseStruct)`, `CheckResult(FrozenBaseStruct)`, and `ConnectivityReport(FrozenBaseStruct)` with `format_text()` matching the golden CLI output format and `to_json()` / `to_json_bytes()` routing through `goe.serializers`.
- **R2 (Stateless Concurrent ConnectRunner)**: `src/goe/connect/runner.py` must implement `ConnectRunner` executing independent frontend, backend, storage/DFS, Spark/Dataproc/DuckDB transport, SSH, and repository probes via `run_bounded`, trapping `Exception` (and never `BaseException` such as `KeyboardInterrupt` or `SystemExit`), evaluating every configured SSH host even when an earlier host fails, using parameterized queries for frontend checks, and deleting `src/goe/connect/{connect,connect_frontend,connect_backend,connect_transport,connect_functions,connect_constants}.py`.
- **R3 (CLI and Listener Integration)**: `src/goe/cli/commands/connect.py` and Listener `/api/v1/system/connectivity` (`src/goe/listener/controllers/system.py` and `src/goe/listener/services/system.py`) must execute `ConnectRunner` directly, returning exit code `0` when `report.passed` is `True` and `1` when any check fails.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | `1.1` | `uv run pytest tests/unit/connect/test_models.py -v` |
| R2 | `1.2` | `uv run pytest tests/unit/connect/test_runner.py -v` |
| R3 | `1.3` | `uv run pytest tests/unit/cli/test_connect_command.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/connect/test_models.py tests/unit/connect/test_runner.py tests/unit/cli/test_connect_command.py -v
uv run ruff format --check src/goe/connect src/goe/cli/commands/connect.py src/goe/listener/controllers/system.py src/goe/listener/services/system.py tests/unit/connect tests/unit/cli/test_connect_command.py
uv run ruff check src/goe/connect src/goe/cli/commands/connect.py src/goe/listener/controllers/system.py src/goe/listener/services/system.py tests/unit/connect tests/unit/cli/test_connect_command.py
uv run mypy src/goe/connect src/goe/cli/commands/connect.py src/goe/listener/controllers/system.py src/goe/listener/services/system.py
uv run python tools/verify_architecture.py
uv run python -c "import ast,sys; is_priv=lambda n:n.startswith('_') and not (n.startswith('__') and n.endswith('__')); bad=[(p,getattr(s,'name','<module>'),f.name) for p in sys.argv[1:] for s in ast.walk(ast.parse(open(p).read())) if isinstance(s,(ast.Module,ast.ClassDef)) for funcs in [[n for n in s.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]] for i,f in enumerate(funcs) if not is_priv(f.name) and any(is_priv(g.name) for g in funcs[:i])]; assert not bad, bad" src/goe/connect/models.py src/goe/connect/runner.py src/goe/cli/commands/connect.py
```

## Implementation Plan

### Phase 1: Connectivity Models, Concurrent Runner, and CLI/Listener Wiring

- [x] 1.1 Implement `CheckDetail`, `CheckResult`, and `ConnectivityReport` in `src/goe/connect/models.py` ([tasks/1.1.md](tasks/1.1.md))
- [x] 1.2 Implement `ConnectRunner` in `src/goe/connect/runner.py` and delete legacy `connect_*.py` modules ([tasks/1.2.md](tasks/1.2.md))
- [x] 1.3 Wire `src/goe/cli/commands/connect.py` and Listener `/api/v1/system/connectivity` to `ConnectRunner` ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `connect_runner_and_connectivity_report_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `ConnectivityReport`, `CheckResult`, and `CheckDetail` inherit from `FrozenBaseStruct`; `ConnectRunner` uses `run_bounded` and traps `Exception` (never `BaseException`); legacy `connect_*.py` files are deleted cleanly.
- **Discoveries**: none yet.
- **Blockers**: `util_dissolution_dependency_and_lint_hygiene_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`connect_runner_and_connectivity_report_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `AGENTS.md`, `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/standards/python.md`, `.agents/bundles/knowledge/standards/testing.md`.
