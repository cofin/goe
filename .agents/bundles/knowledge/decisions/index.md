---
title: Architectural Decision Records
description: Durable records of foundational architectural, data plane, and runtime boundary choices in GOE.
---

# Architectural Decision Records

This directory records architectural decisions that carry lasting structural commitments and real trade-offs.

## Decisions

- [ADR-001: Pooled SQLSpec Oracle Data Layer & SQLGlot AST Boundary](adr-001-sqlspec-oracle-and-sqlglot-ast-seam.md) — Pooling Oracle connections with SQLSpec `OracleDatabaseRegistry` and isolating all `sqlglot` AST construction behind `DialectSqlEngine` and `PredicateCompiler`.
- [ADR-002: DuckDB 2.0 Data Plane, Arrow Parquet Extraction & Direct BigQuery Loads](adr-002-duckdb2-dataplane-and-target-typed-bigquery-loads.md) — Standardizing on DuckDB 2.0 (`cofin/duckdb-oracle` + `httpfs`), PyArrow Parquet staging, and direct `load_table_from_uri` BigQuery ingestion.
- [ADR-003: Staged OffloadPipeline, Vertebra Listener & Oracle-Only Durable Job Queue](adr-003-staged-offload-pipeline-and-oracle-durable-listener.md) — Replacing stateful God-objects and Redis/in-memory queues with a 4-stage `OffloadPipeline`, Vertebra ASGI runtime, and `OracleJobStore`.
