---
type: Spec
flow_id: cli_subcommand_options_and_defaults_parity_20261004
title: CLI Subcommand Option Completeness & Default Parity
state: completed
plan_revision: 2
plan_commit: null
state_revision: 5
current_task: null
last_operation: 20261004T180830Z-flow-completion-complete-c2-00
operation_targets:
  - spec.md
last_verified_checkpoint: ff03d608c422bac2096653922512523bc9b83fcc
created_at: 2026-10-04T15:00:00Z
updated_at: 2026-10-04T18:08:30Z
description: Restore 12 missing goe offload CLI options, string type for --older-than-days, common options across offload/connect/report/logmgr, and original defaults for report and logmgr
parent_prd: v2_main_alignment_remediation_20261004
tags:
  - spec
  - cli
  - offload
  - connect
  - report
  - logmgr
---

# Spec: CLI Subcommand Option Completeness & Default Parity (`cli_subcommand_options_and_defaults_parity_20261004`)

## 1. Objective & Scope

Ensure `goe offload`, `goe connect`, `goe report`, and `goe logmgr` (and their corresponding `bin/*` wrappers) preserve 100% of the CLI options, option destinations, argument types, and default values from `main` (`ab4f0f9`):
1. **`goe offload` Option Completeness & Type Alignment (`Finding CLI-5a`)**:
   - Apply `@common_options` and `extract_common_options(ctx, kwargs)` to `src/goe/cli/commands/offload.py`.
   - Change `--older-than-days` (`src/goe/cli/commands/offload.py:131-135`) from `type=int` to `type=str` (default string option) so `check_opt_is_posint("--older-than-days", options.older_than_days)` in `src/goe/offload/offload.py:345` receives a `str`.
   - Add the 12 missing options from `src/goe/goe.py:2939-3105`:
     1. `--bucket-hash-column` (`"bucket_hash_col"`)
     2. `--not-null-propagation` (`"not_null_propagation"`, `hidden=True`)
     3. `--hive-column-stats` (`"hive_column_stats"`, `is_flag=True`, `default=None`)
     4. `--offload-stats` (`"offload_stats_method"`)
     5. `--offload-chunk-impala-insert-hint` (`"impala_insert_hint"`)
     6. `--dev-log` (`"dev_log"`, `hidden=True`)
     7. `--dev-log-level` (`"dev_log_level"`, `hidden=True`)
     8. `--transform-column` (`"column_transformation_list"`, `multiple=True`, `hidden=True`)
     9. `--offload-transport-validation-polling-interval` (`"offload_transport_validation_polling_interval"`, `hidden=True`)
     10. `--sqoop-additional-options` (`"sqoop_additional_options"`)
     11. `--sqoop-mapreduce-map-memory-mb` (`"sqoop_mapreduce_map_memory_mb"`, `type=int`)
     12. `--sqoop-mapreduce-map-java-opts` (`"sqoop_mapreduce_map_java_opts"`)
   - Register the newly added visible options in `OPTION_GROUPS["goe offload"]` in `src/goe/cli/config.py:51-148`.
2. **`goe connect`, `goe report`, and `goe logmgr` Parity (`Finding CLI-5b`)**:
   - `src/goe/cli/commands/connect.py`: Apply `@common_options` and add hidden `--create-backend-db` (`"create_backend_db"`, `is_flag=True`, `default=None`, `hidden=True`).
   - `src/goe/cli/commands/report.py`: Apply `@common_options`, restore `-o/--output-format` default to `"text"` and `--output-level` default to `"summary"` (matching `src/goe/offload/offload_status_report.py:71-72`), add hidden `-d/--demo` (`"demo_mode"`, `is_flag=True`, `default=None`, `hidden=True`), and propagate `"ansi"` via `extract_common_options(ctx, kwargs)`.
   - `src/goe/cli/commands/logmgr.py`: Apply `@common_options` and default `min_age_minutes` to `int(os.environ.get("LOG_MV_MINS", 60))` when `--min-age-minutes` is not explicitly provided on the CLI (`main:bin/logmgr:28`).

---

## 2. Requirements & Acceptance Criteria

- **REQ-C2-01**: `src/goe/cli/commands/offload.py` must apply `@common_options`, pass `--older-than-days` as `str`, and expose all 12 missing options from `src/goe/goe.py:2939-3105` with exact destination keys.
- **REQ-C2-02**: `src/goe/cli/config.py` must include `--bucket-hash-column`, `--hive-column-stats`, `--offload-stats`, `--offload-chunk-impala-insert-hint`, `--sqoop-additional-options`, `--sqoop-mapreduce-map-memory-mb`, and `--sqoop-mapreduce-map-java-opts` in `OPTION_GROUPS["goe offload"]`.
- **REQ-C2-03**: `src/goe/cli/commands/connect.py` must apply `@common_options` and expose `--create-backend-db` (`hidden=True`).
- **REQ-C2-04**: `src/goe/cli/commands/report.py` must apply `@common_options`, default `-o/--output-format` to `"text"` and `--output-level` to `"summary"`, expose `-d/--demo` (`"demo_mode"`, `hidden=True`), and propagate `"ansi"` to `offload_status_report_run`.
- **REQ-C2-05**: `src/goe/cli/commands/logmgr.py` must apply `@common_options` and honor `LOG_MV_MINS` from `os.environ` (defaulting to `60`) when `--min-age-minutes` is omitted.

---

## Implementation Plan

### Phase 1: `offload`, `connect`, `report`, and `logmgr` Option & Default Parity [checkpoint: ff03d608c422bac2096653922512523bc9b83fcc]

- [x] Task T1.1: [`goe offload` CLI Option Completeness & Option Groups](tasks/T1.1.md) (`depends_on`: `["cli_execution_and_common_options_parity_20261004:T1.1"]`; `files`: `src/goe/cli/commands/offload.py`, `src/goe/cli/config.py`; `tests`: `tests/unit/cli/test_offload_command.py`) — `8c85b161a0d86670a2a7383dc4a022c8ae5c9bbd`
- [x] Task T1.2: [`goe connect`, `goe report`, and `goe logmgr` Option & Default Parity](tasks/T1.2.md) (`depends_on`: `["cli_subcommand_options_and_defaults_parity_20261004:T1.1"]`; `files`: `src/goe/cli/commands/connect.py`, `src/goe/cli/commands/report.py`, `src/goe/cli/commands/logmgr.py`; `tests`: `tests/unit/cli/test_connect_command.py`, `tests/unit/cli/test_report_command.py`, `tests/unit/cli/test_logmgr_command.py`) — `ff03d608c422bac2096653922512523bc9b83fcc`

---

## 4. Requirement-to-Task & Test Traceability Matrix

| Requirement ID | Description | Task ID | Target Source Files | Verification Test Files |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-C2-01** | `goe offload` `@common_options`, `--older-than-days` `str`, and 12 missing options | `T1.1` | `src/goe/cli/commands/offload.py` | `tests/unit/cli/test_offload_command.py` |
| **REQ-C2-02** | `OPTION_GROUPS["goe offload"]` registration for newly added visible options | `T1.1` | `src/goe/cli/config.py` | `tests/unit/cli/test_offload_command.py` |
| **REQ-C2-03** | `goe connect` `@common_options` and hidden `--create-backend-db` | `T1.2` | `src/goe/cli/commands/connect.py` | `tests/unit/cli/test_connect_command.py` |
| **REQ-C2-04** | `goe report` `@common_options`, `"text"` / `"summary"` defaults, `-d/--demo`, and `"ansi"` propagation | `T1.2` | `src/goe/cli/commands/report.py` | `tests/unit/cli/test_report_command.py` |
| **REQ-C2-05** | `goe logmgr` `@common_options` and `LOG_MV_MINS` fallback | `T1.2` | `src/goe/cli/commands/logmgr.py` | `tests/unit/cli/test_logmgr_command.py` |

---

## Continuity Snapshot

- **Active Flow**: `cli_subcommand_options_and_defaults_parity_20261004`
- **Lifecycle State**: `completed`
- **Current Task**: `null`
- **Claimant**: `null`
- **Last Verified Checkpoint**: `ff03d608c422bac2096653922512523bc9b83fcc`
- **Decisions**: Apply `@common_options` and `extract_common_options` across `offload`, `connect`, `report`, and `logmgr`; pass `--older-than-days` as `str`; restore 12 missing `offload` options and register visible ones in `OPTION_GROUPS["goe offload"]`.
- **Recent Discoveries**: Completed `code-reviewer` and `quality-reviewer` passes with 0 findings on `c635ac76ab53fbfb3823d317732bed4a49c4da28..ff03d608c422bac2096653922512523bc9b83fcc`.
- **Blockers & Unblock Conditions**: None
- **Next Exact Step**: Proceed to Chapter 3 (`listener_and_persistence_schema_alignment_20261004`)
- **Plan Identity**: `plan_revision: 2`, `plan_commit: null`
- **State Identity**: `revision: 5`, `last_operation: 20261004T180830Z-flow-completion-complete-c2-00`, `operation_targets: ["spec.md"]`
- **Relevant Knowledge Paths**: `.agents/bundles/knowledge/workflow.md`, `.agents/bundles/knowledge/patterns/cli-architecture.md`



