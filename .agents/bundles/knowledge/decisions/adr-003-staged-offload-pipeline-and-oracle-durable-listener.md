---
type: decision
title: "ADR-003: Staged OffloadPipeline, Vertebra Listener & Oracle-Only Durable Job Queue"
description: Decompose offload orchestration into a 4-stage immutable OffloadPipeline and run the Litestar/MCP Listener on Vertebra with an Oracle-only durable job queue.
status: stable
tags:
  - decision
  - adr
  - orchestration
  - listener
  - vertebra
  - mcp
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: pipeline
    resource: src/goe/orchestration/pipeline.py::OffloadPipeline
    title: 4-Stage Offload Pipeline
  - id: job-store
    resource: src/goe/listener/jobs/store.py::OracleJobStore
    title: Oracle-Backed Durable Listener Job Store
  - id: vertebra-gate
    resource: src/goe/listener/vertebra_gate.py::verify_vertebra_runtime_gate
    title: Vertebra Runtime Verification Gate
  - id: listener-mcp
    resource: src/goe/listener/mcp.py::build_mcp_config
    title: Native Litestar-MCP Configuration and ConfirmationGate
---

# ADR-003: Staged OffloadPipeline, Vertebra Listener & Oracle-Only Durable Job Queue

<!-- truth: start -->
- **Status**: Accepted (`stable`).
- **Decision**: Execute all offloads through the 4-stage `OffloadPipeline` (`DiscoveryStage -> BoundaryStage -> PlanResolutionStage -> OffloadPlanExecutor`) with explicit `ExecutionContext`/`ExecutionSink`, serve the Litestar REST + `litestar-mcp 0.16.0` Listener via Vertebra (`goe.listener.asgi:app`), and persist all asynchronous Listener jobs exclusively in Oracle (`OracleJobStore` on `GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS`).[^pipeline][^job-store][^vertebra-gate][^listener-mcp]
<!-- truth: end -->

## Context

Legacy orchestration coupled discovery, boundary math, type resolution, and execution inside stateful `OffloadOperation` / `OffloadSourceTable` classes that mutated module globals (`log_fh`, `options`), making dry-run previews and concurrent in-process offloads unsafe. In the Listener, external Redis/Valkey queues added deployment dependencies, while an in-memory or SQLite fallback lost jobs across container restarts or split brain across multi-pod deployments.

## Alternatives Considered

| Option | Summary | Why Rejected / Selected |
| :--- | :--- | :--- |
| **Selected: 4-Stage `OffloadPipeline` + Vertebra + Oracle-Only `OracleJobStore` + Native `litestar-mcp`** | Thread `ExecutionContext` through immutable `OffloadPlan` stages; run Litestar on Vertebra; persist jobs in `GOE_LISTENER_JOBS` via `FOR UPDATE SKIP LOCKED`; expose declarative `@mcp_tool` controllers with `ConfirmationGate`. | **Selected**: Enables dry-run `OffloadPipeline.plan()` previews, thread-safe concurrent offloads, zero-extra-infra HA job persistence in the existing `GOE_REPO` Oracle schema, and authenticated MRTR-gated MCP operations. |
| **Retain `SqliteJobStore` Fallback or `litestar-queues` In-Memory Queue** | Allow SQLite or in-memory queues when Oracle is unconfigured. | **Rejected**: GOE requires an Oracle repository (`GOE_REPO`) to operate; maintaining a second SQLite dialect added dead code and couldn't coordinate multi-worker leases across containers. |
| **Direct Core Engine Import of `vertebra`** | Import `vertebra` directly inside `src/goe/orchestration/` or `src/goe/platform/`. | **Rejected**: Couples CLI-only installations to the ASGI server package; keeping `src/goe/platform/` pure-Python and invoking Vertebra at the Listener process boundary (`vertebra_gate.py`) keeps the core engine dependency-light. |

## Consequences

- `OffloadPipeline.plan()` produces a complete `OffloadPlan` without mutating backend tables, powering both CLI `--dry-run` and Listener `/api/orchestration/offload/preview/` (`preview_offload_plan` MCP tool).[^pipeline]
- `OracleJobStore` claims jobs with `SELECT ... FOR UPDATE SKIP LOCKED` + `cursor.fetchmany(limit)` and supports cooperative `CANCEL_REQUESTED` cancellation via `_CooperativeCancelSink`.[^job-store]
- Mutating MCP tools (`execute_offload`, `reset_offload_metadata`, `apply_schema_sync`, `cancel_offload_job`) enforce handler-level `require_mcp_confirmation` (`MCPInputRequiredResult` + HMAC-SHA256 `confirmation_token`), while direct HTTP REST `POST` endpoints remain un-gated for automation clients.[^listener-mcp]

[^pipeline]: `src/goe/orchestration/pipeline.py::OffloadPipeline` — Staged offload discovery, boundary resolution, planning, and execution pipeline.
[^job-store]: `src/goe/listener/jobs/store.py::OracleJobStore` — Oracle-backed durable job queue with `SKIP LOCKED` claiming and cooperative cancellation.
[^vertebra-gate]: `src/goe/listener/vertebra_gate.py::verify_vertebra_runtime_gate` — Vertebra runtime gate and ASGI process command builder.
[^listener-mcp]: `src/goe/listener/mcp.py::build_mcp_config` — Native `litestar-mcp 0.16.0` configuration and HMAC `ConfirmationGate`.
