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
- Maintain compatibility with Python 3.8+ across all modules.
- Format all Python files with `black` and adhere to PEP 257 docstrings with PEP 585/604 typing.
- Always use `OrchestrationRunner` and `OrchestrationLockInterface` to ensure table-level mutex.
- Keep RDBMS queries snapshot-consistent using SCN / Flashback to prevent locks or phantom reads.

## Architecture Patterns
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
