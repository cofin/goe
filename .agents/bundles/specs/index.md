---
type: Reference
title: Specifications Registry
description: Active, planned, and completed feature specifications and task worksheets
tags:
  - reference
  - specs
  - index
---

# Specifications Registry

This directory contains specifications and task worksheets for active and planned work streams in Flow. Completed flows are contracted and archived into [Knowledge](../knowledge/index.md) and recorded in [Change Log](../log.md).

## Active & Planned Flows

### Phase 2 Next-Gen Modernization & Rebuild Roadmaps (Ordered by Implementation Dependency)

1. **[Master PRD 3: SQLSpec Oracle Data Layer, Pluggable SQL AST Engine, BigQuery-First Backend & DuckDB Offload Transport](prd_03_sqlspec_bigquery_and_duckdb_engine_20261010/spec.md)** (`prd_03_sqlspec_bigquery_and_duckdb_engine_20261010`, 17 tasks):
   - **Chapter 3.1**: [SQLSpec Oracle Data Layer & Named SQL Migration](sqlspec_oracle_data_layer_migration_20261010/spec.md) (`sqlspec_oracle_data_layer_migration_20261010`, 3 tasks)
   - **Chapter 3.2**: [Pluggable SQL Dialect Engine (`sql_engine.py`), Custom Oracle Dialect Adapter & `sqlglot` AST Builders](sqlglot_ast_and_predicate_engine_20261010/spec.md) (`sqlglot_ast_and_predicate_engine_20261010`, 5 tasks)
   - **Chapter 3.3**: [BigQuery-First Backend & GCS Transfer Modernization](bigquery_first_backend_modernization_20261010/spec.md) (`bigquery_first_backend_modernization_20261010`, 5 tasks)
   - **Chapter 3.4**: [DuckDB & `cofin/duckdb-oracle` + Community `gcs` Extension Offload Transport](duckdb_oracle_offload_transport_20261010/spec.md) (`duckdb_oracle_offload_transport_20261010`, 4 tasks)
2. **[Master PRD 4: End-to-End OpenTelemetry Observability, Step Spans, Metrics & Log Correlation](prd_04_end_to_end_opentelemetry_observability_20261010/spec.md)** (`prd_04_end_to_end_opentelemetry_observability_20261010`, 15 tasks):
   - **Chapter 4.1**: [OpenTelemetry Foundation, Config & `ExecutionId` Context Bridge](opentelemetry_foundation_and_context_propagation_20261010/spec.md) (`opentelemetry_foundation_and_context_propagation_20261010`, 6 tasks)
   - **Chapter 4.2**: [Orchestration Step Spans, Structured Log Correlation & Listener/Worker Telemetry](orchestration_step_and_listener_telemetry_20261010/spec.md) (`orchestration_step_and_listener_telemetry_20261010`, 4 tasks)
   - **Chapter 4.3**: [Database (`OracleGateway`), Offload Transport, GCS & BigQuery Spans](database_transport_and_cloud_storage_spans_20261010/spec.md) (`database_transport_and_cloud_storage_spans_20261010`, 5 tasks)

## Archived Flows & Roadmaps

All previous flows have completed full verification and code review gates and have been synthesized into `.agents/bundles/knowledge/`:

- **Master PRD 2: Typed `msgspec` Option Model, Core God-Module Decomposition & Strict Type Safety Ratchet (`prd_02_core_typing_options_and_decomposition_20261010`, 13 tasks, PR #9)**:
  - Chapter 2.1: Typed `msgspec` Option Model & Complete `optparse` Retirement (`typed_msgspec_option_model_20261010`, 3 tasks)
  - Chapter 2.2: Core God-Module Decomposition (`core_god_module_decomposition_20261010`, 4 tasks)
  - Chapter 2.3: Strict Mypy Type Safety Ratchet Across `src/goe/` (`strict_mypy_type_safety_ratchet_20261010`, 6 tasks)
  - *Synthesized into*: [Serialization & Utils](../knowledge/patterns/serialization-and-utils.md), [CLI Architecture](../knowledge/patterns/cli-architecture.md), [Orchestration Core](../knowledge/architecture/orchestration.md), [Python Standards](../knowledge/standards/python.md).
- **Master PRD 1: Foundation Hygiene, GCP ADC Auth Unification & CI Integration Harness (`prd_01_foundation_adc_and_ci_harness_20261010`, 15 tasks, PR #8)**:
  - Chapter 1.1: Legacy Shim Removal, Upstream Alignment & Repository Hygiene (`legacy_shim_removal_and_repo_hygiene_20261010`, 6 tasks)
  - Chapter 1.2: GCP Application Default Credentials (ADC) & Impersonation Unification (`gcp_adc_credential_unification_20261010`, 6 tasks)
  - Chapter 1.3: Oracle Free CI Harness, Opt-In BigQuery ADC Integration Suite & Golden Dry-Run Baseline (`oracle_ci_and_bigquery_test_harness_20261010`, 3 tasks)
  - *Synthesized into*: [Google Cloud Storage](../knowledge/storage/gcs.md), [Google BigQuery](../knowledge/backends/bigquery.md), [Dataproc & Spark Engines](../knowledge/transport/spark-dataproc.md), [Testing Standards](../knowledge/standards/testing.md).
- **GOE v2 Main Baseline Alignment & Functional Parity Remediation (`v2_main_alignment_remediation_20261004`)**:
  - Chapter 1: CLI Execution & Common Options Parity (`cli_execution_and_common_options_parity_20261004`)
  - Chapter 2: CLI Subcommand Option Completeness & Default Parity (`cli_subcommand_options_and_defaults_parity_20261004`)
  - Chapter 3: Listener REST & Persistence Schema Alignment (`listener_and_persistence_schema_alignment_20261004`)
  - *Synthesized into*: [CLI Architecture](../knowledge/patterns/cli-architecture.md), [Serialization & Utils](../knowledge/patterns/serialization-and-utils.md), [Listener REST API](../knowledge/listener/rest-api.md).
- **Modern Borderless CLI Styling & Zero-Type-Loss Import Performance (`cli_import_performance_20261008`)**:
  - *Synthesized into*: [CLI Architecture](../knowledge/patterns/cli-architecture.md).
- **Embedded Self-Contained Listener & Native Task Execution (`embedded_listener_and_task_execution_20260826`)**:
  - *Synthesized into*: [Listener Workers & Embedded Caching](../knowledge/listener/worker-and-redis.md), [Listener REST API](../knowledge/listener/rest-api.md).
- **Automatic offload.env Loading via python-dotenv (`python_dotenv_autoload_20260826`)**:
  - *Synthesized into*: [Configuration & Environment Variables](../knowledge/operations/configuration-and-env.md).
- **GOE Modernization Master Roadmap (`modernization_overhaul_20260823`)**:
  - Chapter 1: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul (`build_ci_overhaul_20260823`)
  - Chapter 2: Msgspec & SQLSpec Serialization Overhaul (`msgspec_sqlspec_overhaul_20260823`)
  - Chapter 3: Rich-Click CLI Suite (`rich_click_cli_overhaul_20260823`)
  - Chapter 4: Next-Generation Litestar Listener Service (`litestar_listener_overhaul_20260823`)
  - *Synthesized into*: [Patterns](../knowledge/patterns/index.md), [Workflow](../knowledge/workflow.md), [Listener](../knowledge/listener/index.md).
- **SPDX Copyright & License Header Migration (`spdx_copyright_migration_20260826`)**:
  - Chapters 1–4: Standardized all codebase copyright/license headers to 2-line SPDX headers with Ruff `CPY001` continuous lint enforcement.

