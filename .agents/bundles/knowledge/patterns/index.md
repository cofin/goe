---
type: Guide
title: Project Patterns & Conventions
description: Architectural patterns, utility conventions, CLI standards, offload invariants, and skill routing
tags:
  - guide
  - patterns
  - conventions
  - index
---

# Project Patterns & Conventions

<!-- truth: start -->
- Maintain Python >= 3.12 compatibility, format with `ruff` (`line-length = 120`), type-check with `mypy`, use PEP 585 built-in collections (`dict`, `list`) and PEP 604 unions (`str | None`), and place explanations in PEP 257 docstrings rather than inline comments.
- Start all source files with the standard 2-line SPDX header (`# SPDX-FileCopyrightText: <year> The GOE Authors` and `# SPDX-License-Identifier: Apache-2.0`), enforced via Ruff `CPY001`.
- Export `GOOGLE_API_USE_CLIENT_CERTIFICATE=false` prior to running unit or integration test suites.
- Acquire table-level execution mutexes via `OrchestrationRunner` and `OrchestrationLockInterface`, and keep RDBMS extraction snapshot-consistent using SCN / Flashback.
<!-- truth: end -->

## Pattern Chapters

- [Serialization & Utility Re-Export Patterns](serialization-and-utils.md) - `sqlspec.utils` re-export conventions in `src/goe/util/` and typed `msgspec.Struct` persistence/DTO schemas.
- [Centralized Rich-Click CLI & Legacy Delegators](cli-architecture.md) - Unified `goe` entrypoint (`src/goe/cli/`), Google Cloud color palette, subcommand option groups, and `bin/` deprecation delegators.
- [Data Offload, Canonical Typing & Storage Gotchas](offload-and-typing.md) - Three-tier column mapping, two-phase staged ingestion, RDBMS precision sampling, and cloud storage eventual consistency defenses.

## Cross-Cutting Operational Skills

| Domain | Recommended Skill | When to Use |
| :--- | :--- | :--- |
| Database & SQL | `awr-reports` | Diagnosing Oracle database bottlenecks, wait events, and session locks |
| System Health | `server-healthcheck` | VM health checks, disk/memory limits, runaway background processes |
| Architecture | `architecture-critic` | Reviewing new backend adapters, storage layers, and modular boundaries |
| Security | `security-auditor` | Reviewing credential handling, Oracle Wallet integration, API auth |
| Performance | `performance-analyst` | Profiling Spark JDBC extraction, query chunking, and network latency |
| Testing | `pytest-databases` | Integration testing with database containers and mock environments |
| Memory Keeper | `.agents/skills/flow-memory-keeper` | Elevating learnings, failure patterns, and maintaining bundle state |
