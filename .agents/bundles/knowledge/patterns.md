---
type: Pattern
title: Project Patterns
description: Core architectural patterns, database offload conventions, common gotchas, and skill associations
tags:
  - pattern
  - conventions
  - gotchas
  - skills
---

# Project Patterns

<!-- truth: start -->
## Code Conventions
- Maintain compatibility with Python >= 3.12 across all modules.
- Format all Python files with `ruff` (`line-length = 120`), run `mypy`, and adhere to PEP 257 docstrings with PEP 585 built-in collections (`dict`, `list`) and PEP 604 union types (`str | None`).
- **Never** use in-line comments in Python functions; place explanations in PEP 257 docstrings.
- Run unit tests with `export GOOGLE_API_USE_CLIENT_CERTIFICATE=false`.
- Always use `OrchestrationRunner` and `OrchestrationLockInterface` to ensure table-level mutex.
- Keep RDBMS queries snapshot-consistent using SCN / Flashback to prevent locks or phantom reads.

## Architecture Patterns
- **Serialization & Utility Re-Exports**: Structure `src/goe/util/` to cleanly re-export `sqlspec.utils` modules:
  - `src/goe/util/serialization.py`: Re-exports `to_json`, `from_json`, `schema_dump`, and `DEFAULT_TYPE_ENCODERS` from `sqlspec.utils.serializers`. Direct delegation without redundant fallback catches.
  - `src/goe/util/sync_tools.py`: Re-exports `async_`, `await_`, `ensure_async_`, `run_`, `CapacityLimiter` from `sqlspec.utils.sync_tools` and `Portal`, `get_global_portal` from `sqlspec.utils.portal`.
  - `src/goe/util/text.py`: Re-exports `camelize`, `pascalize`, `snake_case`, `kebabize`, `slugify`, `quote_identifier`, `split_qualified_identifier` from `sqlspec.utils.text`.
  - `src/goe/util/env.py`: Re-exports `get_env`, `get_env_with_aliases`, `get_config_val`, `is_env_set` from `sqlspec.utils.env`.
  - `src/goe/util/uuids.py`: Re-exports `uuid4`, `uuid7`, `nanoid` from `sqlspec.utils.uuids`.
- **Pure `msgspec.Struct` Schemas**: Define metadata and telemetry schemas in `src/goe/persistence/schemas.py` directly as `msgspec.Struct` models without redundant client wrapper classes.
- Three-tier column mapping: Source RDBMS Column -> `CanonicalColumn` -> Target Backend Column.
- Two-phase data ingestion: Staged extraction to GCS/S3/ABFS -> Atomic `INSERT SELECT` / `COPY INTO`.
- Event streaming via Redis `goe:run:<execution_id>` for real-time telemetry and UI listeners.

## Gotchas & Defenses
- Ambiguous Oracle `NUMBER` / `FLOAT` must be sampled (`sample_rdbms_data_types`) before schema creation.
- Cloud storage eventual consistency: verify file visibility before executing backend load queries.
- High-precision numbers (`NUMBER(38)`) risk silent float truncation; map to `INTEGER_38` / `NUMERIC`.
<!-- truth: end -->

## Skill Associations

### Cross-Cutting Operational Skills

| Domain | Recommended Skill | When to Use |
| :--- | :--- | :--- |
| Database & SQL | `awr-reports` | Diagnosing Oracle database bottlenecks, wait events, and session locks |
| System Health | `server-healthcheck` | VM health checks, disk/memory limits, runaway background processes |
| Architecture | `flow:architecture-critic` | Reviewing new backend adapters, storage layers, and modular boundaries |
| Security | `flow:security-auditor` | Reviewing credential handling, Oracle Wallet integration, API auth |
| Performance | `flow:performance-analyst` | Profiling Spark JDBC extraction, query chunking, and network latency |
| Testing | `pytest-databases` | Integration testing with database containers and mock environments |
| Memory Keeper | `.agents/skills/flow-memory-keeper` | Elevating learnings, failure patterns, and maintaining bundle state |
