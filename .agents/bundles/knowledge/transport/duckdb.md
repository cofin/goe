---
type: Reference
title: DuckDB & duckdb-oracle Offload Transport
description: Opt-in zero-JVM DuckDB transport engine using cofin/duckdb-oracle and community gcs extension for Oracle-to-BigQuery Parquet offloads
tags:
  - reference
  - transport
  - duckdb
  - oracle
  - gcs
  - parquet
  - opentelemetry
---

# DuckDB & `duckdb-oracle` Offload Transport

`OffloadTransportDuckDB` (`src/goe/offload/transport/duckdb_*.py`) is an opt-in, zero-JVM local offload transport engine (`--offload-transport-method=DUCKDB` / `OFFLOAD_TRANSPORT=DUCKDB`) that streams Oracle rows directly to Google Cloud Storage (`gcss://`) as Snappy-compressed Parquet files using `duckdb==1.5.5`, `cofin/duckdb-oracle` (`oracle_query`), and the DuckDB community `gcs` extension (`northpolesec/duckdb-gcs`).

## Key Modules

- **`duckdb_constants.py` (`src/goe/offload/transport/duckdb_constants.py`)**: Defines `OFFLOAD_TRANSPORT_DUCKDB_SUPPORTED_VERSION_PREFIX = "1.5.5"`, `DUCKDB_GCS_URI_SCHEME = "gcss"`, `DUCKDB_ORACLE_ATTACH_ALIAS = "goe_ora"`, `DUCKDB_GCS_TOKEN_REFRESH_MARGIN_SECONDS = 600`, and default extension repository URLs.
- **`duckdb_availability.py` (`src/goe/offload/transport/duckdb_availability.py`)**: Pure-local readiness gate `is_duckdb_available()` checking `BACKEND_DISTRO_GCP`, `DBTYPE_ORACLE`, `FILE_STORAGE_FORMAT_PARQUET`, `OFFLOAD_FS_SCHEME_GS`, `not use_oracle_wallet`, `duckdb.__version__` prefix `"1.5.5"`, `max_offload_chunk_size <= offload_transport_duckdb_max_bytes`, and unsigned extension opt-in before attempting any network or database connection.
- **`duckdb_engine.py` (`src/goe/offload/transport/duckdb_engine.py`)**: Extension loading (`configure_duckdb_for_offload`), EasyConnect/TNS DSN parsing (`parse_oracle_dsn`), Oracle secret + `ATTACH` wiring (`attach_oracle_database`), dual-mode GCS secret configuration (`configure_duckdb_gcs_secret`, `refresh_duckdb_gcs_secret_if_expiring`), URI conversion (`gs_to_gcss_uri`), and `verify_batch_scn_invariant`.
- **`duckdb_transport.py` (`src/goe/offload/transport/duckdb_transport.py`)**: `OffloadTransportDuckDB` subclassing `OffloadTransport` and `OffloadTransportRdbms` to execute single or parallel (`ThreadPoolExecutor`) batch extractions into `gcss://` Parquet files and verify staged outputs.

## Strict Opt-In & Safety Gates

1. **Explicit Opt-In Only (`DUCK-D1`)**: `OFFLOAD_TRANSPORT_METHOD_DUCKDB = "DUCKDB"` is never included in `AUTO_TRANSPORT_METHODS` or `GCP_AUTO_TRANSPORT_METHODS`; operators must explicitly pass `--offload-transport-method=DUCKDB` or set `OFFLOAD_TRANSPORT=DUCKDB`.
2. **Version Pin & Runtime Check (`DUCK-D2`)**: `cofin/duckdb-oracle` v0.2.2 targets `duckdb==1.5.5`. Both `uv.lock` and the runtime prefix check (`duckdb.__version__.startswith("1.5.5")`) enforce this version.
3. **Unsigned Extension Policy (`DUCK-D3`)**:
   - When `OFFLOAD_TRANSPORT_DUCKDB_ORACLE_EXTENSION_PATH` points to an existing local `.duckdb_extension` binary, DuckDB loads it directly.
   - When installing `oracle` from `OFFLOAD_TRANSPORT_DUCKDB_ORACLE_REPOSITORY` without a local binary path, `OFFLOAD_TRANSPORT_DUCKDB_ALLOW_UNSIGNED_EXTENSIONS=true` is required (`duckdb.connect(":memory:", config={"allow_unsigned_extensions": "true"})`).
4. **Byte-Ceiling Guard**: `OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES` defaults to `100G` (`100 * 1024**3` bytes).

## Oracle & GCS Secret Wiring (`duckdb_engine.py`)

- **Oracle `ATTACH` via Temporary Secret**:
  ```sql
  CREATE OR REPLACE TEMPORARY SECRET goe_oracle_secret (
    TYPE oracle, HOST ?, PORT ?, SERVICE_NAME ?, USER ?, PASSWORD ?
  );
  ATTACH '' AS goe_ora (TYPE oracle, SECRET goe_oracle_secret);
  ```
- **Dual-Mode Keyless GCS Authentication**:
  - **Attached Service Account / Compute Engine Metadata (`credential_chain`)**:
    ```sql
    CREATE OR REPLACE SECRET goe_gcs_secret (
      TYPE gcs, PROVIDER credential_chain, PROJECT_ID ?
    );
    ```
  - **Developer `authorized_user` ADC or `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` (`access_token`)**:
    Refreshes the `google.auth` credential bundle (`resolve_gcp_credentials(config, component="duckdb_gcs")`) when missing or within 600s of expiry (`refresh_duckdb_gcs_secret_if_expiring`), then registers:
    ```sql
    CREATE OR REPLACE SECRET goe_gcs_secret (
      TYPE gcs, PROVIDER access_token, ACCESS_TOKEN ?
    );
    ```
  - **URI Scheme**: Converts `gs://bucket/path` to `gcss://bucket/path` so the community `gcs` extension handles native multipart streaming writes instead of DuckDB's built-in HTTPFS S3 compatibility layer.

## Snapshot Invariant & Per-Batch Telemetry

- **Mandatory `AS OF SCN` Verification (`verify_batch_scn_invariant`)**: Because each parallel worker thread opens an independent Oracle session via `ATTACH '' AS goe_ora`, `OffloadTransportDuckDB._run_batch()` calls `verify_batch_scn_invariant(query, self._scn)` *before* opening a DuckDB connection, raising `OffloadTransportException` if `AS OF SCN <scn>` is absent from the batch SQL.
- **Parallel Execution & OpenTelemetry Spans**:
  - Single-batch runs execute inline; multi-batch runs (`degree_of_parallelism > 1`) dispatch `_run_batch` across `ThreadPoolExecutor(max_workers=self._dop)` via `submit_with_context()` (`src/goe/observability/context.py`) so the active OpenTelemetry span context, W3C baggage, and SQLSpec `CorrelationContext` propagate to every worker thread.
  - Each `_run_batch` is wrapped in `traced_duckdb_batch(batch_index=..., staging_uri=..., scn=...)` (`src/goe/observability/transport.py`), emitting a `SpanKind.CLIENT` span `goe.transport.duckdb.batch` with `db.system="oracle"`, `goe.transport.batch_index`, `goe.transport.staging_uri`, `goe.transport.scn`, and `goe.transport.rows`.
