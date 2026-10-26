---
name: flow-memory-keeper
description: Use at task, phase, flow, sync, archive, finish, revise, or failure checkpoints to keep Flow specs clean, capture learnings and failures, elevate durable patterns, and refine this skill with project-specific nuances
---

# Flow Memory Keeper

## Purpose

This project-local skill prevents Flow work from drifting into stale specs, missing learnings, or half-archived folders.

Use it whenever work is completed, paused, blocked, revised, synced, or archived.

<workflow>

## Mandatory Outcomes

Before claiming a task, phase, or flow is complete:

1. Ensure `spec.md` is readable and current through the normal Flow sync process.
2. Capture concrete learnings in the flow's `learnings.md`.
3. Capture failures, false starts, blockers, and recovery notes when they would help a future session.
4. If the user had to repeat a correction or showed frustration that something was forgotten, flag that as a workflow gap and capture it explicitly.
5. Elevate durable patterns to evidence-backed `.agents/bundles/knowledge/patterns/<topic>.md` chapters.
6. Update chapters recursively under `.agents/bundles/knowledge/` when the current-state knowledge base changed, preserving project-shaped relative paths, indexes, and links.
7. If the flow is complete, archive it cleanly and leave the active spec area uncluttered.
8. Capture validated repo-native commands and verification workflows in `.agents/bundles/knowledge/workflow.md` when they were discovered or corrected during the work.

## Completion Protocol

### Task or Phase Completion

1. Append a concise entry to `.agents/bundles/specs/<flow_id>/learnings.md`:
   - what changed
   - why it changed
   - files touched
   - commands or checks that mattered
   - canonical repo commands that future agents should reuse
   - gotchas, failures, and recoveries worth remembering
   - any repeated user correction or frustration that revealed a missing default, checklist item, or workflow rule
2. Move reusable guidance into a topic-specific `.agents/bundles/knowledge/patterns/<topic>.md` chapter and update `.agents/bundles/knowledge/patterns/index.md`.
3. If the work changed architecture, conventions, tooling, operational behavior, or canonical project commands, recursively locate and update the relevant chapter under `.agents/bundles/knowledge/` at its existing project-shaped relative path; keep `.agents/bundles/knowledge/workflow.md` as the stable command default.
4. Promote repeated user corrections or frustration into an obvious durable rule instead of leaving it as a one-off note.
5. Run the normal Flow sync step so `spec.md` reflects the latest state.

### Failure Capture

Capture failure notes whenever one of these happened:

- a hypothesis was wrong
- a command or tool failed in a non-obvious way
- a harness integration behaved differently than expected
- a backend migration exposed a hidden assumption
- a repeated reminder from the user revealed a workflow gap
- the user seemed frustrated that something obvious was forgotten again

Failure notes belong in `learnings.md`, but keep them short and reusable. Focus on what future agents should avoid or check earlier.

### Flow Archive

When a flow is finished:

1. Confirm final reconciliation and verification ran through the Flow state contract.
2. Ensure `learnings.md` is not missing critical discoveries.
3. Elevate the stable patterns and current-state knowledge before archiving.
4. Apply the archive state operation: synthesize current-state knowledge, append
   one bundle-log entry, then delete the completed spec directory recorded by
   the approved archive inventory. Do not create a resident archive tree.
5. Confirm the completed spec directory is absent and no stale scratch file
   remains in the active specs area.

</workflow>

<guardrails>

## Skill Refinement Loop

This skill should improve over time.

When you discover a repeated project nuance, add or revise a short rule below instead of keeping the lesson only in session memory.

Only keep:

- durable project-specific rules
- recurring harness quirks
- recurring workflow misses
- validated project-native command wrappers that should become defaults
- user corrections or frustration that clearly indicate a missing default or checklist item
- archive/sync/learnings habits that proved necessary

Do not keep:

- one-off narrative history
- temporary debugging logs
- duplicate rules already captured elsewhere

</guardrails>

<validation>

Before claiming a task, phase, or flow is complete, verify:

- [ ] `spec.md` was synced through the normal Flow process
- [ ] `learnings.md` captures the durable lessons, failures, and recoveries
- [ ] reusable guidance was elevated to an evidence-backed `.agents/bundles/knowledge/patterns/<topic>.md` chapter when appropriate
- [ ] nested chapters, indexes, and links under `.agents/bundles/knowledge/` reflect current-state knowledge without flattening
- [ ] repeated user corrections or frustration were promoted into an explicit rule when applicable
- [ ] canonical repo commands and verification flows were captured when they were learned or corrected
- [ ] completed flows were contracted without a resident archive tree or stale active-spec clutter

</validation>

## Project Nuances

<!-- project-customization: start -->
- This consumer skill is installed at `.agents/skills/flow-memory-keeper/SKILL.md`;
  `.agents/skills/` is the only operational project-skill authority.
- Maintain Python >= 3.12 compatibility and PEP 585 built-in collection types (`dict`, `list`).
- Run tests with `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false`.
- Always format Python files with `ruff` (`line-length = 120`), run `mypy` (strict gate: `check_untyped_defs = true`, `disallow_incomplete_defs = true`, `disable_error_code = []`, zero `# type: ignore` directives), and place PEP 257 explanations in docstrings (never in-line comments).
- Enforce public-before-private function and method ordering (`# PUBLIC METHODS` and dunder methods before `# PRIVATE METHODS` `_...` helpers) across all modules and classes in `src/goe/`.
- Define CLI and orchestration option models as slot-backed `BaseStruct` / `FrozenBaseStruct` (`gc=False` from `src/goe/typing.py`) in `src/goe/config/options.py`, declarative `OptionSpec` entries in `src/goe/config/option_registry.py`, and declarative runtime settings in `src/goe/config/settings.py` (`GOESettings`); never reintroduce `optparse` or `@dataclass`.
- Route all JSON encoding and decoding through `src/goe/serializers.py` (`encode_json`, `encode_json_bytes`, `encode_json_into`, `format_json`, `decode_json`) and all adapter resolution through `src/goe/offload/registry.py` (`ADAPTER_REGISTRY`).
- Guard optional extra imports (`hdfs`, `requests_kerberos`, `impyla`, `thrift_sasl`, `mssql_python`, `pyodbc`, `snowflake`) at module top-level with `try: ... except ModuleNotFoundError:` (binding base-class fallbacks to `object`, not `None`) or load via `ensure_module(..., extra=...)` (`MissingOptionalDependencyError(OffloadException, ModuleNotFoundError)`), and verify unit tests against `UV_PROJECT_ENVIRONMENT=/tmp/ci-venv uv sync --python .venv/bin/python --dev --locked --offline` so base CI (`uv sync --dev --locked`) stays green.
- Keep `src/goe/util/` restricted to the 7 permitted modules (`__init__.py`, `goe_log.py`, `goe_log_fh.py`, `module_loader.py`, `string_utils.py`, `concurrency.py`, `subprocess_utils.py`), and run `uv run python tools/verify_architecture.py` (via `make lint`) to enforce `raw-json`, `sqlglot-boundary`, `oracledb-boundary`, `nested-import` (`files = []`), `member-ordering`, `inline-comment`, and `stale-baseline` rules.
- Maintain a single authoritative entrypoint in `pyproject.toml` (`[project.scripts] goe = "goe.cli.main:cli"`); legacy `bin/` wrappers were removed in PRD 1 Chapter 1.1 — do not reintroduce wrapper scripts.
- Route Oracle data dictionary and repository SQL through `OracleDatabaseRegistry` (`src/goe/persistence/oracle/registry.py`), `OracleCatalogService` (`src/goe/offload/oracle/catalog.py`), `OracleRepositoryService` (`src/goe/persistence/oracle/oracle_repository.py`), and named `.sql` files (`oracle_catalog.sql`, `frontend_metadata.sql`, `oracle_repo.sql`), and route MSSQL catalog SQL through `MssqlPythonConfig` (`mssql-python`) and `src/goe/offload/microsoft/sql/mssql_catalog.sql` with `FrontendCatalogCache` (`src/goe/offload/frontend_cache.py`).
- Route all DDL/DML, Oracle extraction row-source SQL (`AS OF SCN` / `PARTITION` / `SUBPARTITION`), predicate IR rendering (`src/goe/offload/predicates/`), batched 64-aggregate cross-DB validation queries (`src/goe/offload/validation/`), and `SchemaSyncService` evolution DDL (`src/goe/sync/differ.py`) through `DialectSqlEngine` (`src/goe/offload/sql_ast/`) and the library-agnostic protocols in `src/goe/offload/sql_engine.py`; `[sqlglot-boundary]` in `tools/architecture_baseline.toml` is `files = []`, so callers outside `src/goe/offload/sql_ast/` and `src/goe/offload/predicates/compiler.py` must never import `sqlglot` directly.
- Route local data-plane extractions through `OffloadTransportDuckDB` (`src/goe/offload/transport/duckdb/` over `sqlspec.adapters.duckdb.DuckDBConfig` with cgroup v1/v2 75% memory clamping and mandatory `verify_batch_scn_invariant(query, transport_scn)` before opening any DuckDB connection) or `OffloadTransportQueryImport` (`src/goe/offload/staging/parquet/arrow_writer.py` zero-Python-row Arrow `RecordBatch` to Snappy Parquet streaming), transport selection through `TransportSelector` (`src/goe/offload/transport/selector.py`), and cloud/local object staging through `StagingStorageService` (`src/goe/filesystem/storage_service.py` over `sqlspec.storage`) and `CloudStorageDfsAdapter` (`src/goe/filesystem/goe_dfs.py`).
- Keep OpenTelemetry (`src/goe/observability/`) zero-cost when `GOE_OTEL_ENABLED=false` (never importing `opentelemetry.sdk` on the disabled path) and preserve Oracle `MODULE`/`ACTION` attributes by writing W3C `traceparent` only to `V$SESSION.CLIENT_INFO` (55 bytes) and SQLCommenter comments.
- Represent all frontend, canonical, backend, and staging columns with `ColumnSpec` (`src/goe/offload/schema/column_spec.py`) and translate types through `TYPE_REGISTRY` (`src/goe/offload/schema/type_registry.py`); route backend capability queries through `BackendCapabilities` (`src/goe/offload/backend_capabilities.py`), backend catalog lookups/invalidations through `CachedBackendCatalog` (`src/goe/offload/backend_cache.py`), and staged validation/merge plans through `StagingLoadService` and `FinalTableMerger` (`src/goe/offload/backend_load.py`) or `BigQueryIngestStrategy` (`src/goe/offload/bigquery/ingest_strategy.py`).
<!-- project-customization: end -->

