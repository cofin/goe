---
type: Spec
flow_id: database_transport_and_cloud_storage_spans_20261010
title: "Chapter 4.3: Database (OracleGateway), Offload Transport, GCS & BigQuery Spans"
state: planned
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: null
created_at: 2026-10-10T17:15:00Z
updated_at: 2026-10-10T17:25:00Z
description: "Instrument OracleGateway database observability, Oracle V$SESSION.CLIENT_INFO and SQLCommenter trace tagging, OffloadTransport and subprocess spans/metrics, GOEGcs spans, and BigQuery job spans, labels, and slot/bytes metrics."
tags:
  - specification
  - opentelemetry
  - oracle
  - transport
  - duckdb
  - gcs
  - bigquery
parent_prd: prd_04_end_to_end_opentelemetry_observability_20261010
depends_on:
  - orchestration_step_and_listener_telemetry_20261010
  - sqlspec_oracle_data_layer_migration_20261010
  - bigquery_first_backend_modernization_20261010
  - duckdb_oracle_offload_transport_20261010
---

# Chapter 4.3: Database (`OracleGateway`), Offload Transport, GCS & BigQuery Spans

## Specification

## 1. Overview & Goals

With command and step spans (`goe.command.*`, `goe.step.*`) active in Chapter 4.2, Chapter 4.3 instruments the data plane across Oracle RDBMS, multi-engine Offload Transport (DuckDB, Query Import, Spark, Dataproc), Google Cloud Storage (`GOEGcs`), and Google BigQuery (`BigQueryBackendApi` / `BigQueryBackendTable`):
1. **Oracle Database Spans, `V$SESSION.CLIENT_INFO` & `SQLCommenter` Correlation**:
   - Wire `build_db_observability_config()` and `db_statement_observer()` into `OracleGateway` (`src/goe/persistence/oracle_gateway.py` from PRD 3 Chapter 3.1) so all Oracle repository and metadata queries emit child spans under the active `goe.step.*` span with `db.system="oracle"`, `db.operation`, `sqlspec.statement.hash`, and `goe.execution.id`.
   - Stamp W3C `traceparent` (55 bytes, within Oracle's 64-byte limit) onto `V$SESSION.CLIENT_INFO` (`self._db_conn.clientinfo = format_oracle_client_info()`) in `OracleFrontendApi._connect()` (`src/goe/offload/oracle/oracle_frontend_api.py:193-197`) and `DBMS_APPLICATION_INFO.SET_CLIENT_INFO(...)` in `OracleOffloadTransportRdbmsApi.get_rdbms_session_setup_commands()` (`src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py:176-226`) while keeping `MODULE` (`"GOE"`) and `ACTION` 100% unchanged so `LOG_SQL_STATS_QUERY_TEXT` (`v$sql` filtering by `module` and `action` at `L66-77`) continues to match identically.
   - Inject `format_sqlcommenter()` (`traceparent='00-...',goe_exec='...'`) into transport SQL comments when `GOE_OTEL_SQLCOMMENTER=true`.
2. **Offload Transport Spans (`goe.chunk`, `goe.transport.<method>`) & Subprocess `TRACEPARENT` Propagation**:
   - Instrument `transport_and_load_offload_chunk()` (`src/goe/offload/offload_transport_functions.py:275-352`) with a `goe.chunk` span (`goe.chunk.number`, `goe.chunk.rows_staged`, `goe.chunk.transport_bytes`, `goe.chunk.backend_bytes`) and record `goe.offload.bytes_loaded`.
   - Instrument `OffloadTransport` implementations (`DuckDB`, `QueryImport`, `SparkSubmit`, `SparkThrift`, `SparkLivy`, `SparkDataprocGcloud`, `SparkBatchesGcloud`, `Sqoop`) with `goe.transport.<method_lower>` spans and record `goe.offload.rows_transported` and `goe.offload.bytes_staged` metrics.
   - Propagate `TRACEPARENT`, `TRACESTATE`, `BAGGAGE`, and `GOE_EXECUTION_ID` into subprocess environments in `run_os_cmd()` (`src/goe/offload/offload_transport_functions.py:171-234`) and Spark driver/executor environment properties (`spark.driverEnv.TRACEPARENT`, `spark.executorEnv.TRACEPARENT`).
3. **Cloud Storage (`GOEGcs`) & BigQuery (`BigQueryBackendApi` / `BigQueryBackendTable`) Spans, Job Labels & Metrics**:
   - Instrument `GOEGcs` (`src/goe/filesystem/goe_gcs.py:97-308`) operations (`copy_from_local`, `copy_to_local`, `delete`, `list_dir`, `read`, `stat`, `write`) with `goe.storage.gcs.<op>` `SpanKind.CLIENT` spans.
   - Instrument `BigQueryBackendApi` (`src/goe/offload/bigquery/bigquery_backend_api.py:282-433`) and `BigQueryBackendTable` (`src/goe/offload/bigquery/bigquery_backend_table.py:105-555`) with `goe.backend.bigquery.<op>` (`ddl_dml`, `query`, `load`) `SpanKind.CLIENT` spans capturing `job_id`, `location`, `project`, `statement_type`, `total_bytes_processed`, `total_bytes_billed`, `slot_millis`, `num_dml_affected_rows`, and `output_rows`.
   - Inject GCP job labels (`goe_system`, `goe_execution_id`, `goe_command`, `goe_step`, `goe_trace_id`) into `_default_job_config()` (`bigquery_backend_api.py:282-287`) and `LoadJobConfig` (`bigquery_backend_table.py`) for BigQuery `INFORMATION_SCHEMA.JOBS_BY_PROJECT` attribution, and emit `goe.bigquery.bytes_billed` and `goe.bigquery.slot_ms` metrics.

---

## 2. Task Breakdown

| Task ID | Title | Target Files | Dependencies |
| :--- | :--- | :--- | :--- |
| **Task 1.1** | `OracleGateway` Observability, `V$SESSION.CLIENT_INFO` Tagging & `SQLCommenter` | `src/goe/observability/db.py`, `src/goe/persistence/oracle_gateway.py`, `src/goe/offload/oracle/oracle_frontend_api.py`, `src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py`, `tests/unit/observability/test_oracle_db_telemetry.py` | Chapter 4.2 |
| **Task 1.2** | Offload Transport Spans (`goe.chunk`, `goe.transport.*`), Subprocess `TRACEPARENT` & Transport Metrics | `src/goe/observability/transport.py`, `src/goe/offload/offload_transport_functions.py`, `src/goe/offload/offload_transport.py`, `tests/unit/observability/test_transport_telemetry.py` | Task 1.1 |
| **Task 1.3** | `GOEGcs` Storage Spans & BigQuery Client Spans, GCP Job Labels & Slot/Bytes Metrics | `src/goe/observability/cloud.py`, `src/goe/filesystem/goe_gcs.py`, `src/goe/offload/bigquery/bigquery_backend_api.py`, `src/goe/offload/bigquery/bigquery_backend_table.py`, `tests/unit/observability/test_gcs_and_bigquery_telemetry.py` | Task 1.1, Task 1.2 |

---

## 3. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run ruff format --check src/goe tests/unit/observability
uv run ruff check src/goe tests/unit/observability
uv run mypy src/goe
uv run pytest tests/unit/observability/ -v
```

## Implementation Plan

- [ ] 1.1 Implement `src/goe/observability/db.py` (`build_db_observability_config`, `db_statement_observer`), wire into `OracleGateway`, `OracleFrontendApi`, and `OracleOffloadTransportRdbmsApi`, and verify in `tests/unit/observability/test_oracle_db_telemetry.py`.
- [ ] 1.2 Implement `src/goe/observability/transport.py` (`traced_offload_chunk`, `traced_transport`), wire into `offload_transport_functions.py` (`run_os_cmd`, `transport_and_load_offload_chunk`) and `offload_transport.py`, and verify in `tests/unit/observability/test_transport_telemetry.py`.
- [ ] 1.3 Implement `src/goe/observability/cloud.py` (`traced_gcs_operation`, `traced_bigquery_job`, `build_bigquery_job_labels`), wire into `GOEGcs`, `BigQueryBackendApi`, and `BigQueryBackendTable`, and verify in `tests/unit/observability/test_gcs_and_bigquery_telemetry.py`.

## Continuity Snapshot

- **Current State**: Planned (`plan_revision: 1`).
- **Next Action**: Execute Task `1.1` (`database_transport_and_cloud_storage_spans_20261010:1.1`).
