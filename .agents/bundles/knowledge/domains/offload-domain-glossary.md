---
type: domain
title: Offload Domain Glossary & Entity Invariants
description: Ubiquitous vocabulary, entity lifecycles, and domain invariants for GOE offload planning, canonical typing, staging, and durable jobs.
status: stable
tags:
  - domain
  - glossary
  - invariants
  - offload
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: offload-models
    resource: src/goe/orchestration/models.py::OffloadPlan
    title: Immutable Staged Offload Plan Models
  - id: column-spec
    resource: src/goe/offload/schema/column_spec.py::ColumnSpec
    title: Canonical Column Specification
  - id: job-models
    resource: src/goe/listener/jobs/models.py::JobRecord
    title: Durable Listener Job Record Model
---

# Offload Domain Glossary & Entity Invariants

<!-- truth: start -->
- **Frontend (`FrontendApiInterface` / `FrontendTableInterface`)**: Source relational database system (`ORACLE`, `MSSQL`) holding online transactional tables and the `GOE_REPO` metadata repository.
- **Backend (`BackendApiInterface` / `BackendTableInterface`)**: Target analytical data warehouse (`BIGQUERY`, `SNOWFLAKE`, `SYNAPSE`, `HIVE`, `IMPALA`) receiving offloaded table slices.
- **`OffloadPlan` (`src/goe/orchestration/models.py`)**: Immutable `FrozenBaseStruct` capturing the complete resolved execution plan (`DiscoveryResult`, `BoundaryResult`, target `ColumnSpec` tuple, transport method, and staging URI) before any data movement executes.[^offload-models]
- **Data Split (`100:0` vs `90:10`)**: `100:0` offloads the full table; `90:10` offloads historical partitions or predicates up to a high-water mark (`OffloadBoundaryRule`) while keeping recent partitions online in the frontend.
- **`ColumnSpec` (`src/goe/offload/schema/column_spec.py`)**: Immutable canonical representation of a column's name, canonical type (`GOE_TYPE_*`), precision, scale, nullability, char semantics, partition metadata (`ColumnPartitionInfo`), and staging representation (`ColumnStagingSpec`).[^column-spec]
- **Durable Job (`JobRecord` in `src/goe/listener/jobs/models.py`)**: Oracle-persisted asynchronous orchestration task in `GOE_LISTENER_JOBS` transitioning through `QUEUED -> RUNNING -> SUCCEEDED | FAILED | CANCEL_REQUESTED -> CANCELLED`.[^job-models]
<!-- truth: end -->

## Core Domain Terms

| Term | Canonical Symbol | Definition & Invariant |
| :--- | :--- | :--- |
| **Execution ID** | `src/goe/orchestration/execution_id.py::ExecutionId` | Globally unique 16-byte / 36-char UUIDv4 identifier assigned to every CLI command or Listener job and bridged to W3C `traceparent` trace/span IDs. |
| **Execution Context** | `src/goe/orchestration/context.py::ExecutionContext` | Explicit per-operation context holding `ExecutionId`, `OffloadOperationOptions`, `GOELogFileHandle`, and `ExecutionSink`; eliminates module-global state across concurrent runs. |
| **Discovery Result** | `src/goe/orchestration/models.py::DiscoveryResult` | Stage 1 snapshot of frontend columns, partition metadata, prior `OffloadMetadata`, and backend target table existence.[^offload-models] |
| **Boundary Result** | `src/goe/orchestration/models.py::BoundaryResult` | Stage 2 output resolving high-water marks (`HWM`), `PartitionChunkSpec` slices, and `PredicateIR` filters for IPA (`RANGE`/`LIST`) or PBO (`100:0`/`90:10`). |
| **Staging File Spec** | `src/goe/offload/staging/staging_file.py::StagingFileSpec` | Immutable specification of the intermediate staging format (`PARQUET` default on GCP, `AVRO` legacy/Hadoop), URI prefix, and staging column cast rules. |
| **Ingest Strategy** | `src/goe/offload/bigquery/ingest_strategy.py::BigQueryIngestStrategy` | Pluggable backend load mechanism: `BigQueryLoadJobIngestStrategy` (`NATIVE` direct Parquet `load_table_from_uri`) or `BigQueryExternalTableIngestStrategy` (`EXTERNAL` table + `INSERT ... SELECT`). |
| **Predicate IR** | `src/goe/offload/predicates/ast_nodes.py::PredicateNode` | Dialect-neutral AST produced by `PredicateParser` from `--offload-predicate` DSL strings and compiled by `PredicateCompiler` into Oracle, BigQuery, Snowflake, Synapse, or Hive SQL. |
| **Confirmation Gate** | `src/goe/listener/mcp.py::ConfirmationGate` | Multi-round-trip (MRTR) HMAC-SHA256 challenge/token gate requiring explicit user confirmation before any mutating MCP tool executes. |

## Entity Lifecycles

### Staged Offload Pipeline (`OffloadPipeline`)
1. **`DiscoveryStage`**: Inspects source catalog (`OracleCatalogService` / `FrontendCatalogCache`), existing `OffloadMetadata`, and backend catalog (`CachedBackendCatalog`).
2. **`BoundaryStage`**: Evaluates partition high-water marks (`IPA`) or predicate rules (`PBO`) and constructs `PartitionChunkSpec` extraction slices.
3. **`PlanResolutionStage`**: Maps source columns through `TYPE_REGISTRY` (sampling ambiguous `NUMBER` columns when needed), selects the transport method (`QUERY_IMPORT`, `DUCKDB`, or `SPARK_*`), and freezes an `OffloadPlan`.[^offload-models][^column-spec]
4. **`OffloadPlanExecutor`**: Extracts data at a pinned `AS OF SCN` snapshot into staging storage, loads/merges into the backend table, runs `CrossDbValidator`, persists `OffloadMetadata`, and cleans staging files.

### Durable Listener Job State Machine (`OracleJobStore`)
- `QUEUED`: Inserted into `GOE_LISTENER_JOBS` with active-table uniqueness enforced by `GOE_LISTENER_JOBS_ACTIVE_TBL_UQ`.
- `RUNNING`: Claimed via `SELECT ... FOR UPDATE SKIP LOCKED` by a `DurableJobWorker` lease (`JobLease`).
- `CANCEL_REQUESTED`: Set by `cancel_job()`; observed by `_CooperativeCancelSink` on the next step boundary to unwind the worker thread before releasing the active-table unique index.
- Terminal states: `SUCCEEDED`, `FAILED`, or `CANCELLED`.[^job-models]

[^offload-models]: `src/goe/orchestration/models.py::OffloadPlan` — Immutable `FrozenBaseStruct` models for staged offload discovery, boundary resolution, planning, and execution results.
[^column-spec]: `src/goe/offload/schema/column_spec.py::ColumnSpec` — Canonical column specification and adapter bridging mixins.
[^job-models]: `src/goe/listener/jobs/models.py::JobRecord` — Durable job queue record, lease, and heartbeat models.
