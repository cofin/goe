---
type: Spec
flow_id: bigquery_first_backend_modernization_20261010
title: "Chapter 3.3: BigQuery-First Backend & Transport Modernization"
state: completed
plan_revision: 3
plan_commit: null
state_revision: 0
current_task: null
last_operation: finish
operation_targets: []
last_verified_checkpoint: 8fcb959
created_at: 2026-10-10T16:00:00Z
updated_at: 2026-10-11T00:10:00Z
description: Make Google BigQuery and GCS the first-class GOE backend path by replacing Legacy SQL partition metadata, modernizing BackendBigQueryApi query execution and lifecycle, adding native BigQuery load jobs for staged files, removing redundant GOEGcs existence/poll round trips, and prioritizing GCP transports, with zero feature loss and no edits to deprioritized backends.
tags: [refactor, bigquery, gcs, transport, backend]
parent: prd_03_sqlspec_bigquery_and_duckdb_engine_20261010
depends_on:
  - sqlspec_oracle_data_layer_migration_20261010
  - sqlglot_ast_and_predicate_engine_20261010
research: [research/bigquery_first_and_test_harness.md]
---

# Chapter 3.3: BigQuery-First Backend & Transport Modernization

## Specification

### Context & Baseline

- All file/line citations are against baseline commit `46890a8`. Earlier chapters change several of the same files; every task cites the **symbol name** alongside the baseline line so an executor locates the code with `grep -n` after earlier chapters land.
- Earlier-chapter changes this flow builds on (do not redo them):
  - `gcp_adc_credential_unification_20261010:1.1` creates `src/goe/util/gcp_credentials.py` and the `google_cloud_project` config option (the BigQuery job/billing project). This flow therefore adds **no** `BIGQUERY_BILLING_PROJECT` option.
  - `gcp_adc_credential_unification_20261010:1.2` rewrites `BackendBigQueryApi._get_bq_client` / `_get_kms_client` / `_backend_project_name` and `GOEGcs.__init__` to pass resolved credentials, and creates `tests/unit/offload/bigquery/test_bigquery_backend_api.py` and `tests/unit/filesystem/test_goe_gcs.py`.
  - `oracle_ci_and_bigquery_test_harness_20261010` adds the live WIF `integration-bigquery` CI job and `pytest-databases[oracle]`; no BigQuery emulator.
  - `core_god_module_decomposition_20261010:1.4` moves `choose_offload_transport_method` to `src/goe/offload/transport/factory.py` and `OffloadTransportQueryImport` to `src/goe/offload/transport/query_import.py`, leaving `src/goe/offload/offload_transport.py` as a `<= 60` LOC re-export facade.
  - `strict_mypy_type_safety_ratchet_20261010` enables strict mypy; new code is fully annotated.
  - `sqlglot_ast_and_predicate_engine_20261010:1.2` replaces `_create_external_table`, `_create_table_properties_clause`, `_gen_bigquery_create_table_sql_text` and the `get_table_ddl` `re.sub` in `bigquery_backend_api.py`. This flow does not touch those methods.
- Verified external facts (sources recorded in `research/bigquery_first_and_test_harness.md` §C):
  - `google-cloud-bigquery` is locked at `3.44.0` (`uv.lock:1346-1347`); `Client.query_and_wait(query, *, job_config, location, project, api_timeout, wait_timeout, retry, job_retry, page_size, max_results, ...) -> RowIterator` exists since `3.14.0`; `Client(client_info: google.api_core.client_info.ClientInfo | None)`; `LoadJobConfig` exposes `source_format`, `write_disposition`, `decimal_target_types`, `destination_encryption_configuration`, `labels`.
  - `INFORMATION_SCHEMA.PARTITIONS` (Preview) requires a dataset qualifier; `partition_id` is `NULL` for unpartitioned tables and `__UNPARTITIONED__` can appear twice (active + long-term storage), so queries use `DISTINCT`.
  - `google-cloud-storage` is locked at `3.13.1`; `Bucket.delete_blobs(blobs, on_error=...)` deletes one blob per request (no batching by itself); `transfer_manager` has **no** bulk delete; `ifGenerationMatch=0` makes an upload fail with HTTP 412 (`google.api_core.exceptions.PreconditionFailed`) when a live object exists.
  - GCS object listing is strongly consistent, so post-delete sleep/re-list loops are redundant.

### Problem & Goal

1. `BackendBigQueryApi.get_table_partition_count` / `get_table_partitions` (`bigquery_backend_api.py:1510-1532`) run Legacy SQL `[...$__PARTITIONS_SUMMARY__]` with `query_options={"use_legacy_sql": True}`, which forces a Legacy SQL branch in `_default_job_config` (`L282-287`).
2. `BackendBigQueryApi.__del__` (`L173-174`) calls `close()` during garbage collection; `close()` (`L813-815`) is not idempotent. Explicit `close()` callers already exist (`backend_api_factory.py:117`, `backend_table.py:1416`, `goe.py:1854`).
3. `_execute_query_fetch_x` (`L358-433`) always uses `client.query()` + `result()` plus a redundant `state != "DONE"` check; jobs carry no labels; the client sends no GOE user agent; `_execute_global_session_parameters` (`L332-350`) only allows `maximum_bytes_billed` and `use_query_cache`; `create_database` (`L828-856`) never sets `default_kms_key_name`.
4. `BackendBigQueryTable._create_load_table` (`bigquery_backend_table.py:105-138`) always creates an external table over `.../part*`, so `validate_type_conversions` (`L549-554`) and `load_final_table` (`L456-473`) re-scan GCS. BigQuery staging defaults to Avro (`orchestration_defaults.py:683-691`, `templates/conf/offload.env.template.bigquery:61`).
5. `GOEGcs.copy_from_local` / `write` (`goe_gcs.py:97-111`, `L295-307`) do an `exists()` RPC before upload (TOCTOU); `GOEGcs.delete` (`L129-184`) calls `exists()` per blob, sleeps via `_post_cloud_delete_wait`, and re-lists to raise `GOEDfsDeleteNotComplete`.
6. `choose_offload_transport_method` (`offload_transport.py:553-598`) in `AUTO` evaluates `SPARK_THRIFT, QUERY_IMPORT, SPARK_LIVY, SPARK_SUBMIT, SQOOP, SQOOP_BY_QUERY, SPARK_DATAPROC_GCLOUD, SPARK_BATCHES_GCLOUD`, so on `BACKEND_DISTRIBUTION=GCP` Dataproc is chosen only after every GOE/Sqoop rule. `OffloadTransportQueryImport` caps fetch size at `1000` (`L2389-2390`) and shells out `rm -f` (`L2479`, `L2484`).

### Requirements

- **REQ-1** BigQuery staging defaults to `PARQUET` and a validated `BIGQUERY_LOAD_TABLE_MODE` (`NATIVE` default, `EXTERNAL` fallback) option exists. → Task 1.1
- **REQ-2** Legacy SQL partition queries and the `use_legacy_sql` branch are deleted in favor of parameterized `INFORMATION_SCHEMA.PARTITIONS`; `__del__` is deleted; `close()` is idempotent with `__enter__`/`__exit__`; non-profiled reads use `query_and_wait`; jobs carry sanitized `goe_version`/`goe_execution_id`/`goe_command` labels; the client sends `ClientInfo(user_agent="goe/<version>")`; the session allow-list adds `labels`, `priority`, `job_timeout_ms`, `reservation`; `create_database` sets `default_kms_key_name` when CMEK is configured. → Task 1.2
- **REQ-3** `BackendBigQueryTable` loads staged files into a native load table with `load_table_from_uri` (`WRITE_TRUNCATE`, CMEK, labels, `decimal_target_types` for Parquet) when `BIGQUERY_LOAD_TABLE_MODE=NATIVE`, and keeps the external table when `EXTERNAL`. → Task 1.3
- **REQ-4** `GOEGcs` uploads use `if_generation_match=0` for no-overwrite, deletes drop per-blob `exists()` and post-delete wait/re-list, preserving NotFound tolerance. → Task 1.4
- **REQ-5** GCP `AUTO` order is `QUERY_IMPORT, SPARK_DATAPROC_GCLOUD, SPARK_BATCHES_GCLOUD, SPARK_SUBMIT, SPARK_THRIFT, SPARK_LIVY` (Sqoop never evaluated); Query Import allows fetch size up to `10000` for BigQuery and removes the local file with `Path.unlink` in `finally`. → Task 1.5

### Zero Feature Loss & Containment

- Preserve CMEK on tables (`OPTIONS(kms_key_name=...)`), query jobs (`_add_kms_key_to_job_config`) and `_check_kms_key_name`; the UTC `ConnectionProperty("time_zone", "UTC")` in `_default_job_config`; dry-run SQL logging; `_staging_to_backend_cast` / `validate_type_conversions` SQL (native load tables infer the same column types from the self-describing Parquet/Avro files as the external table does).
- Partition metadata keeps legacy semantics: every distinct non-NULL `partition_id` (including `__NULL__` and `__UNPARTITIONED__`) is returned/counted.
- Zero modifications to `src/goe/offload/snowflake/`, `microsoft/`, `hadoop/`, `teradata/`, `backend_api.py`, `backend_table.py`. No new abstract methods or capability keys: the native load is implemented inside `BackendBigQueryTable` using existing `BackendBigQueryApi.bq_client()`.
- **`BQ-D1` (RESOLVED)**: the local `goccy/bigquery-emulator` + `fake-gcs-server` integration harness is excluded — the emulator does not implement external tables (`EXTERNAL` mode), `INFORMATION_SCHEMA.PARTITIONS`, `dry_run`, or CMEK/Parquet load fidelity, and GOE will **never code around emulator limitations**. Live verification uses the real GCP BigQuery test environment (`oracle_ci_and_bigquery_test_harness_20261010` `integration-bigquery`) alongside offline unit and golden dry-run suites.
- **`BQ-D2` (RESOLVED)**: unwired additions from revision 1 are removed: the optional `BigQueryStorageWriteStreamer` (no caller, new `google-cloud-bigquery-storage` dependency, Write API cannot carry job labels), `GOEGcs.copy_many_from_local` via `transfer_manager` (no multi-file upload caller), the `dry_run_preview` parameter (no caller), load-dataset `default_table_expiration`, and `BIGQUERY_BILLING_PROJECT` (duplicates `google_cloud_project`).
- **Public-Before-Private Function & Method Ordering**: Every Python module and class created or modified in this flow (`bigquery_backend_api.py`, `bigquery_backend_table.py`, `bigquery_load_job.py`, `goe_gcs.py`, `factory.py`, `query_import.py`, and their unit test modules) keeps all public/dunder functions and methods grouped above private (`_...`) helpers, verified via an AST ordering check.

### Task Breakdown & File Ownership

| Task | Title | Strategy | Priority | Depends On | Files | Tests |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1.1 | Parquet default and `BIGQUERY_LOAD_TABLE_MODE` config | `behavior_tdd` | P1 | — | `src/goe/offload/offload_constants.py`, `src/goe/config/orchestration_defaults.py`, `src/goe/config/orchestration_config.py`, `src/goe/config/config_validation_functions.py`, `templates/conf/offload.env.template.bigquery` | `tests/unit/config/test_bigquery_first_config.py` |
| 1.2 | `BackendBigQueryApi` metadata, lifecycle and job modernization | `regression_tdd` | P1 | — | `src/goe/offload/bigquery/bigquery_backend_api.py`, `src/goe/offload/offload_messages.py` | `tests/unit/offload/bigquery/test_bigquery_api_modernization.py` |
| 1.3 | Native BigQuery load jobs in `BackendBigQueryTable` | `behavior_tdd` | P2 | 1.1, 1.2 | `src/goe/offload/bigquery/bigquery_backend_table.py`, `src/goe/offload/bigquery/bigquery_load_job.py` | `tests/unit/offload/bigquery/test_bigquery_native_load.py` |
| 1.4 | `GOEGcs` precondition uploads and single-pass delete | `characterization` | P2 | — | `src/goe/filesystem/goe_gcs.py` | `tests/unit/filesystem/test_goe_gcs_preconditions.py` |
| 1.5 | GCP AUTO transport order and Query Import modernization | `behavior_tdd` | P2 | — | `src/goe/offload/transport/factory.py`, `src/goe/offload/transport/query_import.py` | `tests/unit/offload/test_gcp_transport_selection.py` |

## Implementation Plan

- [x] 1.1 Default BigQuery staging to Parquet and add validated `BIGQUERY_LOAD_TABLE_MODE` ([tasks/1.1.md](tasks/1.1.md)) (9e38f08)
- [x] 1.2 Replace Legacy SQL partition metadata, delete `__del__`, adopt `query_and_wait`, job labels, `ClientInfo`, session allow-list and dataset CMEK default in `BackendBigQueryApi` ([tasks/1.2.md](tasks/1.2.md)) (19cf122)
- [x] 1.3 Load staged files into native BigQuery load tables with external-table fallback ([tasks/1.3.md](tasks/1.3.md)) (940eb8b)
- [x] 1.4 Use `if_generation_match=0` uploads and single-pass deletes in `GOEGcs` ([tasks/1.4.md](tasks/1.4.md)) (abade1e)
- [x] 1.5 Prioritize GCP transports in `AUTO` and modernize Query Import fetch size and local cleanup ([tasks/1.5.md](tasks/1.5.md)) (8fcb959)

## Verification Commands

```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
uv run pytest tests/unit/config/test_bigquery_first_config.py tests/unit/offload/bigquery/ tests/unit/filesystem/ tests/unit/offload/test_gcp_transport_selection.py -q
uv run pytest tests/unit -q
uv run ruff check src/goe tests/unit
uv run ruff format --check src/goe tests/unit
uv run mypy src/goe
uv run python -c "import ast,sys; is_priv=lambda n:n.startswith('_') and not (n.startswith('__') and n.endswith('__')); bad=[(p,getattr(s,'name','<module>'),f.name) for p in sys.argv[1:] for s in ast.walk(ast.parse(open(p).read())) if isinstance(s,(ast.Module,ast.ClassDef)) for funcs in [[n for n in s.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]] for i,f in enumerate(funcs) if not is_priv(f.name) and any(is_priv(g.name) for g in funcs[:i])]; assert not bad, bad" src/goe/offload/bigquery/bigquery_backend_api.py src/goe/offload/bigquery/bigquery_backend_table.py src/goe/offload/bigquery/bigquery_load_job.py src/goe/filesystem/goe_gcs.py src/goe/offload/transport/factory.py src/goe/offload/transport/query_import.py
```

## Continuity Snapshot

- **State:** `planned`; current task: none.
- **Next exact step:** after `sqlglot_ast_and_predicate_engine_20261010` completes, claim Task `1.1` (`tasks/1.1.md`). Tasks `1.1`, `1.2`, `1.4` and `1.5` have no in-flow dependencies; `1.3` requires `1.1` and `1.2`. Execute sequentially in id order.
- **Plan identity:** `plan_revision: 3`, `plan_commit: null`.
- **Decisions:** `BQ-D1` (resolved — no emulator workarounds; use real GCP BigQuery project + offline unit/golden suites), `BQ-D2` (resolved — removed unwired additions).
- **Knowledge:** `.agents/bundles/knowledge/patterns/index.md`, `.agents/bundles/product/tech-stack.md`, `research/bigquery_first_and_test_harness.md`.
