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

*No active or planned flows in progress.*

## Archived Flows & Roadmaps

All previous flows have completed full verification and code review gates and have been synthesized into `.agents/bundles/knowledge/`:

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

