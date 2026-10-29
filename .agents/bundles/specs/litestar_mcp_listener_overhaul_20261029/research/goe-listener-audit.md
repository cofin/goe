---
type: Research
research_id: "goe-listener-audit"
title: GOE Listener & Domain Services Baseline Audit
description: Primary-source audit of GOE Listener controllers, MCP configuration, durable job store, CLI commands, and OKF documentation discrepancies on origin/next (090941a).
scope: architecture
tags: [listener, mcp, audit, orchestration]
status: stable
state: promoted
promoted_to: litestar_mcp_listener_overhaul_20261029
created_at: "2026-10-29T17:40:00Z"
updated_at: "2026-10-29T18:18:00Z"
---

# GOE Listener & Domain Services Baseline Audit (`090941a`)

## Scope and Primary Sources

Audited on `origin/next` (`090941a`) across:

- `pyproject.toml` and `uv.lock`
- `src/goe/config/orchestration_defaults.py`
- `src/goe/listener/app.py`, `asgi.py`, `vertebra_gate.py`, `mcp.py`, `security.py`, `telemetry.py`, `cache.py`, `schemas.py`
- `src/goe/listener/config/application.py`
- `src/goe/listener/controllers/{system,schemas,tables,orchestration}.py`
- `src/goe/listener/exceptions/handlers.py` and `src/goe/listener/utils/orchestrate.py`
- `src/goe/listener/services/system.py`
- `src/goe/listener/jobs/{models,store,worker}.py` and `src/goe/listener/jobs/sql/job_queue.sql`
- `src/goe/persistence/oracle/ddl/sql/create_offload_repo_24.sql` and `src/goe/persistence/models.py`
- `src/goe/cli/commands/{listener,report,validate}.py` and `src/goe/cli/config.py`
- `src/goe/orchestration/{orchestration_runner,pipeline,models,sinks}.py`, `src/goe/orchestration/stages/{discovery,plan_resolution}.py`, `src/goe/offload/offload_validation.py`, `src/goe/sync/differ.py`, and `src/goe/report/service.py`
- `.agents/bundles/knowledge/listener/{index,rest-api,worker-and-redis}.md` and `.agents/bundles/knowledge/operations/cli-tools.md`

## Verified Findings

### 1. Packaging, Runtime, and Settings Drift (`F-AUD-01`)

- On `090941a` (including PR #17 `87d18dd`), GOE Listener runs on the **Vertebra** ASGI runtime (`vertebra.extensions.litestar.LitestarPlugin` in `src/goe/listener/app.py`, `verify_vertebra_runtime_gate` in `src/goe/listener/vertebra_gate.py`, and `build_vertebra_command` targeting `goe.listener.asgi:app` in `src/goe/cli/commands/listener.py`), and `litestar-granian` has been removed (enforced by `tests/unit/listener/test_listener_cli_vertebra.py`). Only `.agents/bundles/knowledge/operations/cli-tools.md` retains a stale `litestar-granian` bullet.
- `uv.lock` resolves `litestar==2.25.0`, `litestar-mcp==0.16.0`, `litestar-security==0.6.0`, `litestar-autowire==0.2.0`, `msgspec==0.22.0`, and `httpx2==2.16.0`, whereas `pyproject.toml` `[project.dependencies]` still specifies stale lower bounds (`msgspec>=0.19.0`, `litestar>=2.8.0`, `litestar-security>=0.1.0`, `litestar-autowire>=0.1.0`, `litestar-mcp>=0.1.0`) and omits `httpx2` even though `src/goe/cli/commands/listener.py` makes outbound HTTP probes via undeclared `httpx`.
- `ListenerSettings` (`src/goe/listener/config/application.py`) retains unused `FRONTEND_DIR`, `static_url`, `static_path`, and `background_workers` attributes, lacks loopback-normalized `client_host` / `base_url` properties (using `self.ssl_enabled`), and relies on `listener_port_default` / `listener_heartbeat_interval_default` in `src/goe/config/orchestration_defaults.py`, which raise `ValueError` when `OFFLOAD_LISTENER_PORT` or `OFFLOAD_LISTENER_HEARTBEAT_INTERVAL` is whitespace-only (`"   "`).

### 2. Incomplete & Imperative MCP Integration (`F-AUD-02`)

- `src/goe/listener/mcp.py` registers synchronous imperative `plugin.register_tool(Tool(...))` wrappers (`get_connectivity_report`, `get_table_status_report`, `list_offloaded_tables`, `preview_offload_plan`, `get_job_status`) that either duplicate route handlers already marked with `mcp_tool=` (`check_connectivity`, `get_table_offload_status`, `get_offloadable_tables`) or expose an incomplete stub (`preview_offload_plan` returning `planned_options` without invoking `OffloadPipeline.plan`).
- None of the controllers expose `goe://...` MCP Resources (`mcp_resource` / `mcp_resource_template`), structured `@mcp_tool(...)` guidance (`agent_instructions`, `when_to_use`, `returns`, `ToolAnnotations`, `task_support`, `task_input_before_start`), `MCPResourceLink` execution log pointers, `PromptController` guided DBA workflows, `MCPSkillsConfig` operational runbooks, or `MCPTaskConfig` (`io.modelcontextprotocol/tasks`).
- `ConfirmationGate` enforces mutating confirmation inside `MCPConfig.before_tool_call` (raising `ConfirmationRequiredError`), even though `litestar-mcp` treats `before_tool_call` / `after_tool_call` as observational hooks whose exceptions are caught/swallowed rather than handler-level multi-round-trip (`MCPInputRequiredResult`) control flow. In addition, `ConfirmationGate.__init__` falls back to a static `"goe-local-mcp-confirmation-key"` literal when `OFFLOAD_LISTENER_SHARED_TOKEN` is unset.

### 3. Live Controller Routes, Typing, and Domain Service Gaps (`F-AUD-03`)

- Live controller route and DTO baseline on `090941a`:
  - `SystemController` (`src/goe/listener/controllers/system.py`): `GET /api/system/status/` (`health_check` -> `schemas.HealthCheck`) and `HEAD /api/system/status/` (`health_check_head`) are the `auth=public()` liveness probes; `GET /api/system/connectivity/` (`check_connectivity` -> `ConnectivityReport`) and `GET /api/system/config/` (`get_listener_config` -> `schemas.ListenerConfig`) require `console-key`.
  - `SchemasController` (`src/goe/listener/controllers/schemas.py`): `GET /api/system/schemas/` (`get_offloadable_schemas` -> `schemas.OffloadableSchemas`) and `GET /api/system/schemas/{schema_name:str}/` (`get_offloadable_tables` -> `schemas.TableDetails`).
  - `TablesController` (`src/goe/listener/controllers/tables.py`): `/columns/`, `/partitions/`, `/status/`, and `/drift/` under `/api/system/schemas/{schema_name:str}/{table_name:str}`.
  - `OrchestrationController` (`src/goe/listener/controllers/orchestration.py`): `GET /api/orchestration/executions/` (`get_command_executions`), `GET /api/orchestration/executions/{execution_id:str}/` (`get_command_execution`), `GET /api/orchestration/executions/{execution_id:str}/execution-log/` (`get_command_execution_log`), and `POST /api/orchestration/offload/` (`execute_offload_command`, `mcp_tool="execute_offload"` -> `schemas.CommandScheduled`).
- `OrchestrationController.get_command_execution` returns an untyped `dict[str, Any]` instead of `schemas.CommandExecution` and allows `ValueError` from `ExecutionId.from_str(...)` on malformed UUID strings to escape as an unhandled HTTP `500` instead of a structured HTTP `400`.
- `SystemService.preview_schema_drift` (`src/goe/listener/services/system.py`) defaults `source_columns=()` and `target_columns=()` when invoked from `TablesController.preview_schema_drift`, returning an empty no-op diff unless callers pass synthetic column tuples in tests.
- Core GOE capabilities implemented in PRDs 4–10 have no Listener HTTP or MCP surface yet:
  - Dry-run `OffloadPipeline.plan` preview (`OffloadPlan` in `src/goe/orchestration/models.py`; note `OffloadOperation` uses `execute=False` for dry-run and rejects `"dry_run"` in `EXPECTED_OFFLOAD_ARGS`, and `OffloadPipeline` requires read-only gateway adapters over `create_source_table`, `create_repository_client`, and `get_offload_target_table`)
  - Cross-database aggregate and DuckDB row-diff validation (`CrossDbValidator` and `CrossDbValidationBuilder` in `src/goe/offload/offload_validation.py`)
  - Schema evolution execution (`SchemaSyncService` in `src/goe/sync/differ.py`; `OrchestrationRunner.schema_sync` in `src/goe/orchestration/orchestration_runner.py` is retired and raises `OrchestrationRunnerException("Schema Sync no longer exists")`)
  - Multi-table/schema `StatusReportService` (`StatusReportEnvelope` in `src/goe/report/service.py`, wired with `source_fetcher` and `target_fetcher` backed by `self.get_repo(self.config, self.messages)` and `create_backend_table(..., dry_run=True)`)
  - Persisted hybrid `OffloadMetadata` lookup (`self.get_repo(self.config, self.messages).get_offload_metadata(owner, table_name)` in `SystemService`)
  - Durable job queue HTTP/MCP inspection (`JobStoreProtocol.list_jobs` and `JobStoreProtocol.get_job_by_execution_id` already exist in `src/goe/listener/jobs/store.py` backed by `oracle_list_jobs`/`sqlite_list_jobs` and `oracle_get_job`/`sqlite_get_job`, ready to mount on `OrchestrationController`)

### 4. OKF Documentation vs Code Discrepancy on Job Queue & Cancellation (`F-AUD-04`)

- `.agents/bundles/knowledge/listener/rest-api.md` and `.agents/bundles/knowledge/listener/worker-and-redis.md` claim that `POST /api/orchestration/executions/{execution_id}/cancel/`, `cancel_requested`, and table `OFFLOAD_JOB_QUEUE` (`QUEUED` state) already exist.
- Direct inspection of `src/goe/listener/controllers/orchestration.py`, `src/goe/listener/jobs/{models,store,worker}.py`, `src/goe/listener/jobs/sql/job_queue.sql`, and `src/goe/persistence/oracle/ddl/sql/create_offload_repo_24.sql` proves:
  1. The real durable queue tables are `GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS` (`JobState`: `PENDING`, `CLAIMED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `DEAD_LETTER`).
  2. Neither `CANCEL_REQUESTED`, `JobStoreProtocol.cancel_job`, `JobStoreProtocol.mark_cancelled`, cooperative cancellation inside `DurableJobWorker._default_execute_job` (`OrchestrationRunner` worker thread holding `orchestration_lock_for_table`), expired-lease reaper awareness of `CANCEL_REQUESTED`, nor `POST /api/orchestration/executions/{execution_id}/cancel/` exists in source code yet.

### 5. CLI Transport Gaps (`F-AUD-05`)

- `src/goe/cli/commands/listener.py` uses `_LAZY_IMPORTS` (`bind_lazy_imports`) cleanly and provides `start` and `status`. `goe listener status` interpolates `settings.host` directly into `http://{settings.host}:{settings.port}/api/system/status/` without normalizing wildcard bind addresses (`0.0.0.0`, `::`) to loopback or honoring `settings.ssl_enabled`, uses undeclared `httpx`, and never probes authenticated `/api/system/config/` with `x-goe-console-key`.
- There is no `goe listener mcp` subcommand group (`stdio`, `bridge`, `inspect`) for local desktop/IDE MCP hosts or remote authenticated Streamable HTTP bridging.

## Confidence & Limitations

- **Confidence**: High — every finding was verified directly against tracked source files on `090941a`.
- **Limitations**: Live Oracle integration verification requires external database credentials (`GOE_TEST_USER_PASS`); unit and protocol contract suites run hermetically against `SqliteJobStore` and injected gateway doubles.
