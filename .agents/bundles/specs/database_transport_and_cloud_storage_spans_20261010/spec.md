---
type: Spec
flow_id: database_transport_and_cloud_storage_spans_20261010
title: "Chapter 4.3: Database (OracleGateway), Offload Transport, GCS & BigQuery Spans"
state: completed
plan_revision: 3
plan_commit: null
state_revision: 1
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: 8ddd9f3
created_at: 2026-10-10T17:15:00Z
updated_at: 2026-10-12T19:03:00Z
description: "Instrument the data plane: Oracle CLIENT_INFO tagging and OracleGateway SQLSpec spans, chunk/transport/subprocess spans for every transport including DuckDB batches, GOEGcs storage spans, and BigQuery job spans, labels, and slot/bytes metrics."
tags:
  - specification
  - opentelemetry
  - oracle
  - transport
  - duckdb
  - gcs
  - bigquery
parent: prd_04_end_to_end_opentelemetry_observability_20261010
depends_on:
  - orchestration_step_and_listener_telemetry_20261010
  - core_god_module_decomposition_20261010
  - sqlspec_oracle_data_layer_migration_20261010
  - bigquery_first_backend_modernization_20261010
  - duckdb_oracle_offload_transport_20261010
---

# Chapter 4.3: Database (`OracleGateway`), Offload Transport, GCS & BigQuery Spans

## Specification

### 1. Overview & Goals

With `goe.command.*`/`goe.step.*` spans from Chapter 4.2:

1. **Oracle**: `V$SESSION.CLIENT_INFO` carries the W3C `traceparent` (or `goe:<execution_id>`) on frontend connections and transport sessions while `MODULE`/`ACTION` stay unchanged (so `LOG_SQL_STATS_QUERY_TEXT` keeps matching); optional trace tokens in the Spark JDBC transport SQL comment; `OracleGateway` statements emit SQLSpec `sqlspec.query` CLIENT spans.
2. **Transport**: `goe.chunk` -> `goe.transport.<method_lower>` spans at the single `OffloadTransport.transport()` call site (covers Query Import, Spark Submit/Thrift/Livy, Dataproc, Sqoop, DuckDB), `goe.os_cmd.<exe>` spans with `TRACEPARENT`/`GOE_EXECUTION_ID` in subprocess env, `spark.executorEnv.*` propagation, DuckDB per-batch spans across its thread pool, and `goe.offload.rows_transported`/`bytes_staged`/`bytes_loaded` metrics.
3. **Cloud**: `goe.storage.gs.<op>` CLIENT spans for `GOEGcs`; `goe.backend.bigquery.{ddl_dml,query,load}` CLIENT spans with job statistics, `goe_step`/`goe_execution_id`/`goe_trace_id` job labels, and `goe.bigquery.bytes_billed`/`slot_ms` metrics.

### 2. Context

- Baseline commit `46890a8`. Post-PRD-3 targets and the chapters that create/change them:
  - `src/goe/persistence/oracle_gateway.py` (`OracleGateway`) — created by `sqlspec_oracle_data_layer_migration_20261010` task 1.1; its spec defines no observability hook, so task 1.1 adds one.
  - `src/goe/offload/transport/base.py` (`OffloadTransport`) — created by `core_god_module_decomposition_20261010` task 1.4; `src/goe/offload/offload_transport_functions.py` (`run_os_cmd`, `transport_and_load_offload_chunk`) is unchanged by PRD 1-3.
  - `src/goe/offload/transport/duckdb_transport.py` (`OffloadTransportDuckDB`, `_run_batch`, `_run_batches`) — created by `duckdb_oracle_offload_transport_20261010` task 1.3.
  - `src/goe/filesystem/goe_gcs.py` (`GOEGcs`) — changed by `gcp_adc_credential_unification_20261010` task 1.2 and `bigquery_first_backend_modernization_20261010` task 1.4 (`if_generation_match` uploads and single-pass `delete_blobs`).
  - `src/goe/offload/bigquery/bigquery_backend_api.py` (`BackendBigQueryApi`, `job_labels`, `sanitize_bigquery_label_value`, `query_and_wait`) and `src/goe/offload/bigquery/bigquery_backend_table.py` (`BackendBigQueryTable._load_native_load_table`) — changed by `bigquery_first_backend_modernization_20261010` tasks 1.2-1.3.
- Real class names: `OffloadTransportOracleApi` (not `OracleOffloadTransportRdbmsApi`), `BackendBigQueryApi`/`BackendBigQueryTable` (not `BigQueryBackendApi`/`BigQueryBackendTable`). `get_rdbms_session_setup_commands` is at `oracle_offload_transport_rdbms_api.py:399-444`; `LOG_SQL_STATS_QUERY_TEXT` (L66-77) queries `gv$sql`.
- Verified library facts: python-oracledb 4.0.2 has no tracing hooks; `clientinfo` is write-only, 64 bytes. sqlspec 0.62.1 `TelemetryConfig(enable_spans, provider_factory, resource_attributes)`, driver `attach_observability(runtime)`; an attached runtime disables the driver statement cache, so it is attached only when telemetry is enabled. google-cloud-bigquery 3.44.0 job statistics attributes and built-in `BigQuery.*` REST spans on the global tracer. Spark executor env via `spark.executorEnv.[Name]` (https://spark.apache.org/docs/latest/configuration.html#runtime-environment). BigQuery label rules: https://cloud.google.com/bigquery/docs/labels-intro#requirements.
- Zero-change when disabled: CLIENT_INFO, SQL comments, subprocess env, Spark properties, SQLSpec runtime, storage spans, and BigQuery spans are all gated on `get_observability_runtime().enabled`.
- **Public-Before-Private Function/Method Ordering**: Every created or touched module and class (both production and test files) must place all public functions/methods and dunder lifecycle methods (`__init__`, `__enter__`, `__exit__`, etc.) at the top of each module/class and all private (`_...`) helper functions/methods at the bottom.
- **`D-4.3-SQLCOMMENTER` (RESOLVED)**: SQLCommenter is emitted via `sqlspec.core.sqlcommenter` (`generate_comment`, `SQLCommenterContext`, and `StatementConfig.replace(enable_sqlcommenter=True, sqlcommenter_attributes={"db_driver": "oracledb", "framework": "goe"}, sqlcommenter_enable_traceparent=True, sqlcommenter_enable_context=True)`). For `OracleGateway`, `attach_db_observability(driver)` enables SQLSpec's native AST SQLCommenter transform when `settings.sqlcommenter` is `True`; for Spark JDBC transport queries (`_get_spark_jdbc_query_text`, which wraps `sql_comment` in `f" /* {sql_comment} */"` and passes `rdbms_source_query` through `_spark_sql_option_safe`, escaping `'` as `\'`), `format_sqlcommenter(**attributes)` calls `generate_comment(attrs)` and `build_transport_sql_comment(existing_comment)` strips the outer `/*` and `*/` before appending after `existing_comment` so `LOG_SQL_STATS_QUERY_TEXT` keeps matching.

### 3. Requirement Traceability

| Requirement (PRD 4) | Task | Verification |
| :--- | :--- | :--- |
| `OracleGateway` query spans; `CLIENT_INFO`; MODULE/ACTION invariant; SQLSpec SQLCommenter (`D-4.3-SQLCOMMENTER`) | 1.1 | `test_oracle_telemetry.py`, `test_offload_transport_rdbms_api.py` |
| `goe.chunk`, `goe.transport.<method>`, `run_os_cmd` `TRACEPARENT`, Spark env, transport metrics | 1.2 | `test_transport_telemetry.py`, existing transport tests |
| DuckDB transport coverage ("all transports") | 1.2 (call site), 1.3 (batches) | `test_duckdb_transport_telemetry.py` |
| `GOEGcs` `goe.storage.gs.<op>` spans | 1.4 | `test_storage_telemetry.py` |
| BigQuery spans, job labels, slot/bytes metrics | 1.5 | `test_bigquery_telemetry.py`, `tests/unit/offload/bigquery/` |

### 4. Verification Plan

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run ruff format --check src/goe tests/unit/observability
uv run ruff check src/goe tests/unit/observability
uv run mypy src/goe
uv run pytest tests/unit/observability/ tests/unit/offload/ tests/unit/filesystem/ tests/unit/persistence/ -v
uv run python -c "import ast,sys; is_priv=lambda n:n.startswith('_') and not (n.startswith('__') and n.endswith('__')); bad=[(p,getattr(s,'name','<module>'),f.name) for p in sys.argv[1:] for s in ast.walk(ast.parse(open(p).read())) if isinstance(s,(ast.Module,ast.ClassDef)) for funcs in [[n for n in s.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]] for i,f in enumerate(funcs) if not is_priv(f.name) and any(is_priv(g.name) for g in funcs[:i])]; assert not bad, bad" src/goe/observability/db.py src/goe/observability/transport.py src/goe/observability/storage.py src/goe/observability/bigquery.py src/goe/offload/oracle/oracle_frontend_api.py src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py src/goe/persistence/oracle_gateway.py src/goe/offload/offload_transport_functions.py src/goe/offload/transport/base.py src/goe/offload/transport/duckdb_transport.py src/goe/filesystem/goe_gcs.py src/goe/offload/bigquery/bigquery_backend_api.py src/goe/offload/bigquery/bigquery_backend_table.py tests/unit/observability/test_oracle_telemetry.py tests/unit/observability/test_transport_telemetry.py tests/unit/observability/test_duckdb_transport_telemetry.py tests/unit/observability/test_storage_telemetry.py tests/unit/observability/test_bigquery_telemetry.py
```

## Implementation Plan

- [x] 1.1 Oracle session trace tagging, SQLCommenter helper, and `OracleGateway` SQLSpec spans ([tasks/1.1.md](tasks/1.1.md))
- [x] 1.2 Offload chunk, transport, and subprocess spans with `TRACEPARENT` propagation ([tasks/1.2.md](tasks/1.2.md))
- [x] 1.3 DuckDB transport per-batch spans with thread context propagation ([tasks/1.3.md](tasks/1.3.md))
- [x] 1.4 `GOEGcs` storage CLIENT spans ([tasks/1.4.md](tasks/1.4.md))
- [x] 1.5 BigQuery job spans, trace job labels, and slot/bytes metrics ([tasks/1.5.md](tasks/1.5.md))

## Continuity Snapshot

- **Flow / lifecycle**: `database_transport_and_cloud_storage_spans_20261010`, `planned`.
- **Current task / claimant**: none.
- **Last verified checkpoint**: none.
- **Decisions**: instrument the single transport call site instead of eight subclasses; telemetry gating on every data-plane hook; extend PRD 3 BigQuery labels (`job_labels` / `sanitize_bigquery_label_value`) rather than re-implementing them; `D-4.3-SQLCOMMENTER` resolved (emit spec-compliant SQLCommenter via `sqlspec.core.sqlcommenter`).
- **Blockers**: Chapter 4.2 and PRD 3 chapters listed in `depends_on` must be complete.
- **Next exact step**: execute task `1.1` (`database_transport_and_cloud_storage_spans_20261010:1.1`).
- **Plan identity**: `plan_revision: 3`, `plan_commit: null`. **State identity**: `state_revision: 0`.
- **Relevant knowledge**: `.agents/bundles/knowledge/frontends/oracle.md`, `.agents/bundles/knowledge/transport/`, `.agents/bundles/knowledge/storage/`, `.agents/bundles/knowledge/backends/bigquery.md`, `.agents/bundles/knowledge/standards/database-and-sql.md`.
