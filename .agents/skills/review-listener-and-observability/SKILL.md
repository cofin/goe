---
name: review-listener-and-observability
description: "Use when reviewing GOE changes touching src/goe/listener/, src/goe/cli/commands/listener.py, or src/goe/observability/."
disable-model-invocation: false
---

# Review: Litestar Listener, Vertebra Runtime, Durable Jobs, MCP & OpenTelemetry (`LST`)

<!-- truth: start -->
- `create_app` (`src/goe/listener/app.py`) configures Litestar REST controllers, `litestar-security` (`x-goe-console-key` via `secrets.compare_digest` across `/api/*` and `POST /mcp`, with `/api/system/status/`, `/docs`, and `/schema` public), and `build_mcp_config()` (`src/goe/listener/mcp.py`).
- `OracleJobStore` (`src/goe/listener/jobs/store.py`) backed by `OracleDatabaseRegistry.for_options(config)` is the sole durable job store (`SqliteJobStore` is removed), claiming jobs on `GOE_LISTENER_JOBS` with `SELECT ... FOR UPDATE SKIP LOCKED` + `cursor.fetchmany(limit)` and supporting cooperative `CANCEL_REQUESTED` cancellation via `_CooperativeCancelSink` (`src/goe/listener/jobs/worker.py`).
- Mutating MCP tools (`execute_offload`, `reset_offload_metadata`, `apply_schema_sync`, `cancel_offload_job`) enforce handler-level `require_mcp_confirmation` (`MCPInputRequiredResult` multi-round-trip challenge + HMAC-SHA256 `confirmation_token`), while direct HTTP REST `POST` callers remain un-gated.
- Core GOE modules never import `vertebra`; `src/goe/listener/vertebra_gate.py` (`verify_vertebra_runtime_gate` + `build_vertebra_command`) validates and launches `vertebra run goe.listener.asgi:app`.
- `ObservabilityRuntime` (`src/goe/observability/runtime.py`) is a zero-SDK-import no-op when `GOE_OTEL_ENABLED=false` and bridges `ExecutionId` to W3C `traceparent`/`baggage` and SQLSpec `CorrelationContext` when enabled.
<!-- truth: end -->

## Workflow

1. **Load Suppression & Checklist Catalogs**:
   - Read [Checklist (`LST-01..06`)](references/checklist.md) and [False-Positive Suppressions (`FP-LST-01..04`)](references/false-positive-suppressions.md) before flagging any finding.
2. **Inspect Changed Files & Surrounding Context**:
   - Read the full target files around every diff hunk in this domain to verify callers, types, resource cleanup, and concurrency invariants.
3. **Evaluate Two-Axis Conformance**:
   - Check spec/behavior correctness, public-seam test strength, and adherence to `LST-01..06` and `tools/verify_architecture.py`.
4. **Filter Against Suppressions**:
   - Drop any candidate finding matching a `DO NOT FLAG` rule in [False-Positive Suppressions](references/false-positive-suppressions.md) or lacking a concrete failure mode.

## Guardrails

- Never flag stylistic preferences already enforced by `ruff` or `mypy` unless a real defect is present.
- Never propose inline `#` comments inside function/method bodies or nested function-scoped imports (both violate `tools/verify_architecture.py`).
- Anchor every finding to an exact `path/to/file.py:line` range, rule ID (`LST-NN`), concrete failure scenario, and minimal fix.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/listener tests/unit/observability -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Return structured findings citing `[<PREFIX>-NN] path/to/file.py:line — <summary>`, severity (`blocking` | `important` | `nit`), reproduction/failure trace, and concrete fix, or state that zero issues were found across `LST-01..06`.
