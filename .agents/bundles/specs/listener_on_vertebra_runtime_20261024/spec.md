---
type: Spec
flow_id: listener_on_vertebra_runtime_20261024
title: "Chapter 10.5: Listener on Vertebra Runtime"
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
description: "Implements the programmatic Vertebra release gate (R1-R6), migrates the GOE Listener and CLI launcher from Granian onto Vertebra with LitestarPlugin and CgroupQuota worker sizing, and verifies end-to-end ASGI lifespan, CORS OPTIONS, streaming, and 64-way concurrency."
tags:
  - migration
  - listener
  - vertebra
  - asgi
  - runtime
parent_prd: prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024
depends_on:
  - durable_job_queue_listener_cache_and_mcp_20261024
research:
  - .agents/bundles/specs/prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/vertebra-and-runtime-evaluation.md
  - .agents/bundles/specs/prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/module-by-module-redesign.md
---

# Chapter 10.5: Listener on Vertebra Runtime

## Specification

### 1. Overview and Goals

This chapter replaces `granian` and `litestar-granian` (`GranianPlugin`) with `vertebra` and `vertebra.extensions.litestar.LitestarPlugin` once the Vertebra release gate (`R1`–`R6` in [Vertebra evaluation](../prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/vertebra-and-runtime-evaluation.md)) is satisfied:

1. **Programmatic Release-Gate Verifier (`src/goe/listener/vertebra_gate.py`)**: Implements `verify_vertebra_runtime_gate()` and structured `VertebraGateReport(FrozenBaseStruct)` / `VertebraCriterionResult(FrozenBaseStruct)` checking all six release-gate criteria:
   - `R1`: ASGI `lifespan.startup` and `lifespan.shutdown` protocol execution for mounted ASGI apps, including worker abort when `lifespan.startup.failed` is sent.
   - `R2`: `OPTIONS` CORS preflight and `HEAD` routing on mounted prefixes.
   - `R3`: Bundled `vertebra/bin/vertebra-server` binary inside installed wheels.
   - `R4`: 64-way concurrent request dispatch without `BatchBridge` channel deadlock.
   - `R5`: Clean public `vertebra.supervisor` exports and preservation of caller-supplied `VERTEBRA_*` environment variables in `vtb run`.
   - `R6`: Published `cp312`–`cp314` wheel metadata resolution for Linux `x86_64`/`aarch64` and macOS `arm64`/`x86_64`.
2. **ASGI Entrypoint, `LitestarPlugin`, and CLI Launcher Migration (`src/goe/listener/asgi.py`, `src/goe/listener/app.py`, `src/goe/cli/commands/listener.py`, `pyproject.toml`)**: Ensures `goe.listener.asgi:app` is constructed without network or disk I/O at import time, replaces `GranianPlugin` with `LitestarPlugin` in `src/goe/listener/app.py`, updates `goe listener start` (`src/goe/cli/commands/listener.py`) to run `DurableJobWorker` directly under `--worker-only` and launch Vertebra (`vtb run goe.listener.asgi:app --interface asgi` or `Supervisor`) with `--topology`, `--workers`, `--threads`, TLS, and drain settings sized via `CgroupQuota`, deletes `src/goe/listener/server.py` and `src/goe/listener/__main__.py`, and swaps `granian`/`litestar-granian` for `vertebra` in `pyproject.toml`.
3. **Vertebra Runtime Configuration and End-to-End Verification Suite (`src/goe/listener/config/application.py`, `templates/conf/offload.env.template.common`, `tests/unit/listener/test_vertebra_runtime_integration.py`)**: Adds explicit Vertebra topology, thread, and drain settings (`topology`, `threads`, `drain_timeout_seconds`, `shutdown_timeout_seconds`, `to_vertebra_env()`) to `ListenerSettings`, documents the environment variables in `templates/conf/offload.env.template.common`, and exercises the full Listener ASGI lifecycle, CORS `OPTIONS` preflight, `HEAD` probes, SSE/chunked streaming, and 64-way concurrent requests in `tests/unit/listener/test_vertebra_runtime_integration.py`.

### 2. Code Analysis Summary

- `src/goe/listener/app.py:16, 45`: Imports `from litestar_granian import GranianPlugin` and registers `GranianPlugin()` in `plugins`.
- `src/goe/listener/asgi.py:1-14`: Calls `load_env()` at import time and re-exports `app` and `create_app`. Vertebra's Rust ingress (`src/rs/vertebra-http/src/main.rs:197-213`) requires `VERTEBRA_APP` (`goe.listener.asgi:app`) to resolve to an application instance whose construction performs zero blocking network or database I/O before lifespan startup.
- `src/goe/cli/commands/listener.py:16-26, 178-204`: Lazily imports `Granian` and `Interfaces` from `granian`, ignores `--worker-only` by printing `"Starting GOE Listener worker process..."` and returning immediately (`lines 191-193`), and calls `Granian("goe.listener.asgi:app", address=resolved_host, port=resolved_port, interface=Interfaces.ASGI, workers=resolved_workers, reload=reload).serve()`.
- `src/goe/listener/server.py:1-32` and `src/goe/listener/__main__.py:1-23`: Duplicate Granian launcher wrappers (`run_granian_server` and `run_listener`) superseded by `goe listener start`.
- `src/goe/listener/config/application.py:19-67`: Lacks Vertebra topology (`shm` vs `embedded`), thread pool, and graceful drain timeout settings.

### 3. Requirements

- **R1 (Programmatic Vertebra Release Gate)**: Implement `verify_vertebra_runtime_gate()` in `src/goe/listener/vertebra_gate.py` returning `VertebraGateReport(FrozenBaseStruct)` with per-criterion `VertebraCriterionResult(FrozenBaseStruct)` entries for `R1` through `R6`, raising `VertebraReleaseGateError` when `require_passed=True` and any criterion fails.
- **R2 (Vertebra CLI Launcher, `--worker-only`, and Granian Removal)**: Replace `Granian` and `GranianPlugin` with `vertebra` (`LitestarPlugin` in `src/goe/listener/app.py` and `vtb run goe.listener.asgi:app --interface asgi` in `src/goe/cli/commands/listener.py`), wire `--worker-only` to run `DurableJobWorker.run_forever()` without starting HTTP ingress, delete `src/goe/listener/server.py` and `src/goe/listener/__main__.py`, and replace `granian` and `litestar-granian` with `vertebra` in `pyproject.toml`.
- **R3 (Vertebra Runtime Settings and End-to-End ASGI Integration Verification)**: Extend `ListenerSettings` (`src/goe/listener/config/application.py`) and `templates/conf/offload.env.template.common` with Vertebra topology (`shm` default), worker/thread sizing clamped via `CgroupQuota`, and drain timeouts, and verify end-to-end ASGI lifespan startup/shutdown, startup-failure propagation, `OPTIONS` CORS preflight, `HEAD` routing, SSE/chunked streaming, and 64-way concurrent request handling in `tests/unit/listener/test_vertebra_runtime_integration.py`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | `1.1` | `uv run pytest tests/unit/listener/test_vertebra_gate.py -v` |
| R2 | `1.2` | `uv run pytest tests/unit/listener/test_listener_cli_vertebra.py -v` |
| R3 | `1.3` | `uv run pytest tests/unit/listener/test_vertebra_runtime_integration.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/listener/test_vertebra_gate.py tests/unit/listener/test_listener_cli_vertebra.py tests/unit/listener/test_vertebra_runtime_integration.py -v
uv run ruff format --check src/goe/listener src/goe/cli/commands/listener.py tests/unit/listener
uv run ruff check src/goe/listener src/goe/cli/commands/listener.py tests/unit/listener
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Vertebra Release Gate, Runtime Migration, and End-to-End Verification
- [ ] 1.1 Implement Programmatic Vertebra Release-Gate Verifier ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Migrate Listener App and CLI Launcher from Granian to Vertebra ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Configure Vertebra Runtime Settings and Verify End-to-End Concurrency and Lifespan ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `listener_on_vertebra_runtime_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: Gate runtime cutover on `verify_vertebra_runtime_gate()` (`R1`–`R6`); default to `--topology shm` unless `R4` embedded bridge verification passes; keep `vertebra` strictly confined to the Listener layer (`src/goe/listener/` and `src/goe/cli/commands/listener.py`); run `DurableJobWorker` directly under `goe listener start --worker-only`.
- **Discoveries**: none yet.
- **Blockers**: `durable_job_queue_listener_cache_and_mcp_20261024` (Chapter 10.4) and the published Vertebra release satisfying `R1`–`R6` must complete first.
- **Next exact step**: execute task `1.1` (`listener_on_vertebra_runtime_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/listener/index.md`, `.agents/bundles/knowledge/listener/rest-api.md`, `.agents/bundles/knowledge/operations/cloud-run-deployment.md`.
