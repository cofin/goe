---
type: Spec
flow_id: transport_decomposition_and_auto_selection_20261024
title: "Chapter 8.3: Transport Decomposition, Deterministic Selection, and Unified Canary Probe"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-24T16:45:00Z
updated_at: 2026-10-24T16:45:00Z
description: "Decomposes the monolithic OffloadTransport base class and legacy re-export hub into focused protocol, selector, Spark execution, polling, and unified canary modules while promoting DuckDB in automatic transport selection."
tags:
  - refactor
  - transport
  - duckdb
  - spark
parent_prd: prd_08_duckdb2_transport_query_import_parity_and_storage_20261024
depends_on:
  - arrow_extraction_and_query_import_parity_20261024
research:
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/duckdb2-arrow-and-storage-dataplane.md
  - .agents/bundles/specs/prd_08_duckdb2_transport_query_import_parity_and_storage_20261024/research/module-by-module-redesign.md
---

# Chapter 8.3: Transport Decomposition, Deterministic Selection, and Unified Canary Probe

## Specification

### 1. Overview and Goals

This chapter replaces the monolithic `OffloadTransport` hierarchy (`src/goe/offload/transport/base.py`, `src/goe/offload/transport/factory.py`, `src/goe/offload/transport/availability.py`, and the legacy `src/goe/offload/offload_transport.py` hub) with a modular transport subsystem built on `FrozenBaseStruct` contracts:

1. **Transport Protocol and Deterministic `AUTO` Selection (`protocol.py`, `selector.py`)**: Defines `OffloadTransportProtocol`, `TransportPlan(FrozenBaseStruct)`, `TransportBatchSplit(FrozenBaseStruct)`, and `TransportExecutionSummary(FrozenBaseStruct)`. Implements `TransportSelector` with deterministic `AUTO` precedence: small tables at or below `query_import_max_bytes` use `QUERY_IMPORT` Arrow streaming; medium and single-host tables up to `OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES` (`100G`) use `DUCKDB` (when DuckDB 2.0 is available); multi-TB or cluster-only workloads select from `SPARK_DATAPROC_GCLOUD`, `SPARK_BATCHES_GCLOUD`, `SPARK_SUBMIT`, `SPARK_THRIFT`, or `SPARK_LIVY`. Sqoop and Teradata branches are removed.
2. **Spark Transport Package and Polling Relocation (`src/goe/offload/transport/spark/`)**: Relocates `PollingThread` from `src/goe/util/polling_thread.py` into `src/goe/offload/transport/spark/polling.py` alongside `RdbmsTransportStatsPoller`, `TransportSplitPlanner`, `SparkCommandRunner` (eliminating duplicate `_scp_from_host` definitions), and JSON-safe `PySparkCodegen`. Moves `spark_submit.py`, `spark_thrift.py`, `spark_livy.py`, and `dataproc.py` into `src/goe/offload/transport/spark/`, upgrades `tools/spark-listener/src/main/scala/com/gluent/spark/GOETaskListener.scala` to SLF4J, updates `tools/transport/Makefile` to Spark `3.5.3`, and deletes `tools/goe-shell-functions.sh`.
3. **Unified `TransportCanaryProbe` and Monolith Retirement (`canary.py`, `registry.py`)**: Replaces all per-transport `*Canary` subclasses (`OffloadTransportSparkSubmitCanary`, `OffloadTransportSparkThriftCanary`, `OffloadTransportSparkLivyCanary`, `OffloadTransportSparkGcloudDataprocCanary`, `OffloadTransportSparkGcloudBatchesCanary`) with a single `TransportCanaryProbe` that also covers `DUCKDB` and `QUERY_IMPORT`. Updates `src/goe/offload/registry.py` to wire `TransportSelector` and `TransportCanaryProbe`, and deletes `src/goe/offload/transport/factory.py`, `src/goe/offload/transport/base.py`, `src/goe/offload/transport/availability.py`, and `src/goe/offload/offload_transport.py`.

### 2. Code Analysis Summary

- `src/goe/offload/transport/base.py:1-1215`: Defines `OffloadTransport`, a 55-attribute base class mixing batch split planning (`_get_offload_split_type`, `_get_id_range_splits`), `gv$sql` polling (`_start_ClickThread` / `PollingThread`), SSH/SCP execution with duplicate SCP helpers (`_scp_to_host` and duplicate `_scp_from_host` at `base.py:456-489`), and raw `%` string interpolation into generated PySpark scripts (`base.py:948-983`).
- `src/goe/offload/transport/factory.py:1-381`: Defines `GCP_AUTO_TRANSPORT_METHODS` (`factory.py:65-72`) without `OFFLOAD_TRANSPORT_METHOD_DUCKDB`, retains `OFFLOAD_TRANSPORT_SQOOP` (`factory.py:17, 43-44, 101-107`) and `DBTYPE_TERADATA` (`factory.py:12`), and dispatches 5 separate `*Canary` classes in `offload_transport_SelectCanary` (`factory.py:325-381`).
- `src/goe/offload/transport/availability.py:1-338`: Mixes Spark, Livy, Dataproc, `QUERY_IMPORT`, and obsolete Sqoop availability functions (`is_sqoop_available`, `is_sqoop_by_query_available` at `availability.py:258-338`).
- `src/goe/offload/transport/spark_submit.py:1-214`, `spark_thrift.py:1-265`, `spark_livy.py:1-395`, `dataproc.py:1-342`: Subclass `OffloadTransport` and duplicate `*Canary` boilerplate (~330 LOC total).
- `src/goe/util/polling_thread.py:1-92`: Daemon `threading.Thread` wrapper used exclusively by transport SQL statistics polling.
- `src/goe/offload/offload_transport.py:1-146`: Legacy re-export module created after initial file splitting; callers should resolve transports through `goe.offload.registry` and `goe.offload.transport.selector`.
- `tools/spark-listener/src/main/scala/com/gluent/spark/GOETaskListener.scala:1-120`, `tools/transport/Makefile:1-50`, `tools/goe-shell-functions.sh`, `Makefile:187`: Scala listener imports removed Log4j 1.x `org.apache.log4j.Logger`, builds against Spark `3.2.4`, and `Makefile` references dead `tools/goe-shell-functions.sh`.

### 3. Requirements

- **R1**: Define `OffloadTransportProtocol`, `TransportBatchSplit(FrozenBaseStruct, array_like=True)`, `TransportPlan(FrozenBaseStruct)`, and `TransportExecutionSummary(FrozenBaseStruct)` in `src/goe/offload/transport/protocol.py`.
- **R2**: Implement `TransportSelector` in `src/goe/offload/transport/selector.py` with deterministic `AUTO` precedence: small tables (`estimated_bytes <= query_import_max_bytes`) select `QUERY_IMPORT`; medium and single-host tables (`estimated_bytes <= duckdb_max_bytes`, default `100 GiB`) select `DUCKDB`; multi-TB or distributed workloads select `SPARK_DATAPROC_GCLOUD`, `SPARK_BATCHES_GCLOUD`, `SPARK_SUBMIT`, `SPARK_THRIFT`, or `SPARK_LIVY`. Remove all Sqoop and Teradata selection branches.
- **R3**: Relocate `PollingThread` from `src/goe/util/polling_thread.py` to `src/goe/offload/transport/spark/polling.py` with `RdbmsTransportStatsPoller`, `TransportSplitPlanner`, `SparkCommandRunner`, and JSON-parameterized `PySparkCodegen`, and move `spark_submit.py`, `spark_thrift.py`, `spark_livy.py`, and `dataproc.py` into `src/goe/offload/transport/spark/`.
- **R4**: Modernize `tools/spark-listener/src/main/scala/com/gluent/spark/GOETaskListener.scala` to `org.slf4j.LoggerFactory`, update `tools/transport/Makefile` default Spark version to `3.5.3`, and delete `tools/goe-shell-functions.sh`.
- **R5**: Implement `TransportCanaryProbe` in `src/goe/offload/transport/canary.py` covering `DUCKDB`, `QUERY_IMPORT`, `SPARK_SUBMIT`, `SPARK_THRIFT`, `SPARK_LIVY`, `SPARK_DATAPROC_GCLOUD`, and `SPARK_BATCHES_GCLOUD`, wire it in `src/goe/offload/registry.py`, and delete `src/goe/offload/transport/{factory,base,availability}.py` and `src/goe/offload/offload_transport.py`.

### 4. Requirement Traceability

| Requirement | Task | Verification |
| :--- | :--- | :--- |
| R1, R2 | `1.1` | `uv run pytest tests/unit/offload/transport/test_selector.py -v` |
| R3, R4 | `1.2` | `uv run pytest tests/unit/offload/transport/test_spark_transports.py -v` |
| R5 | `1.3` | `uv run pytest tests/unit/offload/transport/test_canary.py -v` |

### 5. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/offload/transport/test_selector.py tests/unit/offload/transport/test_spark_transports.py tests/unit/offload/transport/test_canary.py -v
uv run ruff format --check src/goe/offload/transport src/goe/offload/registry.py tests/unit/offload/transport
uv run ruff check src/goe/offload/transport src/goe/offload/registry.py tests/unit/offload/transport
uv run mypy src/goe
uv run python tools/verify_architecture.py
```

## Implementation Plan

### Phase 1: Transport Protocol, Spark Decomposition, and Unified Canary
- [ ] 1.1 Define Transport Protocol and Deterministic Selector ([tasks/1.1.md](tasks/1.1.md))
- [ ] 1.2 Decompose Spark Transports, Relocate PollingThread, and Update Spark Tooling ([tasks/1.2.md](tasks/1.2.md))
- [ ] 1.3 Unify Transport Canary Probe and Retire Monolithic Transport Modules ([tasks/1.3.md](tasks/1.3.md))

## Continuity Snapshot

- **Flow / lifecycle**: `transport_decomposition_and_auto_selection_20261024`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: `TransportSelector` orders `QUERY_IMPORT` for small tables below `query_import_max_bytes`, `DUCKDB` for medium/single-host tables up to `100 GiB`, and Spark cluster transports above `100 GiB`; `PollingThread` moves into `src/goe/offload/transport/spark/polling.py`; `TransportCanaryProbe` replaces all `*Canary` subclasses.
- **Discoveries**: none yet.
- **Blockers**: `arrow_extraction_and_query_import_parity_20261024` must complete first.
- **Next exact step**: execute task `1.1` (`transport_decomposition_and_auto_selection_20261024:1.1`).
- **Plan identity**: `plan_revision: 1`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/transport/duckdb.md`, `.agents/bundles/knowledge/transport/spark-dataproc.md`.
