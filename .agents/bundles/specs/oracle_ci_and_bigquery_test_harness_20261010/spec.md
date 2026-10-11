---
type: Spec
flow_id: oracle_ci_and_bigquery_test_harness_20261010
title: "Chapter 1.3: Oracle 23ai Free CI Container, BigQuery Integration Harness, and Golden Dry-Run Characterization Suite"
state: completed
plan_revision: 3
plan_commit: null
state_revision: 4
current_task: null
last_operation: 20261011T155835Z-flow-executor-close-1-3-00
operation_targets: ["1.3"]
last_verified_checkpoint: bc6fc94
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-11T15:58:35Z
description: "Fix integration test collection and latent test framework bugs, provision a non-interactive Oracle 23ai Free CI container and WIF-authenticated BigQuery workflow, and establish a deterministic golden dry-run (execute=False) characterization test suite."
tags: [testing, ci, oracle, bigquery]
parent: prd_01_foundation_adc_and_ci_harness_20261010
depends_on: [gcp_adc_credential_unification_20261010]
research: []
---

# Chapter 1.3: Oracle 23ai Free CI Container, BigQuery Integration Harness, and Golden Dry-Run Characterization Suite

## Specification

### Code Analysis Summary (Verified at `46890a8`)
- **Integration Test Collection Crash & Latent Test Framework Bugs**:
  - `tests/integration/persistence/test_orchestration_metadata.py:139-145`: `TestOrchestrationMetadata.__init__` eagerly invokes `build_current_options()`, `get_test_messages(self.config, "TestOrchestrationMetadata")`, and `get_default_test_user()` during `unittest.TestCase` instantiation at pytest collection time. When `offload.env` / `ORA_CONN` is absent, `build_current_options()` raises `goe.config.config_validation_functions.OrchestrationConfigException: Oracle connection options required`, aborting `GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only`.
  - `tests/integration/offload/test_offload_source_table.py:120,127` (`_test_get_stored_object_dependent_schemas` and `_test_has_rowdependencies`) and `tests/unit/offload/test_offload_source_table.py:92` (`_test_parallel_query_hint`): compare `if self.config == DBTYPE_ORACLE:` instead of `if self.config.db_type == DBTYPE_ORACLE:`, causing those Oracle-specific assertions to be silently skipped in every test run.
  - `tests/testlib/test_framework/test_functions.py:120-124`: `text_in_log(search_text, search_from_text="") -> bool` calls `get_line_from_log(search_text, search_from_text=search_from_text)` without the required first positional parameter `messages: OffloadMessages` expected by `get_line_from_log(messages: OffloadMessages, search_text, search_from_text="")` at line 94, and its caller in `tests/integration/orchestration/test_orchestration_runner.py:117` omits `messages`. (Note: the legacy `redis_publish=False` keyword in `tests/testlib/test_framework/test_functions.py:111-113` is already removed by Chapter 1.1 Task `1.2`.)
  - `tests/integration/` has no `conftest.py` to register markers (`oracle`, `bigquery`, `gcs`, `spark`) or gracefully skip live database/cloud suites when credentials are not configured.
- **Interactive Oracle SQL Bootstrap & Unit-Only CI**:
  - `sql/oracle/source/install_offload.sql:13-20` invokes `@@sql/install_env.sql`, `@@sql/create_offload_users.sql`, `@@sql/create_offload_privs.sql`, `alter session set current_schema = &goe_db_adm_user;`, `@@sql/install_offload_code.sql`, `@@sql/create_offload_repo.sql`, and `@@sql/upgrade_goe_version.sql`. The interactive `ACCEPT` and `PAUSE` prompts live inside `sql/oracle/source/sql/install_env.sql`, `sql/oracle/source/sql/install_repo_env.sql`, and `sql/oracle/source/sql/verify_env.sql`, and `Makefile:184-185` substitutes `VERSION`/`BUILD` in `sql/install_env.sql` and `sql/upgrade_env.sql` and `'%s-SNAPSHOT'` in `sql/create_offload*_package_spec.sql`.
  - `.github/workflows/test.yaml:1-72` (called by `.github/workflows/ci.yaml:26-38` across Python `3.12`, `3.13`, `3.14`) only runs unit tests (`pytest tests/unit`) and never exercises `sql/oracle/source/` PL/SQL installation or `tests/integration/persistence/` and `tests/integration/offload/`.
- **Missing Deterministic Dry-Run (`execute=False`) Characterization Suite**:
  - While subsequent PRDs refactor `OrchestrationConfig`, option structs, `src/goe/goe.py`, `BackendBigQueryApi`, and `sqlglot` AST builders, there is no fast, offline golden characterization suite in `tests/unit/characterization/test_offload_bigquery_golden.py` asserting the exact sequence of generated BigQuery `CREATE TABLE` / `PARTITION BY` / `CLUSTER BY` DDL, external staging table DDL, staging-to-final `INSERT INTO ... SELECT` casts, IPA `RANGE` native and synthetic numeric range bucket partitioning + chunking, IPA `LIST`/`RANGE` subpartition discovery, `GenericPredicate` Oracle/BigQuery `WHERE` rendering, and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` schema evolution in dry-run (`dry_run=True, do_not_connect=True`) mode.

### Relevant Patterns & Conventions
- [Testing Standards](../../knowledge/standards/testing.md)
- [Patterns Index](../../knowledge/patterns/index.md)

### Requirements
- **REQ-1**: Fix `TestOrchestrationMetadata` (`tests/integration/persistence/test_orchestration_metadata.py:139-145`) by moving `self.config`, `self.messages`, and `self.db` initialization into `setUp()`, fix `self.config.db_type == DBTYPE_ORACLE` in `tests/integration/offload/test_offload_source_table.py:120,127` and `tests/unit/offload/test_offload_source_table.py:92`, fix `text_in_log(messages, ...)` in `tests/testlib/test_framework/test_functions.py:120-124` and its caller in `tests/integration/orchestration/test_orchestration_runner.py:117`, reorder `TestOrchestrationMetadata` (`tests/integration/persistence/test_orchestration_metadata.py`) and `TestCurrentOffloadSourceTable` (`tests/integration/offload/test_offload_source_table.py`) so public/test methods precede private (`_...`) helpers, register pytest markers (`oracle`, `bigquery`, `gcs`, `spark`) in `pyproject.toml`, and create `tests/integration/conftest.py` so `GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only` succeeds offline (`147 tests collected`).
- **REQ-2**: Create a non-interactive idempotent bootstrap script `sql/oracle/source/bootstrap_ci.sh` that stages `sql/oracle/source/*`, applies `Makefile`-matching `VERSION`/`BUILD` and `'%s-SNAPSHOT'` substitutions, pre-defines SQL*Plus variables (`goe_version`, `goe_build`, `goe_db_user_prefix`, `goe_db_user_profile`, `goe_db_adm_user`, `goe_db_app_user`, `goe_db_repo_user`, `goe_repo_install`, `goe_repo_upgrade`, `goe_raise_existing_repo_role`, `goe_repo_tablespace`, `goe_repo_ts_quota`), runs the real scripts in `sql/oracle/source/sql/` (`create_offload_users.sql`, `create_offload_privs.sql`, `install_offload_code.sql`, `create_offload_repo.sql`, `upgrade_goe_version.sql`), unlocks `GOE_ADM`/`GOE_APP`/`GOE_REPO`, and provisions `GOE_TEST`/`SH_TEST` in `gvenzl/oracle-free:23-slim-faststart` (`FREEPDB1`); and update `.github/workflows/test.yaml`, `.github/workflows/ci.yaml`, `.gitignore`, and `Makefile` with `integration-oracle` and opt-in keyless WIF `integration-bigquery` jobs (gated to `inputs.python-version == '3.12'`).
- **REQ-3**: Create `tests/unit/characterization/__init__.py` and `tests/unit/characterization/test_offload_bigquery_golden.py` (with public fixtures and `test_*` functions grouped before `_build_bq_table`) capturing and verifying deterministic offline dry-run (`dry_run=True, do_not_connect=True`) artifacts across 5 golden scenarios: RBO (`CREATE TABLE ... CLUSTER BY`, external Avro staging DDL, `INSERT INTO ... SELECT` casts), IPA `RANGE` (native `DATETIME_TRUNC`, synthetic `INT64` `RANGE_BUCKET`, and `OffloadSourceDataIpaRange` partition chunking), IPA `LIST`/`RANGE` subpartition discovery (`OffloadSourcePartitions.from_source_table`), PBO (`GenericPredicate` AST to Oracle and BigQuery `WHERE` clauses), and BigQuery `add_columns` schema evolution (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).

### Requirement Traceability Matrix

| Requirement | Task ID | Verification Strategy | Verification Target |
| :--- | :--- | :--- | :--- |
| REQ-1 | `1.1` | `regression_tdd` | `GOE_NO_AUTOLOAD_ENV=1 GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run pytest tests/integration --collect-only && GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run pytest tests/unit/offload/test_offload_source_table.py -v`; AST public-before-private check on touched files |
| REQ-2 | `1.2` | `static_validation` | `bash -n sql/oracle/source/bootstrap_ci.sh && test -x sql/oracle/source/bootstrap_ci.sh && make -n test-integration-oracle` |
| REQ-3 | `1.3` | `characterization` | `GOOGLE_API_USE_CLIENT_CERTIFICATE=false uv run pytest tests/unit/characterization/test_offload_bigquery_golden.py -v`; AST public-before-private check on `test_offload_bigquery_golden.py` |

---

## Implementation Plan

- [x] 1.1 Fix integration test collection crash, repair latent test framework bugs, and add `tests/integration/conftest.py` ([tasks/1.1.md](tasks/1.1.md)) [P0, regression_tdd]
- [x] 1.2 Create `sql/oracle/source/bootstrap_ci.sh` and configure Oracle 23ai Free + WIF BigQuery CI jobs ([tasks/1.2.md](tasks/1.2.md)) (depends on: 1.1) [P1, static_validation]
- [x] 1.3 Create golden dry-run (`execute=False`) characterization test suite for Oracle-to-BigQuery offloads ([tasks/1.3.md](tasks/1.3.md)) (depends on: 1.1) [P0, characterization]

---

## Continuity Snapshot

- **Flow / lifecycle**: `oracle_ci_and_bigquery_test_harness_20261010` (`state: completed`).
- **Current task / claimant**: `current_task: null` / `claimed_by: null`.
- **Last verified checkpoint**: `bc6fc94`.
- **Plan identity**: `plan_revision: 3`, `plan_commit: null`.
- **State identity**: `state_revision: 4`.
- **Decisions**: All decisions resolved (Oracle 23ai Free container `gvenzl/oracle-free:23-slim-faststart` on `FREEPDB1`; WIF keyless BigQuery CI gated by `vars.GCP_WIF_PROVIDER != ''`; integration jobs run once on `inputs.python-version == '3.12'`).
- **Recent discoveries**: All 3 tasks (`1.1`, `1.2`, `1.3`) completed and verified (`4f3b91d`, `a01672e`, `bc6fc94`).
- **Blockers**: `none`.
- **Next exact step**: Review and archive `oracle_ci_and_bigquery_test_harness_20261010` alongside Master PRD 1 (`prd_01_foundation_adc_and_ci_harness_20261010`).
- **Relevant knowledge**: `.agents/bundles/knowledge/standards/testing.md`, `.agents/bundles/knowledge/patterns/index.md`, `.agents/bundles/knowledge/workflow.md`.
