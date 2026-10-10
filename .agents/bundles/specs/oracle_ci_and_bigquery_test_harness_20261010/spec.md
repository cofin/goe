---
type: Spec
flow_id: oracle_ci_and_bigquery_test_harness_20261010
title: "Chapter 1.3: Oracle 23ai Free CI Container, BigQuery Integration Harness, and Golden Dry-Run Characterization Suite"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-10T16:00:00Z
description: "Fix integration test collection and stale helper signatures, provision a non-interactive Oracle 23ai Free CI container and WIF-authenticated BigQuery workflow, and establish a deterministic golden dry-run (execute=False) characterization test suite."
tags: [testing, ci, oracle, bigquery]
parent_prd: prd_01_foundation_adc_and_ci_harness_20261010
research: []
---

# Chapter 1.3: Oracle 23ai Free CI Container, BigQuery Integration Harness, and Golden Dry-Run Characterization Suite

## Specification

### Code Analysis Summary
- **Integration Test Collection Crash & Stale Test Helper Bugs**:
  - `tests/integration/persistence/test_orchestration_metadata.py:139-146`: `TestOrchestrationMetadata.__init__` executes `self.config = build_current_options()`, `self.messages = get_default_test_messages(self.config, ...)`, and `self.db = get_testing_frontend_api(self.config, ...)` during `unittest.TestCase` instantiation at pytest collection time. When `offload.env` is absent, `build_current_options()` raises `AssertionError: Required configuration missing: OFFLOAD_HOME`, aborting `pytest tests/integration --collect-only`.
  - `tests/integration/offload/test_offload_source_table.py:121,128`: Compares `if self.config == DBTYPE_ORACLE:` instead of `if self.config.db_type == DBTYPE_ORACLE:`.
  - `tests/testlib/test_framework/test_functions.py:111-116`: `log()` calls `messages.log(line, detail=detail, ansi_code=ansi_code, redis_publish=False)`, passing the removed `redis_publish` keyword argument (`OffloadMessages.log` in `src/goe/offload/offload_messages.py:296` only accepts `self, line, detail=NORMAL, ansi_code=None, **_`).
  - `tests/testlib/test_framework/test_functions.py:120-124`: `text_in_log(search_text, search_from_text="")` calls `get_line_from_log(search_text, search_from_text=search_from_text)` without passing the required first parameter `messages: OffloadMessages` expected by `get_line_from_log(messages: OffloadMessages, search_text: str, search_from_text: str = "")` at lines `89-93`.
  - `tests/integration/` has no `conftest.py` to register markers (`oracle`, `bigquery`, `gcs`, `spark`) or gracefully skip live database/cloud suites when credentials are not configured.
- **Interactive Oracle SQL Bootstrap & Unit-Only CI**:
  - `sql/oracle/source/install_offload.sql` uses SQL*Plus `ACCEPT` prompts and requires manual substitution of `VERSION`/`BUILD` in `sql/oracle/source/install_env.sql` and `sql/oracle/source/upgrade_env.sql` and `'%s-SNAPSHOT'` in `sql/oracle/source/create_offload_package_spec.sql` and `sql/oracle/source/create_offload_repo_package_spec.sql`, plus expired passwords (`PASSWORD EXPIRE`) on `GOE_ADM`, `GOE_APP`, and `GOE_REPO`.
  - `.github/workflows/test.yaml:1-72` only runs unit tests (`pytest tests/unit`) and never exercises `sql/oracle/source/` PL/SQL installation or `tests/integration/persistence/` and `tests/integration/offload/`.
- **Missing Deterministic Dry-Run (`execute=False`) Characterization Suite**:
  - While subsequent PRDs refactor `OrchestrationConfig`, backend adapters, and `src/goe/goe.py`, there is no fast, offline golden characterization suite asserting the exact sequence of generated Oracle extraction queries, BigQuery DDL (`CREATE TABLE`, `PARTITION BY`, `CLUSTER BY`, `OPTIONS`), GCS load steps, predicate pushdown SQL, and metadata repository writes in dry-run (`execute=False`) mode.

### Relevant Patterns & Conventions
- [Testing & Faker Architecture](../../knowledge/patterns/testing-and-fakers.md): `TestBackedOffloadSourceTable`, `FakeBackendTestingApi`, and `FakeOrchestrationRepoClient` enable deterministic dry-run (`execute=False`) orchestration testing without live Oracle or BigQuery connections.

### Requirements
- **REQ-1**: Fix `TestOrchestrationMetadata` (`tests/integration/persistence/test_orchestration_metadata.py:139-146`) by moving `self.config`, `self.messages`, and `self.db` initialization into `setUp()`, fix `self.config.db_type == DBTYPE_ORACLE` in `tests/integration/offload/test_offload_source_table.py:121,128`, fix `log()` and `text_in_log()` in `tests/testlib/test_framework/test_functions.py:111-125`, register `pytest-databases[oracle]>=0.14.0` and pytest markers (`oracle`, `bigquery`, `gcs`, `spark`) in `pyproject.toml`, and create `tests/integration/conftest.py` so `GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only` succeeds offline.
- **REQ-2**: Create a non-interactive idempotent bootstrap script `sql/oracle/source/bootstrap_ci.sh` that installs the `OFFLOAD` and `OFFLOAD_REPO` schemas/packages and `GOE_TEST`/`SH_TEST` test schemas into `gvenzl/oracle-free:23-slim-faststart` (`FREEPDB1`), and update `.github/workflows/test.yaml` and `Makefile` with an `integration-oracle` CI job and an opt-in keyless WIF `integration-bigquery` CI job.
- **REQ-3**: Create `tests/unit/characterization/test_offload_bigquery_golden.py` capturing and verifying deterministic dry-run (`execute=False`) artifacts (Oracle extraction queries, BigQuery `CREATE TABLE` / `PARTITION BY` / `CLUSTER BY` / `OPTIONS` DDL, staging load steps, predicate pushdown SQL, and metadata writes) across RBO (`100/0`), IPA `RANGE`, IPA `LIST`, PBO (`90/10`), and schema evolution (column addition) scenarios.

### Requirement Traceability Matrix

| Requirement | Task ID | Verification Strategy | Verification Target |
| :--- | :--- | :--- | :--- |
| REQ-1 | `1.1` | `regression_tdd` | `GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only` |
| REQ-2 | `1.2` | `integration_acceptance` | `bash -n sql/oracle/source/bootstrap_ci.sh && uv run ruff check` |
| REQ-3 | `1.3` | `characterization` | `uv run pytest tests/unit/characterization/test_offload_bigquery_golden.py` |

---

## Implementation Plan

- [ ] 1.1 Fix integration test collection crash, repair stale test helper signatures, and add `tests/integration/conftest.py` (`tasks/1.1.md`) [P0, regression_tdd]
- [ ] 1.2 Create `sql/oracle/source/bootstrap_ci.sh` and configure Oracle 23ai Free + WIF BigQuery CI jobs (`tasks/1.2.md`) (depends on: 1.1) [P1, integration_acceptance]
- [ ] 1.3 Create golden dry-run (`execute=False`) characterization test suite for Oracle-to-BigQuery offloads (`tasks/1.3.md`) (depends on: 1.1) [P0, characterization]

---

## Continuity Snapshot

- **Current State**: Planned (`state: planned`, `plan_revision: 1`). Tasks `1.1`–`1.3` are authored with exact `file:line` references and verification commands.
- **Next Action**: Claim and execute Task `1.1` (`tasks/1.1.md`) once Chapter 1.2 completes.
