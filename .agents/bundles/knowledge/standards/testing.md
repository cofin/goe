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

1. **Unit Tests (`tests/unit/`)**:
   - Fast, in-memory execution testing discrete components without requiring live database connections or cloud credentials.
   - Run via:
     ```bash
     export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
     uv run pytest tests/unit
     # or via Makefile
     make test-unit
     ```
   - Covers canonical column metadata, predicate AST parsing, options validation, filesystem URI generation, and configuration loading.

2. **Integration Tests (`tests/integration/`)**:
   - Full end-to-end tests validating RDBMS extraction, Spark transport, BigQuery/Snowflake ingestion, and hybrid views against active test instances.
   - Run via:
     ```bash
     export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
     export GOE_TEST_USER_PASS="<db_pass>"
     export GOOGLE_CLOUD_PROJECT="<gcp_project>"
     uv run pytest tests/integration -n 4
     # or via Makefile
     make test-integration
     ```

## Verification Strategies in Flow

When implementing new features or bug fixes, choose the appropriate verification strategy:

| Strategy | When to Select | Required Evidence |
| :--- | :--- | :--- |
| `behavior_tdd` | New observable features | Failing focused unit test proving absence, followed by green test post-implementation. |
| `regression_tdd` | Bug/defect fixes | Focused reproduction unit test proving failure, followed by green test post-fix. |
| `characterization` | Behavior-preserving refactoring | Passing baseline unit tests before and after code changes. |
| `static_validation` | Configuration, DDL, templates | Lint, schema validation, and dry-run execution checks. |
| `integration_acceptance` | Cross-system workflows | End-to-end offload test with verification (`bin/agg_validate`). |
