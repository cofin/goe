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

- [GOE v2 Main Baseline Alignment & Functional Parity Remediation (`v2_main_alignment_remediation_20261004`)](v2_main_alignment_remediation_20261004/spec.md) - [State: Completed] Master roadmap remediating CLI runtime regressions (`goe sync`, `goe validate`), global/common CLI option propagation across subcommands and `bin/*` wrappers, `bin/listener` default startup, subcommand option/default parity (`offload`, `connect`, `report`, `logmgr`), and Listener/Persistence schema alignment (`OffloadOptions`, `ListenerConfig`, `ColumnDetail`, `SubPartitionDetail`, `serialization.py`).
- [GOE Modernization Master Roadmap (`modernization_overhaul_20260823`)](modernization_overhaul_20260823/spec.md) - [State: Completed] Master architectural roadmap overhauling packaging/CI, serialization with msgspec & sqlspec, unified rich-click CLI, automatic `offload.env` discovery, and embedded Litestar listener ecosystem.

## Completed & Archived Flows

- [Modern Borderless CLI Styling & Zero-Type-Loss Import Performance (`cli_import_performance_20261008`)](cli_import_performance_20261008/spec.md) - [State: Completed] Borderless modern `rich-click` CLI styling, zero-type-loss PEP 562 lazy binding (`src/goe/cli/_lazy.py`), and transitive import decoupling in `goe.listener.utils` and `goe.util.goe_log_fh`.
- [Chapter 1: CLI Execution & Common Options Parity (`cli_execution_and_common_options_parity_20261004`)](cli_execution_and_common_options_parity_20261004/spec.md) - [State: Completed] Shared `@common_options` decorator (`src/goe/cli/common.py`), `bin/listener` default `start` invocation, `goe sync` delegation to `run_schema_sync`, and `goe validate` `post_process_args` & exit code handling.
- [Chapter 2: CLI Subcommand Option Completeness & Default Parity (`cli_subcommand_options_and_defaults_parity_20261004`)](cli_subcommand_options_and_defaults_parity_20261004/spec.md) - [State: Completed] Restore 12 missing `goe offload` options, string type for `--older-than-days`, `--create-backend-db` on `connect`, `"text"` / `"summary"` defaults & `--demo` on `report`, and `LOG_MV_MINS` fallback on `logmgr`.
- [Chapter 3: Listener REST & Persistence Schema Alignment (`listener_and_persistence_schema_alignment_20261004`)](listener_and_persistence_schema_alignment_20261004/spec.md) - [State: Completed] Align `OffloadOptions` with `EXPECTED_OFFLOAD_ARGS` (`to_params_dict()`), `ListenerConfig` optional fields, `ColumnDetail` `data_precision`, `SubPartitionDetail` `partition_name`/`partition_position`, `SystemController.get_table_partitions` struct normalization, and `serialization.py` fallback hook.
- [Embedded Self-Contained Listener & First-Party Litestar Execution (`embedded_listener_and_task_execution_20260826`)](embedded_listener_and_task_execution_20260826/spec.md) - [State: Completed] Embedded in-memory TTL cache (`MemoryCache` / `MemorySyncCache`), `litestar-queues` in-memory worker & cron jobs, `litestar-security` console-key auth, `LitestarMCP` tools, Litestar 2.24 native DI annotations, deprecation shims, and full CLI option parity.
- [Automatic offload.env Loading via python-dotenv (`python_dotenv_autoload_20260826`)](python_dotenv_autoload_20260826/spec.md) - [State: Completed] Multi-stage configuration discovery, POSIX variable expansion, and automatic environment loading across CLI and Python entrypoints via `python-dotenv`.
- **SPDX Migration (`spdx_copyright_migration_20260826`)**: Standardized all codebase copyright/license headers to 2-line SPDX headers (`SPDX-FileCopyrightText` / `SPDX-License-Identifier: Apache-2.0`) with Ruff `CPY001` continuous lint enforcement.
  - Chapter 1 (`spdx_pyproject_ruff_config_20260826`): Ruff CPY001 configuration in `pyproject.toml`.
  - Chapter 2 (`spdx_python_files_migration_20260826`): Core Python source, tests, tools, and root scripts migration.
  - Chapter 3 (`spdx_non_python_files_migration_20260826`): SQL, Shell, Makefiles, templates, HTML, CSS, JS, and Scala migration.
  - Chapter 4 (`spdx_ci_precommit_verification_20260826`): CI workflows and developer documentation updates.
- **Chapter 1 (`build_ci_overhaul_20260823`)**: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul. Synthesized into [Patterns](../knowledge/patterns/index.md) and [Workflow](../knowledge/workflow.md); recorded in [Change Log](../log.md).
- **Chapter 2 (`msgspec_sqlspec_overhaul_20260823`)**: High-Performance Msgspec Serialization & SQLSpec Data Layer. Synthesized into [Serialization & Utility Re-Export Patterns](../knowledge/patterns/serialization-and-utils.md); recorded in [Change Log](../log.md).
- **Chapter 3 (`rich_click_cli_overhaul_20260823`)**: Unified Rich-Click CLI Suite & Interactive Terminal UX. Synthesized into [Centralized Rich-Click CLI & Legacy Delegators](../knowledge/patterns/cli-architecture.md); recorded in [Change Log](../log.md).
- [Chapter 4 (`litestar_listener_overhaul_20260823`)](litestar_listener_overhaul_20260823/spec.md) - [State: Completed] Next-Generation Litestar Listener Service, Granian ASGI, `litestar-queues`, `litestar-security`, and MCP Tools.

