---
title: Project Patterns & Conventions
description: Architectural patterns, utility conventions, CLI standards, offload invariants, and skill routing
---

# Project Patterns & Conventions

<!-- truth: start -->
- Maintain Python >= 3.12 compatibility, format with `ruff` (`line-length = 120`), type-check with `mypy`, use PEP 585 built-in collections (`dict`, `list`) and PEP 604 unions (`str | None`), and place explanations in PEP 257 docstrings rather than inline comments.
- Start all source files with the standard 2-line SPDX header (`# SPDX-FileCopyrightText: <year> The GOE Authors` and `# SPDX-License-Identifier: Apache-2.0`), enforced via Ruff `CPY001`.
- Export `GOOGLE_API_USE_CLIENT_CERTIFICATE=false` prior to running unit or integration test suites.
- Acquire table-level execution mutexes via `OrchestrationRunner` and `OrchestrationLockInterface`, and keep RDBMS extraction snapshot-consistent using SCN / Flashback.
- Resolve environment configuration via `GOESettings.from_env()` and `load_env()` (`src/goe/config/settings.py`) across explicit path, `$OFFLOAD_HOME/conf/offload.env`, upward `dotenv.find_dotenv()`, and `/opt/goe/offload/conf/offload.env` / `/u01/app/goe/offload/conf/offload.env` with `interpolate=True, override=False`, skipping auto-load when `PYTEST_CURRENT_TEST` or `GOE_NO_AUTOLOAD_ENV` is set.
<!-- truth: end -->

## Pattern Chapters

- [Serialization & Utility Patterns](serialization-and-utils.md) — Centralized `goe.serializers` helpers, `FrozenBaseStruct` value objects, and platform cgroup/locking utilities.
- [Centralized Rich-Click CLI](cli-architecture.md) — Unified `goe` entrypoint (`src/goe/cli/`), `_lazy.py` lazy binding, and option group architecture.
- [Data Offload, Canonical Typing & Storage Patterns](offload-and-typing.md) — Canonical `ColumnSpec`, `TYPE_REGISTRY`, staged ingestion, and cloud storage atomicity.
- [Project-Local Domain Skills](../../../skills/index.md) — Stack-specific implementation and review skills across `core-orchestration`, `sqlspec-and-sql-ast`, `offload-backends-and-dataplane`, and `listener-and-observability`.
