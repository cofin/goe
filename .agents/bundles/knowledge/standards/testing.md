---
type: Guide
title: Testing & Quality Assurance Standards
description: Unit testing guidelines, integration test harness, concurrency testing, and verification strategies
tags:
  - guide
  - standards
  - testing
  - pytest
  - quality
---

# Testing & Quality Assurance Standards

## Test Hierarchy

1. **Unit & Golden Characterization Tests (`tests/unit/`)**:
   - Fast, in-memory execution testing discrete components without requiring live database connections or cloud credentials.
   - Includes the offline Oracle-to-BigQuery golden dry-run (`dry_run=True, do_not_connect=True`) characterization suite in `tests/unit/characterization/test_offload_bigquery_golden.py` covering RBO DDL/staging/casts, IPA `RANGE` native and synthetic numeric `RANGE_BUCKET` partitioning + chunking, IPA `LIST`/`RANGE` subpartition discovery, PBO `GenericPredicate` Oracle/BigQuery `WHERE` rendering, and BigQuery `add_columns` schema evolution.
   - Run via:
     ```bash
     export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
     uv run pytest tests/unit
     # or via Makefile
     make test-unit
     ```
   - Covers canonical column metadata, predicate AST parsing, options validation, filesystem URI generation, configuration loading, and golden dry-run SQL/DDL artifacts.

2. **Integration Tests (`tests/integration/`)**:
   - Full end-to-end tests validating RDBMS extraction, Spark transport, BigQuery/Snowflake ingestion, and hybrid views against active test instances.
   - **Offline Collection**: `tests/integration/conftest.py` registers markers (`oracle`, `bigquery`, `gcs`, `spark`) and skips live suites at runtime when credentials (`ORA_CONN`, `BIGQUERY_DATASET_PROJECT`, `OFFLOAD_FS_CONTAINER`) are absent, ensuring `GOE_NO_AUTOLOAD_ENV=1 uv run pytest tests/integration --collect-only` always succeeds offline (`147 tests collected`).
   - **Oracle 23ai Free CI Bootstrap**: `sql/oracle/source/bootstrap_ci.sh` non-interactively provisions `GOE_ADM`, `GOE_APP`, `GOE_REPO`, `GOE_TEST`, and `SH_TEST` inside `gvenzl/oracle-free:23-slim-faststart` (`FREEPDB1`) for the `integration-oracle` GitHub Actions job (`make test-integration-oracle`).
   - **Keyless WIF BigQuery CI**: The `integration-bigquery` job in `.github/workflows/test.yaml` authenticates via `google-github-actions/auth@v3` Workload Identity Federation (`make test-integration-gcp`).
   - Run via:
     ```bash
     export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
     export GOE_TEST_USER_PASS="<db_pass>"
     export GOOGLE_CLOUD_PROJECT="<gcp_project>"
     uv run pytest tests/integration -n 4
     # or via Makefile
     make test-integration
     make test-integration-oracle
     make test-integration-gcp
     ```

## Verification Strategies in Flow

When implementing new features or bug fixes, choose the appropriate verification strategy:

| Strategy | When to Select | Required Evidence |
| :--- | :--- | :--- |
| `behavior_tdd` | New observable features | Failing focused unit test proving absence, followed by green test post-implementation. |
| `regression_tdd` | Bug/defect fixes | Focused reproduction unit test proving failure, followed by green test post-fix. |
| `characterization` | Behavior-preserving refactoring | Passing baseline unit tests before and after code changes. |
| `static_validation` | Configuration, DDL, templates | Lint, schema validation, and dry-run execution checks. |
| `integration_acceptance` | Cross-system workflows | End-to-end offload test with verification (`goe validate`). |
