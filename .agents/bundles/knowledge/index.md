---
title: "GOE Knowledge Base"
description: "Canonical architectural documentation, domain glossary, ADRs, implementation patterns, and operational standards for the Gluent Offload Engine."
---

# GOE Knowledge Base

This knowledge base captures the verified architecture, adapter contracts, and engineering standards of the Gluent Offload Engine (GOE).

## Core Workflow

- [Developer Workflow & Commands](workflow.md) — Verified build, test, lint, and architecture verification commands plus Flow task continuity rules.

## Knowledge Domains

- [Domain Glossary](domains/index.md) — Ubiquitous terminology across offload planning, boundary partitioning, staging, and durable Listener jobs.
- [Architecture & Core Engine](architecture/index.md) — Staged offload pipeline, execution context, canonical type registry, and schema evolution.
- [Architectural Decision Records](decisions/index.md) — Durable records of foundational technology and boundary choices.
- [Frontend RDBMS Adapters](frontends/index.md) — Oracle and Microsoft SQL Server metadata extraction, pooling, and type mapping.
- [Backend Analytical Targets](backends/index.md) — Google BigQuery, Snowflake, Azure Synapse, and Hadoop (Hive/Impala) target adapters.
- [Data Transport Engines](transport/index.md) — DuckDB 2.0 streaming transport, Arrow Parquet query import, and Spark/Dataproc transports.
- [Staging Storage Layer](storage/index.md) — Unified `StagingStorageService` across GCS, S3, Azure Blob/ADLS Gen2, and HDFS/WebHDFS.
- [Listener & MCP Service](listener/index.md) — Litestar REST API, Vertebra runtime gate, Oracle durable job store, bounded caching, and `litestar-mcp` tools.
- [Operations & Deployment](operations/index.md) — CLI entry points, `GOESettings` env resolution, OpenTelemetry observability, and Cloud Run deployment.
- [Implementation Patterns](patterns/index.md) — Lazy CLI startup, `FrozenBaseStruct` typing, centralized JSON serialization, and concurrency safety.
- [Coding Standards](standards/index.md) — Python 3.10+, SQLSpec/SQLGlot boundaries, shell scripting, and test suite conventions.
- [Testing & Verification](testing/index.md) — Public-seam TDD strategy, offline unit doubles, and Docker Oracle integration harness.
- [Runtime & Adapter Gotchas](gotchas/index.md) — Non-obvious driver, dialect, and concurrency traps verified in production and CI.
