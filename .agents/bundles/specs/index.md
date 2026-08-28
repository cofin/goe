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

This directory contains specifications and task worksheets for active, planned, and completed work streams in Flow.

## Master Roadmaps (PRDs)

- [GOE Modernization Master Roadmap (`modernization_overhaul_20260823`)](modernization_overhaul_20260823/spec.md) - [State: Planned] Master architectural roadmap overhauling packaging/CI, serialization with msgspec & sqlspec, unified rich-click CLI, and Litestar listener ecosystem.

## Active & Planned Child Flows

- [Embedded Self-Contained Listener & Native Task Execution (`embedded_listener_and_task_execution_20260826`)](embedded_listener_and_task_execution_20260826/spec.md) - [State: Planned] Rebuild the GOE Listener with an embedded architecture (in-memory TTL cache, accelerator-pattern WorkerPlugin & Task runner, deprecation shims for Redis and bin wrappers, zero external daemon dependencies).
- [Automatic offload.env Loading via python-dotenv (`python_dotenv_autoload_20260826`)](python_dotenv_autoload_20260826/spec.md) - [State: Planned] Multi-stage configuration discovery, POSIX variable expansion, and automatic environment loading across CLI and Python entrypoints via python-dotenv.

## Completed & Archived Flows

- **SPDX Migration (`spdx_copyright_migration_20260826`)**: Standardized all codebase copyright/license headers to 2-line SPDX headers (`SPDX-FileCopyrightText` / `SPDX-License-Identifier: Apache-2.0`) with Ruff `CPY001` continuous lint enforcement.
  - Chapter 1 (`spdx_pyproject_ruff_config_20260826`): Ruff CPY001 configuration in `pyproject.toml`.
  - Chapter 2 (`spdx_python_files_migration_20260826`): Core Python source, tests, tools, and root scripts migration.
  - Chapter 3 (`spdx_non_python_files_migration_20260826`): SQL, Shell, Makefiles, templates, HTML, CSS, JS, and Scala migration.
  - Chapter 4 (`spdx_ci_precommit_verification_20260826`): CI workflows and developer documentation updates.
- **Chapter 1 (`build_ci_overhaul_20260823`)**: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul. Synthesized into [Patterns](../knowledge/patterns.md) and [Workflow](../knowledge/workflow.md); recorded in [Change Log](../log.md).
- **Chapter 2 (`msgspec_sqlspec_overhaul_20260823`)**: High-Performance Msgspec Serialization & SQLSpec Data Layer. Synthesized into [Patterns](../knowledge/patterns.md); recorded in [Change Log](../log.md).
- **Chapter 3 (`rich_click_cli_overhaul_20260823`)**: Unified Rich-Click CLI Suite & Interactive Terminal UX. Synthesized into [Patterns](../knowledge/patterns.md); recorded in [Change Log](../log.md).
- **Chapter 4 (`litestar_listener_overhaul_20260823`)**: Next-Generation Litestar Listener Service, Granian ASGI, litestar-queues, and MCP Tools.

