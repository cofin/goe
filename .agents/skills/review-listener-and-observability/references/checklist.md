# Review Checklist: Litestar Listener, Vertebra Runtime, Durable Jobs, MCP & OpenTelemetry (`LST`)

## `LST-01`: Authenticated REST & `POST /mcp` (`x-goe-console-key`)

All `/api/*` and `POST /mcp` routes (including `GOEPromptController` and `GOEResourcesController`) enforce `AUTH_POLICY_OPT_KEY: required('console-key')` when `OFFLOAD_LISTENER_SHARED_TOKEN` is set, leaving only `/api/system/status/`, `/docs`, and `/schema` public.

## `LST-02`: Handler-Level MRTR + HMAC `ConfirmationGate` on Mutating MCP Tools

Every mutating `@mcp_tool` (`execute_offload`, `reset_offload_metadata`, `apply_schema_sync`, `cancel_offload_job`) validates `require_mcp_confirmation` (`MCPInputRequiredResult` challenge + HMAC-SHA256 `confirmation_token`), while direct HTTP REST `POST` callers remain un-gated and OTel hooks remain purely observational.

## `LST-03`: Oracle-Only `OracleJobStore` & Cooperative Cancellation

Job persistence uses `OracleJobStore` (`src/goe/listener/jobs/store.py`) with `FOR UPDATE SKIP LOCKED` + `cursor.fetchmany(limit)` (never reintroducing `SqliteJobStore` or `litestar-queues`), and `DurableJobWorker` unwinds via `_CooperativeCancelSink` before `mark_cancelled()` releases `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ`.

## `LST-04`: Dry-Run Preview & `SchemaSyncService` Routing in `ListenerOperationsService`

`ListenerOperationsService` (`src/goe/listener/services/operations.py`) passes `execute: False` in options and `dry_run=True` on gateway constructors (never passing `'dry_run'` into `OffloadOperation` kwargs, which fails `EXPECTED_OFFLOAD_ARGS`), and routes schema evolution through `SchemaSyncService` (`src/goe/sync/differ.py`).

## `LST-05`: Litestar DI Test Mocking & MCP `ByteReceiveStream` Contract

Unit tests inject `job_store` via `create_app(job_store=...)` or patch `goe.listener.app._default_job_store` (never patching `get_job_store` with un-spec'd `MagicMock`, which breaks Litestar's `ParsedSignature.from_fn`), and stdio MCP tests use `anyio.abc.ByteReceiveStream`/`ByteSendStream`.

## `LST-06`: Zero-Overhead Default `ObservabilityRuntime` & Context Propagation

When `GOE_OTEL_ENABLED=false`, `src/goe/observability/` performs zero `opentelemetry.sdk` imports and zero span allocations; background worker threads propagate context via `submit_with_context` / `run_bounded`.
