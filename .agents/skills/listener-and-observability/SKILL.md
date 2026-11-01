---
name: listener-and-observability
description: "Use when working on the GOE Listener (src/goe/listener/), Vertebra runtime gate, OracleJobStore, DurableJobWorker, ListenerCache, litestar-mcp tools/resources/prompts/ConfirmationGate, or OpenTelemetry observability (src/goe/observability/)."
disable-model-invocation: false
---

# Litestar Listener, Vertebra Runtime, Durable Jobs, MCP & OpenTelemetry

<!-- truth: start -->
- `create_app` (`src/goe/listener/app.py`) configures Litestar REST controllers, `litestar-security` (`x-goe-console-key` via `secrets.compare_digest` across `/api/*` and `POST /mcp`, with `/api/system/status/`, `/docs`, and `/schema` public), and `build_mcp_config()` (`src/goe/listener/mcp.py`).
- `OracleJobStore` (`src/goe/listener/jobs/store.py`) backed by `OracleDatabaseRegistry.for_options(config)` is the sole durable job store (`SqliteJobStore` is removed), claiming jobs on `GOE_LISTENER_JOBS` with `SELECT ... FOR UPDATE SKIP LOCKED` + `cursor.fetchmany(limit)` and supporting cooperative `CANCEL_REQUESTED` cancellation via `_CooperativeCancelSink` (`src/goe/listener/jobs/worker.py`).
- Mutating MCP tools (`execute_offload`, `reset_offload_metadata`, `apply_schema_sync`, `cancel_offload_job`) enforce handler-level `require_mcp_confirmation` (`MCPInputRequiredResult` multi-round-trip challenge + HMAC-SHA256 `confirmation_token`), while direct HTTP REST `POST` callers remain un-gated.
- Core GOE modules never import `vertebra`; `src/goe/listener/vertebra_gate.py` (`verify_vertebra_runtime_gate` + `build_vertebra_command`) validates and launches `vertebra run goe.listener.asgi:app`.
- `ObservabilityRuntime` (`src/goe/observability/runtime.py`) is a zero-SDK-import no-op when `GOE_OTEL_ENABLED=false` and bridges `ExecutionId` to W3C `traceparent`/`baggage` and SQLSpec `CorrelationContext` when enabled.
<!-- truth: end -->

## Workflow

1. **Ground in Domain Seams & Knowledge**:
   - Read [Patterns & Seams](references/patterns-and-seams.md) and the linked OKF v0.2 chapters before editing production modules:
- [Listener REST API & MCP Architecture](../../bundles/knowledge/listener/rest-api.md)
- [Listener Durable Job Queue & Bounded Caching](../../bundles/knowledge/listener/worker-and-redis.md)
- [OpenTelemetry Observability](../../bundles/knowledge/operations/observability.md)
- [Cloud Run & Container Deployment](../../bundles/knowledge/operations/cloud-run-deployment.md)
- [ADR-003: Staged OffloadPipeline, Vertebra Listener & Oracle Durable Queue](../../bundles/knowledge/decisions/adr-003-staged-offload-pipeline-and-oracle-durable-listener.md)
2. **Verify Public Seams First**:
   - Classify touched dependencies (`In-process`, `Local-substitutable`, `Remote-owned`, `External boundary`) and write or update unit tests in the canonical `tests/unit/` module before changing implementation behavior.
3. **Implement Within Architectural Boundaries**:
   - Preserve `FrozenBaseStruct(..., frozen=True)` / `BaseStruct` contracts, route JSON through `goe.serializers`, keep imports at module top-level (or `if TYPE_CHECKING:` / `import_optional_dependency`), and place public methods/functions above `_` private helpers.
4. **Run Focused & Aggregate Verification**:
   - Run the focused pytest suite, `uv run python tools/verify_architecture.py`, and `make lint`.

## Guardrails

- Never violate the 6 AST/token rules in `tools/verify_architecture.py` (`raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import`, `member-ordering`, `inline-comment`).
- Never introduce inline `#` comments inside function or method bodies; document rationale in Google-style docstrings.
- Never add backward-compatibility shims, unused re-exports, or standalone `test_*_remediation.py` files; place tests in the canonical `tests/unit/` file for the module under test.
- Check [Review Checklist](../review-listener-and-observability/references/checklist.md) and [False-Positive Suppressions](../review-listener-and-observability/references/false-positive-suppressions.md) before finalizing changes.

## Validation

```bash
GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run --no-sync pytest tests/unit/listener tests/unit/observability -q
uv run python tools/verify_architecture.py
make lint
```

## Output

Summarize modified files, public-seam tests executed, and exact exit statuses for `pytest`, `verify_architecture.py`, and `make lint`.
