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
- [SPDX Copyright & License Header Migration (`spdx_copyright_migration_20260826`)](spdx_copyright_migration_20260826/spec.md) - [State: Planned] Master roadmap migrating repository copyright/license headers to concise SPDX format with Ruff CPY001 automated enforcement.

## Active & Planned Child Flows

- [Chapter 1: Ruff CPY001 Configuration & Automated Migration Tooling (`spdx_pyproject_ruff_config_20260826`)](spdx_pyproject_ruff_config_20260826/spec.md) - [State: Planned] Configure Ruff flake8-copyright CPY001 rule in pyproject.toml and implement automated migration tooling with unit tests.
- [Chapter 2: Python Source Files SPDX Header Migration & Ruff Enforcement (`spdx_python_files_migration_20260826`)](spdx_python_files_migration_20260826/spec.md) - [State: Planned] Migrate all Python files in src/, tests/, tools/, and repo root with zero CPY001 violations.
- [Chapter 3: Non-Python Repository Files SPDX Header Migration (`spdx_non_python_files_migration_20260826`)](spdx_non_python_files_migration_20260826/spec.md) - [State: Planned] Migrate SQL, Shell, Makefiles, templates, HTML, CSS, JS, and Scala files.
- [Chapter 4: CI Enforcement, Pre-commit Integration & Developer Documentation (`spdx_ci_precommit_verification_20260826`)](spdx_ci_precommit_verification_20260826/spec.md) - [State: Planned] Integrate Ruff CPY into pre-commit and CI workflows, update developer guidelines.

## Completed & Archived Flows

- **Chapter 1 (`build_ci_overhaul_20260823`)**: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul. Synthesized into [Patterns](../knowledge/patterns.md) and [Workflow](../knowledge/workflow.md); recorded in [Change Log](../log.md).
- **Chapter 2 (`msgspec_sqlspec_overhaul_20260823`)**: High-Performance Msgspec Serialization & SQLSpec Data Layer. Synthesized into [Patterns](../knowledge/patterns.md); recorded in [Change Log](../log.md).
- **Chapter 3 (`rich_click_cli_overhaul_20260823`)**: Unified Rich-Click CLI Suite & Interactive Terminal UX. Synthesized into [Patterns](../knowledge/patterns.md); recorded in [Change Log](../log.md).
- **Chapter 4 (`litestar_listener_overhaul_20260823`)**: Next-Generation Litestar Listener Service, Granian ASGI, litestar-queues, and MCP Tools.
