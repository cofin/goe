---
type: Spec
flow_id: litestar_mcp_listener_overhaul_20261029
title: Native Litestar-MCP GOE Listener Overhaul
state: completed
plan_revision: 3
plan_commit: null
state_revision: 14
current_task: null
last_operation: 20261029T215700Z-flow-executor-complete-4-3-00
operation_targets: ["4.3"]
last_verified_checkpoint: "phase-4@b42af38"
created_at: "2026-10-29T17:40:00Z"
updated_at: "2026-10-29T21:57:00Z"
description: Overhaul the GOE Listener REST and MCP service onto native litestar-mcp 0.16.0 stateless primitives, GOEResourcesController goe:// resources, MRTR and HMAC confirmation gating, full GOE operational parity, cooperative job cancellation, guided DBA prompts, packaged skills, and CLI transports.
---

# Flow: Native Litestar-MCP GOE Listener Overhaul

**Flow ID:** `litestar_mcp_listener_overhaul_20261029`

## Specification

### Code Analysis Summary

Primary-source inspection on `origin/next` (`090941a`) across `pyproject.toml`, `uv.lock`, `src/goe/config/orchestration_defaults.py`, `src/goe/listener/**`, `src/goe/cli/commands/listener.py`, `src/goe/orchestration/**`, `src/goe/offload/offload_validation.py`, `src/goe/sync/differ.py`, `src/goe/report/service.py`, `src/goe/persistence/**`, and `.agents/bundles/knowledge/**` established the following baseline (see promoted research in [goe-listener-audit.md](research/goe-listener-audit.md) and [litestar-mcp-capabilities.md](research/litestar-mcp-capabilities.md)):

- **Packaging, Runtime & Settings (`pyproject.toml`, `uv.lock`, `src/goe/config/orchestration_defaults.py`, `src/goe/listener/config/application.py`)**: The Listener ASGI runtime runs on **Vertebra** (`vertebra.extensions.litestar.LitestarPlugin`, `goe.listener.asgi:app`; `litestar-granian` is absent and prohibited). `uv.lock` resolves `litestar==2.25.0`, `litestar-mcp==0.16.0`, `litestar-security==0.6.0`, `litestar-autowire==0.2.0`, `msgspec==0.22.0`, and `httpx2==2.16.0`, while `pyproject.toml` declares outdated floors (`msgspec>=0.19.0`, `litestar>=2.8.0`, `litestar-security>=0.1.0`, `litestar-autowire>=0.1.0`, `litestar-mcp>=0.1.0`) and omits `httpx2`. `orchestration_defaults.py` (`listener_port_default`, `listener_heartbeat_interval_default`) and `ListenerSettings` lack whitespace-safe numeric env parsing, and `ListenerSettings` retains dead `FRONTEND_DIR`, `static_url`, `static_path`, and `background_workers` attributes without loopback normalization (`0.0.0.0` / `::` -> `127.0.0.1` via `ssl_enabled`).
- **Imperative MCP Bridge (`src/goe/listener/mcp.py`, `src/goe/listener/app.py`)**: `mcp.py` registers synchronous imperative `plugin.register_tool(Tool(...))` wrappers (`get_connectivity_report`, `get_table_status_report`, `list_offloaded_tables`, `preview_offload_plan`, `get_job_status`), enforces confirmation inside `MCPConfig.before_tool_call` (which `litestar-mcp` treats as a non-authorizing observability hook), and falls back to a static `"goe-local-mcp-confirmation-key"` literal when `OFFLOAD_LISTENER_SHARED_TOKEN` is unset.
- **Controller & Domain Parity Gaps (`src/goe/listener/controllers/*.py`, `src/goe/listener/services/system.py`)**:
  - Controllers expose zero `goe://...` MCP Resources or RFC 6570 Resource Templates, zero `ToolAnnotations` or structured `@mcp_tool` metadata, zero `MCPResourceLink` log pointers, zero `PromptController` DBA workflows, and zero `MCPSkillsConfig` operational runbooks. Because `LitestarMCP._discover_mcp_routes` branches `if metadata: ... elif handler.opt:`, `@mcp_tool(...)` on public REST controllers must be paired with a dedicated `GOEResourcesController` (`include_in_schema=False`) so both structured tools and `goe://` resources/templates are discovered simultaneously.
  - `OrchestrationController.get_command_execution` returns untyped `dict[str, Any]` and lets malformed UUID strings raise HTTP `500`.
  - `SystemService.preview_schema_drift` defaults `source_columns=()` and `target_columns=()` unless callers pass synthetic tuples in tests.
  - Core GOE capabilities (`OffloadPipeline.plan` dry-run preview, `CrossDbValidator` validation, `SchemaSyncService` schema evolution, `StatusReportService` multi-table reporting with wired partition fetchers, `self.get_repo(...).get_offload_metadata`, and durable job list/detail inspection) have no Listener endpoints or MCP tools. Note `OrchestrationRunner.schema_sync` is retired (`OrchestrationRunnerException`), so schema evolution routes directly through `SchemaSyncService` (`src/goe/sync/differ.py`).
- **Durable Job Cancellation & Documentation Drift (`src/goe/listener/jobs/**`, `src/goe/persistence/oracle/ddl/sql/create_offload_repo_24.sql`)**: `.agents/bundles/knowledge/listener/{rest-api,worker-and-redis}.md` reference non-existent `OFFLOAD_JOB_QUEUE` and `/cancel/` routes (and `operations/cli-tools.md` still references `litestar-granian`), whereas the actual schema is `GOE_LISTENER_JOBS` (`JobState`: `PENDING`, `CLAIMED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `DEAD_LETTER`) with no `CANCEL_REQUESTED` column, `cancel_job` store method, or worker-thread `ExecutionSink` cancellation unwinding yet.
- **CLI Transports (`src/goe/cli/commands/listener.py`)**: Uses `bind_lazy_imports(__name__, _LAZY_IMPORTS)` and provides `start` and `status` only, with undeclared `httpx` in `_LAZY_IMPORTS` and no `goe listener mcp` (`stdio`, `bridge`, `inspect`) transport commands.

### Relevant Patterns

- **Architecture Boundary Gate (`tools/verify_architecture.py`)**: Enforces centralized JSON serialization via `goe.serializers` (`raw-json`), adapter-isolated `sqlglot` and `oracledb` imports, module top-level imports (or `goe.cli._lazy` in CLI modules) with zero function-scoped imports (`nested-import`), public-before-private function/method ordering (`member-ordering`), and zero inline `#` comments inside function/method bodies (`inline-comment`).
- **DTO & Value Object Convention (`src/goe/typing.py`, `src/goe/listener/schemas.py`)**: All Listener request/response schemas inherit from `FrozenBaseStruct` (`msgspec.Struct` with `frozen=True, gc=False`).
- **Litestar & `litestar-mcp 0.16.0` Conventions**:
  - `build_mcp_config()` must return an exact `MCPConfig` instance (`type(cfg) is MCPConfig`, never a subclass) so Litestar's `SignatureModel` / `msgspec.convert` short-circuits cleanly.
  - Runtime-inspected route handler parameter annotations (`Request`, `FromPath`, `FromQuery`, `JSONBody`, `NamedDependency`) remain at module top-level with zero inline `# noqa` comments, dual REST/MCP mutating handlers retain canonical DTO return annotations (using `typing.cast` on the MCP-only `MCPInputRequiredResult | MCPToolResult` return branch) so OpenAPI and `mypy` stay clean, and every static and templated handler on `GOEResourcesController` carries a Litestar `@get("/...")` route decorator.
  - Blocking database, filesystem, and catalog calls run off the asyncio event loop via `goe.util.concurrency.async_` (`asyncio.to_thread`).
  - `PromptController` subclasses declare `opt = {AUTH_POLICY_OPT_KEY: required("console-key")}` as a plain class attribute (without `ClassVar`) to satisfy both `SecurityPlugin` route compilation and `mypy`.
  - Both `run_stdio` and `run_stdio_streamable_http_bridge` require `header_name="x-goe-console-key"` and `token_prefix=""` when `shared_token` is configured so `HeaderTokenAuth` receives the raw token without `"Bearer "` prefixing.
  - Tests constructing multiple Litestar apps call `clear_autowire_cache()` (`litestar_autowire`) between app instantiations, and tests overriding the job store patch `goe.listener.app._default_job_store` rather than replacing `get_job_store` with `MagicMock`.

### Architectural Decisions & Trade-offs

1. **Base Branch (`D-01`, Confirmed by Cody)**: Target `origin/next` (`090941a`), building directly atop the Vertebra ASGI runtime (`goe.listener.asgi:app`), durable `GOE_LISTENER_JOBS` queue, `ListenerCache`, and OpenTelemetry instrumentation.
2. **Full Native `litestar-mcp 0.16.0` & GOE Operational Suite (`D-02`, Confirmed by Cody)**: Expose `goe://` Resources/Templates via `GOEResourcesController` (`include_in_schema=False`) alongside structured `@mcp_tool` definitions on public REST controllers, delete all imperative `register_tool` shims in `mcp.py`, add `ListenerOperationsService` as a domain facade over `OffloadPipeline.plan` (`execute=False` with read-only protocol gateways), `CrossDbValidator`, and `SchemaSyncService`, add cooperative durable job cancellation + `MCPTaskConfig`, and ship `GOEPromptController` + `MCPSkillsConfig` operational skills.
3. **Mutating Safety Gate via Handler-Level MRTR + Signed `confirmation_token` (`D-03`, Confirmed by Cody)**: Guard `get_mcp_request_context()` with `try: ... except RuntimeError: ctx = None` at the top of mutating handlers (`execute_offload` and `apply_schema_sync` when `execute=True`, decorated with `task_input_before_start=True`). Active `/mcp` requests accept either a two-call MRTR `requestState` + `inputResponses={"confirm": True}` exchange or a preview-issued HMAC-SHA256 `confirmation_token` (in DTO or `x-goe-mcp-confirmation-token` header), returning `MCPInputRequiredResult` synchronously otherwise. Direct HTTP REST `POST` requests (`ctx is None`) return typed `FrozenBaseStruct` DTOs (`schemas.CommandScheduled`, `SchemaSyncExecutionResult`) directly without confirmation tokens or `MCPToolResult` wrappers.
4. **CLI Transports Without A2A (`D-04`, Confirmed by Cody)**: Provide `POST /mcp` Streamable HTTP plus `goe listener mcp {stdio,bridge,inspect}` using core `litestar-mcp` (`run_stdio`, `MCPStdioContext`, `run_stdio_streamable_http_bridge`, `httpx2`) while omitting `litestar-mcp[a2a]` / `a2a-sdk`.

### Requirements

#### Functional Requirements

- **FR-01 (Stateless `2026-07-28` MCP Configuration)**: `src/goe/listener/mcp.py` exposes `build_mcp_config()` returning an exact `MCPConfig` instance protected by `route_opt={AUTH_POLICY_OPT_KEY: required("console-key")}`, with DBA server `instructions`, pure OpenTelemetry `before_tool_call` / `after_tool_call` hooks, and zero imperative `register_tool` wrappers.
- **FR-02 (`GOEResourcesController` & Structured Tools)**: Public read-only system, catalog, table, job, and execution endpoints (excluding `GET`/`HEAD /api/system/status/` public probes) publish `@mcp_tool(...)` definitions with `agent_instructions`, `when_to_use`, `returns`, and `ToolAnnotations`, while `GOEResourcesController` (`include_in_schema=False`, `auth=required("console-key")`) publishes static `goe://...` MCP Resources and RFC 6570 Resource Templates.
- **FR-03 (Table Metadata & Status Report Parity)**: Listener exposes persisted hybrid `OffloadMetadata` (`GET /api/system/schemas/{schema_name}/{table_name}/metadata/` via `self.get_repo(...)`) and multi-table/schema `StatusReportEnvelope` (`GET /api/system/reports/status/` via `StatusReportService` with wired source/target partition fetchers and `demo=True` support).
- **FR-04 (Typed Orchestration & `MCPResourceLink` Logs)**: `OrchestrationController` returns typed `CommandExecution` / `JobStatusResponse` / `JobListResponse` DTOs (reusing `JobStoreProtocol.list_jobs` and `get_job_by_execution_id`), maps malformed UUIDs to HTTP `400`, exposes `/api/orchestration/jobs/` and `/api/orchestration/jobs/{execution_id}/`, preserves `/api/orchestration/executions/{execution_id}/execution-log/`, and provides `get_execution_log_link` (`/execution-log/link/`) returning `MCPResourceLink` (`goe://executions/{execution_id}/log`).
- **FR-05 (Handler-Level MRTR & Preview `confirmation_token` Gate)**: `ConfirmationGate` uses `settings.shared_token` or a cryptographically random per-process secret (`secrets.token_hex(32)`), gates mutating `/mcp` calls (`execute_offload`, `apply_schema_sync` when `execute=True`, `task_input_before_start=True`) via `MCPInputRequiredResult` or signed `confirmation_token`, strips `confirmation_token` in `OffloadOptions.to_params_dict()`, and leaves direct HTTP REST `POST` calls un-gated (`schemas.CommandScheduled`, `SchemaSyncExecutionResult`).
- **FR-06 (Dry-Run `OffloadPipeline.plan` Preview)**: `POST /api/orchestration/offload/preview/` (`preview_offload_plan`) runs `OffloadPipeline.plan` with read-only protocol gateways and `execute=False` (without injecting `"dry_run"` into `OffloadOperation` kwargs) and returns `OffloadPlanPreview` plus a `ConfirmationChallenge` bound to `execute_offload` (`execute=True`).
- **FR-07 (Catalog-Hydrated Schema Drift, Schema Sync & Cross-DB Validation)**: `preview_schema_drift` hydrates live frontend/backend columns and mints an `apply_schema_sync` challenge when evolution DDL exists; `POST /api/orchestration/sync/` (`apply_schema_sync`) executes `SchemaSyncService` under `orchestration_lock_for_table` and invalidates `ListenerCache`; `POST /api/orchestration/validate/` (`validate_table`) runs read-only `CrossDbValidator.validate(...)`, `CrossDbValidationBuilder("oracle").parse_filter_tuples(...)`, and optional `validator.run_row_diff()`.
- **FR-08 (Cooperative Job Cancellation & `MCPTaskConfig`)**: `GOE_LISTENER_JOBS` tracks `CANCEL_REQUESTED` (filtered in claim/reap queries); `cancel_job` cancels `PENDING`/`CLAIMED` jobs immediately and flags `RUNNING` jobs so `_CooperativeCancelSink` unwinds the worker thread and releases `orchestration_lock_for_table` before `mark_cancelled`; `POST /api/orchestration/executions/{execution_id}/cancel/` (`cancel_offload_job`) cancels durable queue jobs while `MCPTaskConfig` (`tasks/get`, `tasks/result`, `tasks/list`, `tasks/cancel`) manages in-flight MCP tool tasks.
- **FR-09 (`GOEPromptController` & `MCPSkillsConfig`)**: `GOEPromptController` publishes `plan_table_offload`, `diagnose_failed_execution`, `reconcile_schema_drift`, and `audit_schema_readiness`; `MCPSkillsConfig` serves SHA-256-verified `SKILL.md` runbooks resolved from packaged `goe.listener` resources.
- **FR-10 (`goe listener mcp` CLI & Status Hardening)**: `goe listener mcp` provides `stdio`, `bridge`, and `inspect` via `_LAZY_IMPORTS` (passing `header_name="x-goe-console-key"` and `token_prefix=""` on `stdio` and `bridge`), and `goe listener status` uses `httpx2`, `settings.base_url` loopback normalization, and `x-goe-console-key`.

#### Non-Functional & Architectural Requirements

- **NFR-01 (Event-Loop Non-Blocking)**: All database, catalog, validation, planning, and log reads execute in worker threads (`async_` / `asyncio.to_thread`) with bounded payload sizes (`max_log_bytes`, `max_blob_bytes`).
- **NFR-02 (Architecture & Style Compliance)**: Zero violations in `tools/verify_architecture.py`, `ruff check`, `ruff format --check`, and `mypy src/goe`.
- **NFR-03 (Lockfile, Runtime & Packaging Hygiene)**: Vertebra ASGI runtime is preserved (zero `litestar-granian` dependencies), `pyproject.toml` floors match `0.16.0` / `2.25.0` APIs, `uv.lock` contains only `https://pypi.org/simple` URLs, and `src/goe/listener/skills/**/SKILL.md` files are verified inside built Hatch wheels.
- **NFR-04 (Stdio Frame Purity)**: `goe listener mcp stdio` and `goe listener mcp bridge` emit strictly newline-delimited JSON-RPC frames on `stdout`, routing any logs/diagnostics to `stderr` or log files.
- **NFR-05 (Table Lock Safety)**: Mutating offload and schema evolution executions honor `orchestration_lock_for_table` (`409` on lock contention -> `isError: True` in MCP), and cooperative job cancellation unwinds `orchestration_lock_for_table` before releasing `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ`.
- **NFR-06 (OKF Documentation Accuracy)**: `.agents/bundles/knowledge/listener/*.md` and `operations/cli-tools.md` match Vertebra, implemented `GOE_LISTENER_JOBS` states, routes, and CLI commands.

#### REST & MCP Surface Catalog

| Controller / Owner | HTTP Route | MCP Tool (`@mcp_tool`) | MCP Resource / Template (`GOEResourcesController`) | Safety / Annotations |
| --- | --- | --- | --- | --- |
| `SystemController` / `GOEResourcesController` | `GET`/`HEAD /api/system/status/` | *(unmarked)* | `goe://system/status` (`console-key`) | HTTP `public()` probe; MCP `console-key` read-only |
| `SystemController` / `GOEResourcesController` | `GET /api/system/connectivity/` | `check_connectivity` | `goe://system/connectivity` | Read-only |
| `SystemController` / `GOEResourcesController` | `GET /api/system/config/` | `get_listener_config` | `goe://system/config` | Read-only (redacted) |
| `SystemController` / `GOEResourcesController` | `GET /api/system/reports/status/` | `generate_status_report` | `goe://reports/status` | Read-only, `task_support="optional"` |
| `SchemasController` / `GOEResourcesController` | `GET /api/system/schemas/` | `get_offloadable_schemas` | `goe://schemas` | Read-only |
| `SchemasController` / `GOEResourcesController` | `GET /api/system/schemas/{schema_name}/` | `get_offloadable_tables` | `goe://schemas/{schema_name}/tables` | Read-only |
| `TablesController` / `GOEResourcesController` | `GET .../schemas/{schema_name}/{table_name}/columns/` | `get_table_columns` | `goe://schemas/{schema_name}/{table_name}/columns` | Read-only |
| `TablesController` / `GOEResourcesController` | `GET .../schemas/{schema_name}/{table_name}/partitions/` | `get_table_partitions` | `goe://schemas/{schema_name}/{table_name}/partitions` | Read-only |
| `TablesController` / `GOEResourcesController` | `GET .../schemas/{schema_name}/{table_name}/status/` | `get_table_offload_status` | `goe://schemas/{schema_name}/{table_name}/status` | Read-only |
| `TablesController` / `GOEResourcesController` | `GET .../schemas/{schema_name}/{table_name}/drift/` | `preview_schema_drift` | `goe://schemas/{schema_name}/{table_name}/drift` | Read-only (mints sync token) |
| `TablesController` / `GOEResourcesController` | `GET .../schemas/{schema_name}/{table_name}/metadata/` | `get_table_offload_metadata` | `goe://schemas/{schema_name}/{table_name}/metadata` | Read-only |
| `OrchestrationController` / `GOEResourcesController` | `GET /api/orchestration/executions/` | `get_command_executions` | `goe://executions` | Read-only |
| `OrchestrationController` / `GOEResourcesController` | `GET /api/orchestration/executions/{execution_id}/` | `get_command_execution` | `goe://executions/{execution_id}` | Read-only |
| `OrchestrationController` / `GOEResourcesController` | `GET /api/orchestration/executions/{execution_id}/execution-log/` | `get_command_execution_log` | `goe://executions/{execution_id}/log` | Read-only (bounded) |
| `OrchestrationController` | `GET /api/orchestration/executions/{execution_id}/execution-log/link/` | `get_execution_log_link` | *(returns `MCPResourceLink`)* | Read-only |
| `OrchestrationController` / `GOEResourcesController` | `GET /api/orchestration/jobs/` | `list_offload_jobs` | `goe://jobs` | Read-only |
| `OrchestrationController` / `GOEResourcesController` | `GET /api/orchestration/jobs/{execution_id}/` | `get_offload_job` | `goe://jobs/{execution_id}` | Read-only |
| `OrchestrationController` | `POST /api/orchestration/offload/preview/` | `preview_offload_plan` | — | Read-only dry-run (mints offload token) |
| `OrchestrationController` | `POST /api/orchestration/offload/` | `execute_offload` | — | Destructive, MCP MRTR + HMAC gated (`execute=True`), `task_support="optional"`, `task_input_before_start=True` |
| `OrchestrationController` | `POST /api/orchestration/validate/` | `validate_table` | — | Read-only, `task_support="optional"` |
| `OrchestrationController` | `POST /api/orchestration/sync/` | `apply_schema_sync` | — | Destructive, MCP MRTR + HMAC gated (`execute=True`), `task_support="optional"`, `task_input_before_start=True` |
| `OrchestrationController` | `POST /api/orchestration/executions/{execution_id}/cancel/` | `cancel_offload_job` | — | Mutating idempotent durable-job cancellation |
| `GOEPromptController` | `POST /mcp` (`prompts/*`) | — | Prompts: `plan_table_offload`, `diagnose_failed_execution`, `reconcile_schema_drift`, `audit_schema_readiness` | `console-key` auth |
| `MCPSkillsConfig` | `POST /mcp` (`skills/*`, `resources/*`) | — | `skill://goe-offload-operations/SKILL.md`, `skill://goe-diagnostics-and-recovery/SKILL.md`, `skill://goe-schema-drift-and-validation/SKILL.md` | SHA-256 verified |

#### Database & Durable Job Queue Contract

- Remove `SqliteJobStore` and all `sqlite_*` SQL queries (`D-05`); `OracleJobStore` backed by `OracleDatabaseRegistry.for_options(config)` is the sole durable job store implementation.
- Add `CANCEL_REQUESTED NUMBER(1) DEFAULT 0 NOT NULL` (Oracle in `src/goe/listener/jobs/sql/job_queue.sql` and `src/goe/persistence/oracle/ddl/sql/create_offload_repo_24.sql`).
- Filter `CANCEL_REQUESTED = 0` in `oracle_claim_pending_jobs` and `oracle_reap_expired_to_pending`, and add `oracle_reap_expired_to_cancelled` in `reap_expired_leases` so expired `CLAIMED`/`RUNNING` jobs with `CANCEL_REQUESTED = 1` transition directly to `CANCELLED`.
- Cancellation state machine (`JobStoreProtocol.cancel_job`):
  - `PENDING` or `CLAIMED`: atomically update `STATUS = 'CANCELLED'`, `CANCEL_REQUESTED = 1`, `LEASE_EXPIRES_AT = NULL`, `FINISHED_AT = :now`, `UPDATED_AT = :now`, `ERROR_MESSAGE = :reason` (releasing `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ` immediately).
  - `RUNNING`: set `CANCEL_REQUESTED = 1`, `UPDATED_AT = :now`; `DurableJobWorker._lease_renewal_loop` trips the per-job `threading.Event` observed by `_CooperativeCancelSink(ExecutionSink)` inside the worker thread (`JobCancelledError`), awaits worker-thread unwinding (releasing `orchestration_lock_for_table` `filelock`), and only then invokes `mark_cancelled(...)` (`STATUS = 'CANCELLED'`, `FINISHED_AT = :now`) without incrementing retry attempts.
  - Terminal (`SUCCEEDED`, `FAILED`, `CANCELLED`, `DEAD_LETTER`): return existing `JobRecord` unchanged (idempotent `200`).

#### Security & Failure-Mode Mitigations

- **Unauthenticated Local Dev Secret**: When `OFFLOAD_LISTENER_SHARED_TOKEN` is unset, `ConfirmationGate` uses a module-scoped `_EPHEMERAL_CONFIRMATION_SECRET = secrets.token_hex(32)` rather than a static predictable string.
- **Cross-Table / Payload Replay Prevention**: HMAC confirmation tokens bind `(tool_name, owner_table.upper(), sha256(canonical_payload_json), exp)`; modifying `owner_table`, `reset_backend_table`, `purge`, or `execute` invalidates the signature.
- **Symlink & Integrity Protection on Skills**: `SkillCatalog.from_config` rejects symlinks and verifies SHA-256 digests on every `skill://` read.
- **Log Path Containment**: `read_execution_log_bounded` enforces `candidate.is_relative_to(allowed_log_dir)` (`403` on traversal) and caps reads at `settings.max_log_bytes`.

#### Requirement-to-Task Traceability Matrix

| Requirement | Task(s) | Verification Strategy | Primary Test Suite |
| --- | --- | --- | --- |
| `FR-01`, `NFR-03` | `1.1`, `1.2`, `4.1` | `behavior_tdd` | `tests/unit/listener/test_settings.py`, `tests/unit/listener/test_mcp.py`, `tests/unit/listener/test_listener_cli_vertebra.py` |
| `FR-02`, `FR-03`, `NFR-01` | `2.1` | `behavior_tdd` | `tests/unit/listener/test_system_controllers.py`, `tests/unit/listener/test_listener_cache_and_controllers.py`, `tests/unit/listener/test_system_service.py` |
| `FR-04`, `FR-05` | `1.2`, `2.2`, `4.3` | `behavior_tdd`, `integration_acceptance` | `tests/unit/listener/test_mcp.py`, `tests/unit/listener/test_orchestration_controllers.py`, `tests/unit/listener/test_mcp_protocol_contract.py` |
| `FR-06` | `3.1` | `behavior_tdd` | `tests/unit/listener/test_operations_service.py`, `tests/unit/listener/test_orchestration_controllers.py` |
| `FR-07`, `NFR-05` | `3.2` | `behavior_tdd` | `tests/unit/listener/test_operations_service.py`, `tests/unit/listener/test_system_service.py`, `tests/unit/listener/test_orchestration_controllers.py` |
| `FR-08` | `3.3` | `behavior_tdd` | `tests/unit/listener/test_job_models.py`, `tests/unit/listener/test_job_store_and_worker.py`, `tests/unit/listener/test_mcp.py` |
| `FR-09` | `4.1` | `behavior_tdd` | `tests/unit/listener/test_mcp.py` |
| `FR-10`, `NFR-04` | `4.2` | `behavior_tdd` | `tests/unit/cli/test_listener_command.py` |
| `NFR-02`, `NFR-06` | `1.1`–`4.3` | `integration_acceptance` | `tests/unit/listener/test_mcp_protocol_contract.py`, `tools/verify_architecture.py` |

## Implementation Plan

### Phase 1: Foundation, Dependencies, and Native MCP Configuration

- [x] Task 1.1: Align Listener ecosystem dependencies and clean up ListenerSettings [25243cb]
- [x] Task 1.2: Overhaul mcp.py for stateless MCPConfig, MRTR + HMAC ConfirmationGate, and pure OTel hooks [e72b0f4]

> **Phase 1 Recovery Checkpoint**: Verify `uv lock --check`, `make lint`, `tools/verify_architecture.py`, and `tests/unit/listener/{test_settings,test_mcp,test_listener_cli_vertebra}.py` pass on clean working tree commit before starting Phase 2.

### Phase 2: GOEResourcesController, Annotated Controllers, and Typed Orchestration

- [x] Task 2.1: Expose goe:// resources via GOEResourcesController, annotated @mcp_tool handlers, table OffloadMetadata, and StatusReportEnvelope [6ce00d6]
- [x] Task 2.2: Refactor OrchestrationController for typed CommandExecution DTOs, job inspection, MCPResourceLink logs, and MRTR offload gating [b8fc910]

> **Phase 2 Recovery Checkpoint**: Verify `tests/unit/listener/{test_system_controllers,test_listener_cache_and_controllers,test_system_service,test_orchestration_controllers}.py`, `tools/verify_architecture.py`, and `make lint` pass on clean commit before starting Phase 3.

### Phase 3: Operational Parity and Cooperative Job Cancellation

- [x] Task 3.1: Implement dry-run OffloadPipeline.plan preview service and preview_offload_plan endpoint [ef38e3d]
- [x] Task 3.2: Implement catalog-hydrated schema drift, MRTR-gated apply_schema_sync, and read-only validate_table [dca1fa7]
- [x] Task 3.3: Add cooperative durable job cancellation and wire MCPTaskConfig [89c2989]

> **Phase 3 Recovery Checkpoint**: Verify `tests/unit/listener/{test_operations_service,test_system_service,test_orchestration_controllers,test_job_models,test_job_store_and_worker,test_mcp}.py`, `tools/verify_architecture.py`, and `make lint` pass on clean commit before starting Phase 4.

### Phase 4: Guided Prompts, Operational Skills, CLI Transports, and Protocol Verification

- [x] Task 4.1: Add GOEPromptController guided DBA prompts and packaged MCPSkillsConfig skills [ef1671b]
- [x] Task 4.2: Add goe listener mcp CLI transports (stdio, bridge, inspect) and harden goe listener status [83ef546]
- [x] Task 4.3: Add MCP 2026-07-28 end-to-end protocol contract suite and reconcile OKF Listener/CLI docs [b42af38]

> **Phase 4 Recovery Checkpoint & Manual Verification Gate**: Run full `GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run pytest tests/unit/listener/ tests/unit/cli/test_listener_command.py`, `uv run python tools/verify_architecture.py`, `make lint`, wheel `SKILL.md` archive inspection, and `uv run goe listener mcp inspect` smoke check before invoking `/flow:complete`.

## Continuity Snapshot

- **Active Flow / Lifecycle**: `litestar_mcp_listener_overhaul_20261029` (`completed`)
- **Current Task & Claimant**: None (all 10 tasks completed)
- **Last Verified Checkpoint**: `phase-4@b42af38`
- **Decisions**:
  - `D-01`: Base branch is `origin/next` (`090941a`), preserving the Vertebra ASGI runtime (`goe.listener.asgi:app`).
  - `D-02`: Full native `litestar-mcp 0.16.0` overhaul + full GOE operational parity (`GOEResourcesController` + `@mcp_tool`, `OffloadPipeline.plan` preview, `CrossDbValidator`, `SchemaSyncService`, `StatusReportService`, `OffloadMetadata`, cooperative job cancellation + `MCPTaskConfig`, `GOEPromptController`, `MCPSkillsConfig`).
  - `D-03`: Handler-level MRTR (`MCPInputRequiredResult`, `task_input_before_start=True`) + signed `confirmation_token` fallback on mutating MCP calls (`execute_offload`, `apply_schema_sync`), guarding `get_mcp_request_context()` with `RuntimeError` so direct HTTP REST `POST` callers remain un-gated and OTel hooks stay purely observational.
  - `D-04`: Streamable HTTP (`POST /mcp`) + `goe listener mcp {stdio,bridge,inspect}` CLI without `a2a-sdk` / `LitestarA2A`.
  - `D-05`: Remove `SqliteJobStore` and `sqlite_*` queries completely; `OracleJobStore` backed by `OracleDatabaseRegistry.for_options(config)` is the sole durable job store.
- **Newest Discoveries**:
  1. `litestar_mcp 0.16.0` defines `MCPInputRequiredResult(input_requests=..., request_state: str | None = None)` and uses `dict[str, Any]` (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) for `@mcp_tool(..., annotations=...)`.
  2. `LitestarMCP._discover_mcp_routes` branches `if metadata: ... elif handler.opt:`, and `_resource_uri` reads `handler.opt["mcp_resource_uri"]`, so static `GOEResourcesController` handlers pass `mcp_resource_uri="goe://..."` on `@get("/...")`.
  3. `get_mcp_request_context()` raises `RuntimeError` outside `/mcp`, and `task_input_before_start=True` ensures Round 1 returns `MCPInputRequiredResult` synchronously before creating a `TaskRecord`.
  4. `DurableJobWorker` runs synchronous `OrchestrationRunner` in `asyncio.to_thread` under `orchestration_lock_for_table`, requiring `_CooperativeCancelSink` to unwind the worker thread before `mark_cancelled`.
  5. Both `run_stdio` and `run_stdio_streamable_http_bridge` default `token_prefix="Bearer"`, so `goe listener mcp stdio` and `bridge` must pass `header_name="x-goe-console-key"` and `token_prefix=""`.
- **Blockers & Unblock Conditions**: None.
- **Next Exact Step**: Flow complete (`phase-4@b42af38`)
- **Plan Identity**: `{plan_revision: 3, plan_commit: null}`
- **State Identity**: `{revision: 14, last_operation: 20261029T215700Z-flow-executor-complete-4-3-00, operation_targets: ["4.3"]}`
- **Relevant Rule & Knowledge Paths**:
  - `AGENTS.md`
  - `tools/verify_architecture.py`
  - `.agents/bundles/knowledge/workflow.md`
  - `.agents/bundles/knowledge/patterns/index.md`
  - `.agents/bundles/knowledge/listener/index.md`
  - `.agents/bundles/knowledge/operations/cli-tools.md`
