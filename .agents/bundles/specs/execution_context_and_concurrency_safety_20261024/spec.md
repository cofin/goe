---
type: Spec
flow_id: execution_context_and_concurrency_safety_20261024
title: "Chapter 10.1: Execution Context and Concurrency Safety"
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
description: "Route orchestration log lines and step records through a ContextVar-bound ExecutionContext and its sinks, remove module-global and shared-runner state, and fix the execution-path defects that break concurrent offloads in one process."
tags: [refactor, orchestration, concurrency, logging]
parent_prd: prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024
depends_on:
  - prd_05_foundation_typing_settings_and_adapter_reduction_20261024
  - prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024
  - prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024
  - prd_08_duckdb2_transport_query_import_parity_and_storage_20261024
  - prd_09_composable_backends_and_direct_bigquery_ingestion_20261024
research:
  - .agents/bundles/specs/prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/module-by-module-redesign.md
  - .agents/bundles/specs/prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/vertebra-and-runtime-evaluation.md
---

# Chapter 10.1: Execution Context and Concurrency Safety

## Specification

### 1. Overview and Goals

GOE runs offloads concurrently inside one process once the Listener executes jobs in worker threads. Today the orchestration log state is module-global, the Listener shares one `OrchestrationRunner` whose per-command fields are overwritten by each job, and several execution-path helpers mutate shared configuration or the process environment. This chapter makes concurrent execution safe without changing what a user sees:

1. A `ContextVar`-bound `ExecutionContext(FrozenBaseStruct)` (new `src/goe/orchestration/context.py`) carries the execution identity, console policy, and an ordered tuple of `ExecutionSink`s (new `src/goe/orchestration/sinks.py`: `LogFileSink`, `ConsoleSink`, `TelemetrySink`, `RepositoryStepSink`).
2. `src/goe/orchestration/logging_init.py` and `OffloadMessages` (`src/goe/offload/offload_messages.py`) emit events through the context instead of module globals; default text stdout and log file bytes stay identical, and repository `COMMAND_EXECUTION_STEP` writes keep their arguments.
3. `OrchestrationRunner` keeps no per-command instance state and accepts extra sinks (used by Chapter 10.4 for the `ListenerCacheSink`); the Listener builds a runner per job.
4. Defect fixes with regression tests: the unraised `OffloadException`, the in-place `override_offload_dfs_config` mutation, racy `NLS_LANG` mutation, the leaked backend API and the wrong `get_hybrid_metadata` argument in `validate_sort_columns`, the throwaway Oracle connection used only to read an identifier length that nothing reads, and the double settings construction in `offload_by_cli`.

### 2. Code Analysis Summary

Line references are at HEAD `d6a02fe`. PRDs 5–9 run first; tasks anchor edits by symbol name where those PRDs change surrounding code.

- `src/goe/orchestration/logging_init.py:18-21` defines module globals `options`, `log_fh`, `suppress_stdout_override`, `ts`. `log()` (`:28-54`) writes every line to `log_fh` (falling back to `sys.stderr`), prints unwrapped lines when `options` is unset, prints `.` in quiet mode, and gates stdout by `options.verbose`/`options.vverbose` and `suppress_stdout_override`. `init()` (`:139-145`) replaces `options`; `init_log()` (`:114-131`) replaces `log_fh`. Two jobs in one process overwrite each other's log handle and options.
- `src/goe/orchestration/execution.py:438-439` constructs `OffloadException(...)` without `raise`; `:440` sets `logging_init.suppress_stdout_override`; `:442-446` calls `offload_options.override_offload_dfs_config(...)`, which mutates the shared settings object (`src/goe/config/orchestration_config.py:863-875`); `:640` calls `check_and_set_nls_lang` on every execution.
- `src/goe/orchestration/operation.py:181-196` sets `os.environ["NLS_LANG"]` from whichever thread first sees it unset; two concurrent executions both query the database character set and both write the variable. `:1173`/`:1181` set `created_api = False` even when the method constructs a backend API, so the `finally` at `:1204-1206` never closes it; `:1193-1194` passes `offload_options` into `get_hybrid_metadata(force: bool)` (`:787-797`). `validate_sort_columns` has exactly one production caller (`execution.py:392-399`).
- `src/goe/orchestration/orchestration_runner.py:64-69` stores `_execution_id`, `_messages`, and `_max_hybrid_name_length` on the instance; `_init_command` (`:338-367`) overwrites `_execution_id` and `_messages` per command (`:351-352`). `_get_max_hybrid_identifier_length` (`:320-336`) opens and closes a frontend connection to read `max_table_name_length()`; the value flows into `OffloadOperation(max_hybrid_name_length=...)` and is written at `operation.py:664` but never read (`git grep -n '\.max_hybrid_name_length' src/goe` shows only that assignment).
- `src/goe/listener/services/orchestrate.py:13-31` holds the module-global `_runner` built once with `OrchestrationRunner(suppress_stdout=True)`; `src/goe/listener/jobs.py:17-22` calls `orchestration_runner.offload(...)` through `async_` in a worker thread. The roadmap row names this file `src/goe/listener/services/orchestration.py`; the file at HEAD is `services/orchestrate.py`.
- `src/goe/orchestration/cli_entry_points.py:47-59` builds `OrchestrationConfig.from_dict(config_overrides)` for connectivity logging and passes the same overrides to `OrchestrationRunner(config_overrides=...)`, whose `_gen_config` (`orchestration_runner.py:263-267`) builds a second settings object.
- `src/goe/offload/offload_messages.py:40-63` defines `QUIET`..`SUPPRESS_STDOUT` and `COLORS`; `log()` (`:202-225`) writes the file line then the console line with ANSI wrapping (`ansi_wrap`, `:174-182`) and disables stdout after an `OSError` while logging the reason to the file; `warning()` (`:244-248`) also calls `add_span_log_event`; `offload_step()` (`:270-399`) wraps the step in `traced_step`, records skipped steps with `record_skipped_step`, and calls `repo_client.start_command_step` / `end_command_step` with trace ids. 139 modules import names from this module (`git grep -l "from goe.offload.offload_messages import"`), so its public names stay importable from it.
- Existing tests: `tests/unit/offload/test_offload_messages.py` (no byte-level stdout assertions), `tests/unit/orchestration/test_goe_orchestration_characterization.py`, `tests/unit/listener/test_jobs.py`, `tests/unit/listener/test_orchestration_controllers.py`. No test covers `logging_init` output, `offload_table` guards, `OrchestrationRunner` state, or `validate_sort_columns`.

### 3. Requirements

- **R1** `ExecutionContext(FrozenBaseStruct)` is bound through a module-level `ContextVar`; `bind_execution_context` restores the previous value on exit; contexts bound in different threads or tasks never see each other's sinks.
- **R2** `ExecutionSink` protocol with `LogFileSink`, `ConsoleSink`, `TelemetrySink`, and `RepositoryStepSink`; events are frozen structs (`LogEvent`, `WarningEvent`, `StepStartedEvent`, `StepFinishedEvent`, `StepSkippedEvent`); `ConsoleSink` reproduces `OffloadMessages.log` stdout rules exactly.
- **R3** `logging_init` keeps its public function names and signatures but stores no module-level mutable state; `OffloadMessages` routes every line, warning, step start, step end, and skipped step through its context; default text stdout and log text stay byte-identical; repository step calls keep their arguments.
- **R4** `OrchestrationRunner` has no per-command instance attributes, takes a prebuilt settings object, and accepts `sinks` appended to the per-command context; `offload_by_cli` builds settings once; the Listener constructs a runner per job and keeps no module-global runner.
- **R5** `offload_table` raises `OffloadException("Unsupported Offload target: <target>")` for targets outside the backends PRD 9 keeps, and never mutates the settings object it receives.
- **R6** `NLS_LANG` is resolved and written at most once per process under a lock.
- **R7** `validate_sort_columns` closes any backend API it creates and calls `get_hybrid_metadata()` with no argument; the unused `max_hybrid_name_length` plumbing and its frontend connection are deleted.
- **Non-functional**: no new dependencies; architecture gate, `ruff`, and `mypy src/goe` stay green; public-before-private ordering in every touched module.
- **Risks and mitigations**: byte drift in stdout (mitigated by Task 1.1 golden transcripts run before and after every later task); sinks held by a `gc=False` struct (sinks never reference the context, so no reference cycle); Chapter 5.3 may have changed the settings type (Task 1.3 picks the derivation that matches the type found at execution time and keeps only that one).

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1 | 1.2 | `tests/unit/orchestration/test_context.py` |
| R2 | 1.2 | `tests/unit/orchestration/test_sinks.py` |
| R3 | 1.1, 1.3 | `tests/unit/offload/test_offload_messages.py`, `tests/unit/orchestration/test_logging_init.py` |
| R4 | 1.4 | `tests/unit/orchestration/test_orchestration_runner.py`, `tests/unit/orchestration/test_cli_entry_points.py`, `tests/unit/listener/test_jobs.py` |
| R5 | 1.3 | `tests/unit/orchestration/test_execution.py` |
| R6 | 1.4 | `tests/unit/orchestration/test_operation.py` |
| R7 | 1.4 | `tests/unit/orchestration/test_operation.py`, `tests/unit/orchestration/test_orchestration_runner.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/orchestration tests/unit/offload/test_offload_messages.py tests/unit/listener -q
uv run pytest tests/unit/characterization -q
uv run pytest tests/unit -q
uv run ruff format --check src/goe tests/unit
uv run ruff check src/goe tests/unit
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Baseline and Context Primitives

- [ ] 1.1 Pin byte-exact console and log output ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Add ExecutionContext and execution sinks ([tasks/1.2.md](tasks/1.2.md))

### Phase 2: Adoption and Defect Fixes

- [ ] 1.3 Route orchestration logging through the execution context and fix execution-state defects ([tasks/1.3.md](tasks/1.3.md))
- [ ] 1.4 Make OrchestrationRunner stateless and fix operation defects ([tasks/1.4.md](tasks/1.4.md))

## Continuity Snapshot

- **Flow / lifecycle**: `execution_context_and_concurrency_safety_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: verbosity constants, `COLORS`, and `ansi_wrap` move to `goe.orchestration.sinks` and stay importable from `goe.offload.offload_messages` because it uses them; `traced_step` stays a context manager inside `offload_step` (span parentage needs lexical scope) while skipped-step and warning span events go through `TelemetrySink`; the unsupported-target guard accepts the backends PRD 9 preserves (`bigquery`, `snowflake`, `synapse`, `hive`, `impala`, `spark`); `ListenerCacheSink` is implemented in Chapter 10.4 because `ListenerCache` is created there.
- **Discoveries**: none yet.
- **Blockers**: Master PRDs 5–9 must complete first.
- **Next exact step**: execute task `1.1` (`execution_context_and_concurrency_safety_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/architecture/orchestration.md`, `.agents/bundles/knowledge/operations/observability.md`, `.agents/bundles/knowledge/standards/testing.md`, `.agents/bundles/knowledge/workflow.md`.
