---
type: Spec
flow_id: schema_sync_and_status_report_redesign_20261024
title: "Chapter 7.4: Schema Sync and Status Report Redesign"
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
description: "Replace multi-pass schema sync and N+1 status report modules with single-pass SchemaDiff and SchemaSyncService in goe.sync, concurrent set-based StatusReportService in goe.report, and clean CLI and Listener wiring while retiring legacy schema_sync, status_report, and ora_query modules."
tags: [refactor, schema-sync, reporting, sqlglot, concurrency]
parent_prd: prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024
depends_on: [concurrent_cross_db_validation_20261024]
research:
  - .agents/bundles/specs/prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024/research/sqlspec-sqlglot-and-caching-architecture.md
  - .agents/bundles/specs/prd_05_foundation_typing_settings_and_adapter_reduction_20261024/research/module-by-module-redesign.md
---

# Chapter 7.4: Schema Sync and Status Report Redesign

## Specification

### 1. Overview and Goals

GOE's schema synchronization package (`src/goe/schema_sync/`, 1,738 LOC across analyzer, processor, runner, command file, and step classes) currently rebuilds `OffloadSourceTable` 6 to 7 times per table, leaks proxy Oracle connections in `src/goe/schema_sync/steps/add_oracle_column.py:55-65`, contains raw f-string SQL interpolation in `src/goe/schema_sync/schema_sync_analyzer.py:49-57`, raises `NotImplementedError` on `PRESENT_TABLE`, and writes stray `}');` characters to command files. Similarly, the offload status report (`src/goe/offload/offload_status_report.py` and `src/goe/report/`, 3,799 LOC plus `src/goe/util/ora_query.py`, 348 LOC) executes thousands of sequential per-table `dba_segments` queries and per-table BigQuery RPCs, ships a 1,502-LOC Python literal demo file (`demo_data.py`), and has a broken Jinja2 template path in `src/goe/report/renderers.py` and an undefined `INCREMENTAL_PREDICATE_TYPE` variable in `goe_components.html:352`.

This chapter:

1. Replaces `src/goe/schema_sync/` with `src/goe/sync/differ.py` (`ColumnAddition`, `TypeWidening`, `NullabilityRelaxation`, `PartitionDrop`, `SchemaDiff(FrozenBaseStruct)`, and `SchemaSyncService`), computing schema drift in a single pass between `OracleTableSnapshot` and backend `ColumnMetadata` and emitting `ALTER TABLE` and view evolution DDL via `DialectSqlEngine`.
2. Replaces the legacy status report collector and `src/goe/util/ora_query.py` with `src/goe/report/models.py` and `src/goe/report/service.py` (`PartitionStatusRow(FrozenBaseStruct)`, `TableStatusReport(FrozenBaseStruct)`, `StatusReportEnvelope(FrozenBaseStruct)`, and `StatusReportService`), querying `OracleCatalogService`, `OracleRepositoryService`, and backend metadata concurrently via `run_bounded`, rolling up summaries in DuckDB 2.0 `GROUP BY ROLLUP`, and serializing console tables and JSON through `goe.util.serializers`.
3. Wires `src/goe/cli/commands/sync.py`, `src/goe/cli/commands/report.py`, and the Listener status/sync endpoints (`src/goe/listener/controllers/system.py` and `src/goe/listener/services/system.py`) directly to `SchemaSyncService` and `StatusReportService`.

### 2. Code Analysis Summary

- `src/goe/schema_sync/schema_sync.py:39-125`: orchestrates `SchemaSyncAnalyzer`, `SchemaSyncProcessor`, and `SchemaSyncCommandFile` while acquiring per-table orchestration locks.
- `src/goe/schema_sync/schema_sync_analyzer.py:49-57`: dead `ddl_compare` constructs unquoted SQL via f-strings; `compare_structures` repeatedly instantiates source and backend tables.
- `src/goe/schema_sync/steps/add_oracle_column.py:55-65`: opens a proxy Oracle session (`ora_adm_user[schema]`) using `ora_app_pass` instead of `ora_adm_pass` (`ORA-01017` when passwords differ) and never closes the connection.
- `src/goe/report/renderers.py:12-80`: imports `jinja2` and constants from `src/goe/report/models.py`; template lookup fails when packaged outside the repo root, and `src/goe/report/templates/goe_components.html:352` references an undefined `INCREMENTAL_PREDICATE_TYPE` variable.
- `src/goe/report/demo_data.py:1-1502`: stores a 1,502-LOC hardcoded Python dictionary for `goe report --demo`.
- `src/goe/util/ora_query.py:1-348`: legacy raw `oracledb` cursor wrapper whose last remaining callers are the legacy status report and schema sync modules.
- `src/goe/cli/commands/sync.py:70-100` and `src/goe/cli/commands/report.py:61-74`: CLI entry points currently lazy-importing `goe.schema_sync.schema_sync` and `goe.offload.offload_status_report`.

### 3. Requirements

- R1. `src/goe/sync/differ.py` defines `ColumnAddition(FrozenBaseStruct)`, `TypeWidening(FrozenBaseStruct)`, `NullabilityRelaxation(FrozenBaseStruct)`, `PartitionDrop(FrozenBaseStruct)`, `SchemaDiff(FrozenBaseStruct)`, and `SchemaSyncService`, computing diffs between `OracleTableSnapshot` and backend `ColumnMetadata` in one pass, generating `ALTER TABLE` and view DDL via `DialectSqlEngine`, executing hybrid Oracle DDL through `OracleDatabaseRegistry.proxy_ddl_session` without connection leaks, writing clean command files without trailing `}');`, and retiring `src/goe/schema_sync/`.
- R2. `src/goe/report/models.py` and `src/goe/report/service.py` define `PartitionStatusRow(FrozenBaseStruct)`, `TableStatusReport(FrozenBaseStruct)`, `StatusReportEnvelope(FrozenBaseStruct)`, and `StatusReportService`, fetching catalog, repository, and backend metadata concurrently via `run_bounded`, aggregating schema and table totals via DuckDB 2.0 `GROUP BY ROLLUP`, formatting JSON via `goe.util.serializers`, fixing `renderers.py` and `goe_components.html:352`, replacing `demo_data.py` with `demo_report.json.gz` while preserving golden `goe report --demo` digests, and retiring `src/goe/util/ora_query.py`.
- R3. `src/goe/cli/commands/sync.py`, `src/goe/cli/commands/report.py`, and Listener status/sync endpoints delegate to `SchemaSyncService` and `StatusReportService`, acquiring per-table locks via `OrchestrationLockInterface` during `sync --execute`.
- R4 (risk). Retiring `src/goe/schema_sync/` and `src/goe/util/ora_query.py` could leave dangling imports in CLI or Listener modules. Mitigation: Task 1.3 updates all CLI and Listener callers and runs `git grep` and `tools/verify_architecture.py` across `src/goe` and `tests/unit`.
- R5 (risk). Replacing `demo_data.py` could alter `goe report --demo` output digests. Mitigation: `StatusReportEnvelope.to_report_dict()` emits the exact dictionary schema expected by HTML/TEXT/JSON/RAW/CSV renderers and is verified against the golden digest.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| --- | --- | --- |
| R1 | 1.1 | `tests/unit/sync/test_differ.py` diff computation, `DialectSqlEngine` DDL generation, proxy DDL session, and command file tests |
| R2 | 1.2 | `tests/unit/report/test_service.py` concurrent `run_bounded` collection, DuckDB rollup, `goe.util.serializers` JSON formatting, and `--demo` digest tests |
| R3 | 1.3 | `tests/unit/cli/test_sync_and_report_commands.py` CLI and Listener service delegation tests |
| R4 | 1.3 | `git grep -n -E "goe\.schema_sync|ora_query|offload_status_report" -- src` returning nothing |
| R5 | 1.2 | `test_status_report_demo_mode_matches_golden_digest` in `tests/unit/report/test_service.py` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/sync tests/unit/report tests/unit/cli/test_sync_and_report_commands.py -v
uv run ruff format --check src/goe/sync src/goe/report src/goe/cli/commands/sync.py src/goe/cli/commands/report.py tests/unit/sync tests/unit/report tests/unit/cli
uv run ruff check src/goe/sync src/goe/report src/goe/cli/commands/sync.py src/goe/cli/commands/report.py tests/unit/sync tests/unit/report tests/unit/cli
uv run mypy src/goe
uv run python tools/verify_architecture.py
git grep -n -E "goe\.schema_sync|ora_query|offload_status_report" -- src
```

## Implementation Plan

### Phase 1: Schema Sync Differ, Set-Based Status Report, and CLI/Listener Wiring
- [ ] 1.1 Implement `SchemaDiff` and `SchemaSyncService` in `src/goe/sync/differ.py` and retire `src/goe/schema_sync/` ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Implement `TableStatusReport`, `PartitionStatusRow`, and `StatusReportService` in `src/goe/report/` and retire `ora_query.py` ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Wire `cli/commands/sync.py`, `cli/commands/report.py`, and Listener endpoints to `SchemaSyncService` and `StatusReportService` ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `schema_sync_and_status_report_redesign_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: consolidate schema sync into `src/goe/sync/differ.py` using `FrozenBaseStruct` diff models and `DialectSqlEngine` `ALTER TABLE` / view DDL builders; execute Oracle hybrid DDL through `OracleDatabaseRegistry.proxy_ddl_session`; consolidate status report collection and DuckDB rollup into `src/goe/report/models.py` and `src/goe/report/service.py` with concurrent `run_bounded` metadata queries and `goe.util.serializers` JSON output; delete `src/goe/schema_sync/`, `src/goe/offload/offload_status_report.py`, `src/goe/report/demo_data.py`, and `src/goe/util/ora_query.py`.
- **Discoveries**: none yet.
- **Blockers**: Chapter 7.3 (`concurrent_cross_db_validation_20261024`) and PRD 6 (`OracleCatalogService`, `OracleRepositoryService`, `OracleDatabaseRegistry`) must complete first.
- **Next exact step**: execute task `1.1` (`schema_sync_and_status_report_redesign_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/architecture/schema-evolution.md`, `.agents/bundles/knowledge/standards/database-and-sql.md`, `.agents/bundles/knowledge/operations/cli-tools.md`.
