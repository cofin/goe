---
type: Research
research_id: "goe-architecture-redesign"
title: "GOE Architecture Redesign: DuckDB 2.0, SQLSpec 0.68, SQLGlot 30.24, and the Vertebra Runtime"
description: "Entry point for the codebase-wide primary-source audit and redesign that reduces GOE by roughly 69 percent while keeping every retained capability, removes N+1 metadata round-trips, unifies transport, SQL compilation, and caching, and moves the Listener onto Vertebra."
scope: architecture
tags: [architecture, redesign, duckdb, duckdb-oracle, sqlspec, sqlglot, msgspec, litestar, vertebra, caching]
status: stable
state: promoted
promoted_to: prd_05_foundation_typing_settings_and_adapter_reduction_20261024
created_at: 2026-10-24T16:00:00Z
updated_at: 2026-10-24T16:40:00Z
---

# GOE Architecture Redesign

This dossier records a full-repository primary-source investigation of GOE (`src/goe/`, 74,758 LOC across ~200 files, plus `sql/`, `templates/conf/`, `tools/`, and `pyproject.toml`) against `duckdb==2.0.0` ("Cyanoptera" LTS), signed community `cofin/duckdb-oracle` `v0.3.1`, `sqlspec==0.68.0`, `sqlglot==30.24.0`, `msgspec==0.22.0`, `litestar==2.25.0`, `litestar-mcp==0.16.0`, `oracledb==26.0.1`, `pyarrow==26.0.0`, and `cofin/vertebra` at `df36a30`.

## Executive Thesis

GOE modernized its CLI (`rich-click`), embedded service (Litestar, Granian, `litestar-queues`, `LitestarMCP`), OpenTelemetry observability, and first `OracleGateway`, BigQuery, and DuckDB slices across Master PRDs 1–4. Those slices sit on top of the original procedural core instead of replacing it:

1. **Parallel abstractions**: option schemas are declared in six layers (`orchestration_defaults.py`, `orchestration_config.py`, `config_validation_functions.py`, `options.py`, `cli/commands/offload.py`, `listener/schemas.py`); database access splits across `OracleGateway`, raw `OracleFrontendApi` cursors, inline `OracleSourceTable` SQL, and `ora_query.py`; SQL and predicate formatting splits across `sql_engine.py`, 8 `*_literal.py` classes, 6 `*_predicate.py` Lark transformers, a 96-method `BackendApiInterface`, and a 50-forwarder `BackendTableInterface`.
2. **Broken or unwired hot paths**: DuckDB 2.0.0 is installed while `duckdb_constants.py:6` pins `"1.5.5"` (the DuckDB transport is never available) and depends on the unported `northpolesec/duckdb-gcs` extension; `OracleGateway` discards its `StatementCacheHolder` on every query and issues an extra `ALTER SESSION` round-trip before each lookup; Listener periodic tasks write an unbounded cache that no endpoint reads while handlers block the event loop and leak Oracle sessions.
3. **Convergence opportunity**: DuckDB 2.0.0, signed `duckdb-oracle` v0.3.1, `python-oracledb` 26.0.1 PyCapsule Arrow streaming, `sqlspec` 0.68.0 (`OracleSyncConfig`, `BigQueryConfig`, `MssqlPythonConfig`, `sqlspec.storage`, `SQLFileLoader`), `sqlglot` 30.24.0, Vertebra's server runtime, and Vertebra's pure-Python idioms together reduce `src/goe/` from 74,758 LOC to roughly 22,800 LOC (-69.5%) while keeping every retained capability and improving throughput, warehouse cost, memory safety, and numeric precision.

---

## Resolved Decisions

| Decision | Resolution |
| :--- | :--- |
| **`QUERY_IMPORT` engine** | Replace the row-by-row engine with `python-oracledb` Thin Arrow batches written through DuckDB 2.0 (Parquet) or `fastavro` (Avro), keeping the `QUERY_IMPORT` option name and staged-file contract. A differential parity suite (unit, golden fixtures, and Oracle Free integration) proves equivalence before the old engine and encoders are deleted, and the golden-fixture parity tests remain afterwards. |
| **Listener job queue** | Remove `litestar-queues`. A GOE-owned durable job queue on `sqlspec` (`OracleJobStore` backed by `OracleDatabaseRegistry.for_options(config)`) persists jobs in Oracle repository tables (`GOE_LISTENER_JOBS` and `GOE_LISTENER_ENDPOINTS`) across multi-worker and multi-host deployments. It enforces one active offload per frontend table, renews leases by heartbeat for long runs, supports cooperative cancellation (`CANCEL_REQUESTED`), and powers `goe listener start --worker-only`. |
| **Listener runtime** | Run the Listener on Vertebra (`vtb run goe.listener.asgi:app --interface asgi`) and remove Granian, gated on a Vertebra release that closes six verified integration gaps (ASGI lifespan, `OPTIONS`/`HEAD` mount routing, packaged `vertebra-server` binary, embedded-topology deadlock fix, launcher contract, published wheels). |
| **Removed adapters** | Remove the Sqoop transport, the MapRFS filesystem scheme, and the Teradata frontend and repository client, with their options, templates, extras, tests, and knowledge chapters. |

---

## Impact Scorecard

| Metric | Current (`d6a02fe`) | Redesigned | Gain |
| :--- | :--- | :--- | :--- |
| **Source volume (`src/goe/`)** | 74,758 LOC, ~200 files | ~22,800 LOC, ~100 files | -69.5% |
| **Core dependencies** | 31 packages, including `fsspec[gcs]`, `PyYAML`, `tenacity`, `brotli`, `python-dateutil`, `boto3`, `azure-*`, `avro`, `granian` stack, `litestar-queues` | ~21 packages; cloud, format, and Hadoop SDKs in extras; `jinja2` declared; `vertebra` replaces the Granian stack | -10 core packages |
| **DuckDB transport** | Disabled by the `1.5.5` pin; one `:memory:` instance per worker thread; unsigned custom repository; `gcss://` | DuckDB `>=2.0.0`; signed community `oracle` v0.3.1; one shared instance clamped to 75% of the cgroup memory limit; core `httpfs` over `gs://` | Streaming extraction for OCI and Thin-only containers |
| **BigQuery ingestion per chunk** | 6 sequential jobs and 3 full staging-table scans | 1 `load_table_from_uri(..., WRITE_APPEND)` job over target-typed Parquet, or a Storage Write `PENDING` stream, with staged fallback | -83% jobs, 0 scan bytes billed |
| **Oracle metadata round-trips** | 22–35+ per offload; 40–70+ per `goe sync` table | 3–4 cold (1-RTT `offload_metadata_v`, 3-query cached catalog snapshot, no extra `ALTER SESSION`) | -85% to -93% |
| **BigQuery metadata RPCs** | 15–17 per incremental offload; 400–600 per 100-table report | 3 per offload; 2 `INFORMATION_SCHEMA` queries per dataset | -82% and -98% |
| **`goe report` on 200 tables** | 2,500–4,000+ sequential Oracle queries plus 800 BigQuery RPCs | 2 concurrent set-based queries and one DuckDB `GROUP BY ROLLUP` | Orders of magnitude fewer round-trips |
| **Listener** | 5 event-loop blocking paths, 1–3 leaked sessions per call, per-worker in-memory queues, unread cache, `/mcp` authentication bypass | Vertebra runtime, non-blocking pooled I/O, durable job queue, bounded singleflight cache, authenticated `/mcp` with 4 read-only tools | Multi-worker and multi-host ready |

---

## Research Chapters

1. **[Module-by-Module Redesign Blueprint, Defect Ledger, and Consolidation Budget](module-by-module-redesign.md)**: LOC budget, the verified defect ledger with `src/goe/...:line` citations, removed adapters, `src/goe/util/` dissolution, dependency and lint cleanup, and per-subsystem preservation contracts.
2. **[SQLSpec 0.68, SQLGlot 30.24, and Cohesive Caching Architecture](sqlspec-sqlglot-and-caching-architecture.md)**: `OracleGateway` cache and round-trip defects, the pooled `OracleDatabaseRegistry`, session tracing versus `gv$sql` `MODULE`/`ACTION`, native `sqlglot` Oracle support, the `PredicateIR` compiler, concurrent validation, single-pass schema sync, the set-based status report, and the cache boundaries.
3. **[DuckDB 2.0 LTS, `duckdb-oracle` v0.3.1, Arrow Streaming, and Cloud Storage Data Plane](duckdb2-arrow-and-storage-dataplane.md)**: DuckDB transport blockers, the precision-safe type boundary matrix, OCI and Thin Arrow extraction, `QUERY_IMPORT` replacement and parity verification, direct BigQuery ingestion, transport decomposition, and `sqlspec.storage`.
4. **[Vertebra Runtime, Worker, and Queue Evaluation for the GOE Listener](../../prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/research/vertebra-and-runtime-evaluation.md)**: Vertebra's server, gateways, topologies, supervision, worker lanes, and queue framework, the release gate, the queue decision, and the ported idioms.

---

## Risk Matrix

| Failure Mode | Trigger | Mitigation |
| :--- | :--- | :--- |
| **`NUMBER`/`BIGNUMERIC` and `TIMESTAMP(9)` precision loss** | `duckdb-oracle` maps unbounded `NUMBER` to `DOUBLE` and timestamps to microseconds; `GenericPredicateToTyped` uses `float()`. | RDBMS-side `TO_CHAR(col, 'TM')` and `TO_CHAR(..., 'FF9')`; `DecimalVal(str)` and nanosecond `TimestampVal` in `PredicateIR`; exact `Decimal` validation. |
| **`duckdb-oracle` 30-second call timeout and 64 KiB buffers** | `oracle_call_timeout_ms = 30000` default; `ub2` fetch buffers cap at 65,535 bytes. | `SET oracle_call_timeout_ms = 0;` on every transport session; LOB/XML/JSON/VECTOR tables and Thin-only hosts route to the Arrow path. |
| **DuckDB Arrow registration leaks and expiring GCS tokens** | Registered readers stay pinned in DuckDB's `nanobind` registry; OAuth tokens expire after about an hour. | `try ... finally: cursor.unregister(name)`; refresh `CREATE OR REPLACE TEMPORARY SECRET goe_gcs` when the token has less than 15 minutes left. |
| **`QUERY_IMPORT` output drift** | The new engine changes type rendering, null handling, or Avro schema. | Differential unit parity, committed golden fixtures from the current engine, and Oracle Free integration parity gate the cutover. |
| **`V$SQL` cursor flooding or broken `gv$sql` transport statistics** | Per-span SQL comments change `SQL_ID`; session tracing on transport sessions overwrites `MODULE`/`ACTION`. | `enable_session_tracing=True` only on repository pools; transport pools tag `CLIENT_IDENTIFIER` and `ECID` only. |
| **Direct BigQuery load cannot express a staged-only transform** | Backend UDF partition functions, >38-digit `BIGNUMERIC` strings, `--offload-chunk-column`, or `--preserve-load-table`. | Per-plan `BackendIngestStrategy` selection with automatic staged fallback. |
| **Listener served by an incomplete runtime** | Vertebra skips ASGI lifespan, drops `OPTIONS`/`HEAD`, or lacks a packaged binary. | The runtime switch is gated on the Vertebra release; an end-to-end Listener test on Vertebra (lifespan hooks, CORS preflight, drain) is part of the gate. |
| **Duplicate offload runs from the job queue** | Lease expiry during a 24-hour run, or two hosts claiming the same table. | Heartbeat-renewed leases and a unique index over active jobs per frontend table. |
| **Encrypted password or golden report drift** | Replacing AES-256-CBC + PKCS7 in `PasswordTools`, or changing `goe report --demo` keys. | `PasswordTools` stays byte-compatible; `StatusReportEnvelope.to_report_dict()` is verified against the golden SHA-256 digests. |

---

## Delivery Roadmap

| Master PRD | Scope |
| :--- | :--- |
| Master PRD 5 (`prd_05_foundation_typing_settings_and_adapter_reduction_20261024`) | Adapter reduction (Sqoop, MapRFS, Teradata) and `AdapterRegistry`, `goe.typing`, serializers, platform utilities, the architecture gate, declarative settings and options, the error model, `src/goe/util/` dissolution, and dependency slimming. |
| Master PRD 6 (`prd_06_sqlspec_oracle_data_layer_and_catalog_cache_20261024`) | Pooled `OracleDatabaseRegistry`, session tracing, the repository service and `OffloadMetadata`, the cached Oracle catalog snapshot, and the MSSQL frontend on `MssqlPythonConfig`. |
| Master PRD 7 (`prd_07_sqlglot_engine_predicates_validation_sync_and_report_20261024`) | Native `sqlglot` dialect engine, `PredicateIR`, concurrent cross-database validation, schema sync and status report redesign, and `ora_query.py` retirement. |
| [Master PRD 8](../spec.md) | DuckDB 2.0 engine hardening, Arrow extraction with `QUERY_IMPORT` parity, transport decomposition, and `sqlspec.storage` filesystems. |
| [Master PRD 9](../../prd_09_composable_backends_and_direct_bigquery_ingestion_20261024/spec.md) | Canonical column model and type registry, backend capabilities and cached catalog, BigQuery ingest strategies, and Snowflake, Synapse, and Hadoop alignment. |
| [Master PRD 10](../../prd_10_staged_orchestration_durable_jobs_and_vertebra_listener_20261024/spec.md) | Execution context and concurrency safety, the staged `OffloadPlan`, the stateless executor, the durable job queue, Listener cache and MCP, and the Listener on Vertebra. |
