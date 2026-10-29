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

The GOE architecture redesign is planned as six sequenced Master PRDs (research: [redesign dossier](prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/goe-architecture-redesign.md)):

- **[Master PRD 8: DuckDB 2.0 Data Plane, QUERY_IMPORT Parity Replacement, Transport Decomposition, and SQLSpec Storage](prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/spec.md)** (`planned`):
  - Chapter 8.1: DuckDB 2.0 Engine Hardening ([`duckdb2_engine_hardening_20261024`](duckdb2_engine_hardening_20261024/spec.md))
  - Chapter 8.2: Arrow Extraction and `QUERY_IMPORT` Parity ([`arrow_extraction_and_query_import_parity_20261024`](arrow_extraction_and_query_import_parity_20261024/spec.md))
  - Chapter 8.3: Transport Decomposition and Automatic Selection ([`transport_decomposition_and_auto_selection_20261024`](transport_decomposition_and_auto_selection_20261024/spec.md))
  - Chapter 8.4: `sqlspec.storage` Filesystem Backends ([`sqlspec_storage_filesystem_backends_20261024`](sqlspec_storage_filesystem_backends_20261024/spec.md))
- **[Master PRD 9: Canonical Column Model, Composable Backends, Cached Backend Catalog, and Direct BigQuery Ingestion](prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/spec.md)** (`planned`):
  - Chapter 9.1: Canonical Column Model and Type Registry ([`canonical_column_model_and_type_registry_20261024`](canonical_column_model_and_type_registry_20261024/spec.md))
  - Chapter 9.2: Backend Capabilities and Cached Catalog ([`backend_capabilities_and_cached_catalog_20261024`](backend_capabilities_and_cached_catalog_20261024/spec.md))
  - Chapter 9.3: BigQuery Ingest Strategies ([`bigquery_ingest_strategies_20261024`](bigquery_ingest_strategies_20261024/spec.md))
  - Chapter 9.4: Snowflake, Synapse, and Hadoop Backend Alignment ([`snowflake_synapse_hadoop_backend_alignment_20261024`](snowflake_synapse_hadoop_backend_alignment_20261024/spec.md))
- **[Master PRD 10: Execution Context, Staged OffloadPlan, Durable Job Queue, and the Listener on Vertebra](prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/spec.md)** (`planned`):
  - Chapter 10.1: Execution Context and Concurrency Safety ([`execution_context_and_concurrency_safety_20261024`](execution_context_and_concurrency_safety_20261024/spec.md))
  - Chapter 10.2: `OffloadPlan` Discovery and Boundary Stages ([`offload_plan_discovery_and_boundary_stages_20261024`](offload_plan_discovery_and_boundary_stages_20261024/spec.md))
  - Chapter 10.3: `OffloadPlan` Resolution and Stateless Executor ([`offload_plan_resolution_and_stateless_executor_20261024`](offload_plan_resolution_and_stateless_executor_20261024/spec.md))
  - Chapter 10.4: Durable Job Queue, Listener Cache, and MCP ([`durable_job_queue_listener_cache_and_mcp_20261024`](durable_job_queue_listener_cache_and_mcp_20261024/spec.md))
  - Chapter 10.5: Listener on Vertebra Runtime ([`listener_on_vertebra_runtime_20261024`](listener_on_vertebra_runtime_20261024/spec.md))

## Archived Flows & Roadmaps

All previous flows have completed full verification and code review gates and have been synthesized into `.agents/bundles/knowledge/`:

- **Master PRD 7: Native SQLGlot Dialect Engine, PredicateIR, Concurrent Validation, Schema Sync, and Status Report (`prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024`, 13 tasks)**:
  - Chapter 7.1: Native SQLGlot Dialect Engine (`native_sqlglot_dialect_engine_20261024`, 4 tasks)
  - Chapter 7.2: `PredicateIR` Compiler (`predicate_ir_compiler_20261024`, 3 tasks)
  - Chapter 7.3: Concurrent Cross-Database Validation (`concurrent_cross_db_validation_20261024`, 3 tasks)
  - Chapter 7.4: Schema Sync and Status Report Redesign (`schema_sync_and_status_report_redesign_20261024`, 3 tasks)
  - *Synthesized into*: [Database & SQL Standards](../knowledge/standards/database-and-sql.md), [Schema Evolution](../knowledge/architecture/schema-evolution.md), [CLI Tools](../knowledge/operations/cli-tools.md), [Offload & Typing Gotchas](../knowledge/patterns/offload-and-typing.md).

- **Master PRD 6: Pooled SQLSpec Oracle Data Layer, Repository Service, Catalog Cache, and MSSQL Frontend (`prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024`, 13 tasks)**:
  - Chapter 6.1: `OracleDatabaseRegistry` and Session Tracing (`oracle_database_registry_and_session_tracing_20261024`, 4 tasks)
  - Chapter 6.2: `OffloadMetadata` and Repository Service (`offload_metadata_and_repository_service_20261024`, 3 tasks)
  - Chapter 6.3: Oracle Catalog Snapshot and Frontend Cache (`oracle_catalog_snapshot_and_frontend_cache_20261024`, 4 tasks)
  - Chapter 6.4: MSSQL Frontend on `MssqlPythonConfig` (`mssql_frontend_on_mssql_python_20261024`, 2 tasks)
  - *Synthesized into*: [Oracle Adapter](../knowledge/frontends/oracle.md), [SQL Server Adapter](../knowledge/frontends/sqlserver.md), [Database & SQL Standards](../knowledge/standards/database-and-sql.md), [Tech Stack](../product/tech-stack.md).

- **Master PRD 5: Adapter Reduction, Core Typing, Declarative Settings, Utility Dissolution, and Connect Runner (`prd_05_foundation_typing_settings_and_adapter_reduction_20261024`, 21 tasks, PR #11)**:
  - Chapter 5.1: Adapter Reduction and `AdapterRegistry` (`adapter_reduction_and_adapter_registry_20261024`, 7 tasks)
  - Chapter 5.2: Core Typing, Serializers, Platform Utilities, and Architecture Gate (`core_typing_serializers_platform_and_architecture_gate_20261024`, 4 tasks)
  - Chapter 5.3: Declarative Settings, Option Registry, and Error Model (`declarative_settings_options_and_error_model_20261024`, 4 tasks)
  - Chapter 5.4: Utility Dissolution, Dependency Slimming, and Lint Hygiene (`util_dissolution_dependency_and_lint_hygiene_20261024`, 3 tasks)
  - Chapter 5.5: Connect Runner and Connectivity Report (`connect_runner_and_connectivity_report_20261024`, 3 tasks)
  - *Synthesized into*: [Serialization & Utils](../knowledge/patterns/serialization-and-utils.md), [CLI Architecture](../knowledge/patterns/cli-architecture.md), [Orchestration Core](../knowledge/architecture/orchestration.md), [CLI Tools](../knowledge/operations/cli-tools.md), [Configuration & Environment Variables](../knowledge/operations/configuration-and-env.md), [Python Standards](../knowledge/standards/python.md), [Development Workflow](../knowledge/workflow.md).

- **Master PRD 4: End-to-End OpenTelemetry Observability, Step Spans, Metrics & Log Correlation (`prd_04_end_to_end_opentelemetry_observability_20261010`, 15 tasks)**:
  - Chapter 4.1: OpenTelemetry Foundation, Config & `ExecutionId` Context Bridge (`opentelemetry_foundation_and_context_propagation_20261010`, 6 tasks)
  - Chapter 4.2: Orchestration Step Spans, Structured Log Correlation & Listener/Worker Telemetry (`orchestration_step_and_listener_telemetry_20261010`, 4 tasks)
  - Chapter 4.3: Database (`OracleGateway`), Offload Transport, GCS & BigQuery Spans (`database_transport_and_cloud_storage_spans_20261010`, 5 tasks)
  - *Synthesized into*: [OpenTelemetry Observability](../knowledge/operations/observability.md), [Oracle Adapter](../knowledge/frontends/oracle.md), [Google BigQuery](../knowledge/backends/bigquery.md), [Google Cloud Storage](../knowledge/storage/gcs.md), [Dataproc & Spark Engines](../knowledge/transport/spark-dataproc.md), [DuckDB Offload Transport](../knowledge/transport/duckdb.md), [Listener REST API](../knowledge/listener/rest-api.md), [Orchestration Core](../knowledge/architecture/orchestration.md).
- **Master PRD 3: SQLSpec Oracle Data Layer, Pluggable SQL AST Engine, BigQuery-First Backend & DuckDB Offload Transport (`prd_03_sqlspec_bigquery_and_duckdb_engine_20261010`, 17 tasks)**:
  - Chapter 3.1: SQLSpec Oracle Data Layer & Named SQL Migration (`sqlspec_oracle_data_layer_migration_20261010`, 3 tasks)
  - Chapter 3.2: Pluggable SQL Dialect Engine (`sql_engine.py`), Custom Oracle Dialect Adapter & `sqlglot` AST Builders (`sqlglot_ast_and_predicate_engine_20261010`, 5 tasks)
  - Chapter 3.3: BigQuery-First Backend & GCS Transfer Modernization (`bigquery_first_backend_modernization_20261010`, 5 tasks)
  - Chapter 3.4: DuckDB & `cofin/duckdb-oracle` + Community `gcs` Extension Offload Transport (`duckdb_oracle_offload_transport_20261010`, 4 tasks)
  - *Synthesized into*: [Oracle Adapter](../knowledge/frontends/oracle.md), [Database & SQL Standards](../knowledge/standards/database-and-sql.md), [Google BigQuery](../knowledge/backends/bigquery.md), [Google Cloud Storage](../knowledge/storage/gcs.md), [DuckDB Offload Transport](../knowledge/transport/duckdb.md), [Dataproc & Spark Engines](../knowledge/transport/spark-dataproc.md).
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
