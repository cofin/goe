---
type: Research
title: DuckDB, duckdb-oracle & community gcs Integration Feasibility for GOE
description: Primary-source capability matrix for cofin/duckdb-oracle, the northpolesec community gcs extension and DuckDB core httpfs, and the resulting scope for an opt-in GOE DUCKDB offload transport.
tags: [research, duckdb, gcs, transport, validation]
created_at: 2026-10-10T15:05:00Z
updated_at: 2026-10-10T18:45:00Z
---

# DuckDB, duckdb-oracle & community `gcs` Integration Feasibility for GOE

## 1. Executive Summary

**Verdict: worth pursuing as an opt-in `DUCKDB` offload transport for Oracle → BigQuery, not as a default or AUTO candidate.** DuckDB runs one `oracle_query` per GOE transport batch (reusing GOE's SCN-pinned split row sources and Oracle-side `TO_CHAR` casts) and writes each batch with `COPY ... TO 'gcss://<bucket>/<prefix>/part-NNNNN.parquet' (FORMAT PARQUET)` through the community `gcs` extension, after which `BackendBigQueryTable.post_transport_tasks` loads the files.

- **Use:** small/medium tables staged as Parquet on GCS, Oracle user/password auth, EZConnect DSN, no LOB/LONG/RAW/XMLTYPE columns.
- **Not useful:** DuckDB cross-engine aggregate validation (`CrossDbValidator` already pushes aggregates to Oracle and BigQuery, `offload_validation.py:506-528`) and a DuckDB dev backend (would re-implement ~4,100 lines of `BackendApiInterface`/`BackendTableInterface`).
- **Hard upstream limits (no setting exists to change them):** 30 s per OCI call, 64 KiB per-value fetch buffer (errors, does not truncate), password-only authentication, no session-init hook, unsigned extension served from a custom repository, DuckDB-version-locked binaries.

## 2. Sources

| Source | Ref | URL |
|---|---|---|
| duckdb-oracle | `main@a601991`, release v0.2.2 (2026-07-22, "Built for DuckDB v1.5.5") | https://github.com/cofin/duckdb-oracle , https://api.github.com/repos/cofin/duckdb-oracle/releases |
| DuckDB community registry | no `extensions/oracle`; `extensions/gcs/description.yml` v0.0.8 (ref `84082773`) | https://github.com/duckdb/community-extensions , https://duckdb.org/community_extensions/extensions/gcs.html |
| duckdb-gcs | `main@60c5eb9` | https://github.com/northpolesec/duckdb-gcs |
| DuckDB GCS guide / S3 API | current docs | https://duckdb.org/docs/current/guides/network_cloud_storage/gcs_import.html , https://duckdb.org/docs/current/core_extensions/httpfs/s3api.html |
| DuckDB PyPI | latest `1.5.6`; GOE lock `1.5.5` (`uv.lock:886-887`, transitive via `sqlspec[duckdb]`, `pyproject.toml:35`) | https://pypi.org/pypi/duckdb/json |
| Local probe | DuckDB 1.5.5 in `.venv`: `duckdb.connect(config={threads, memory_limit, allow_unsigned_extensions})` accepted; `COPY ... TO ... (FORMAT PARQUET)` returns `[(row_count,)]`; `ATTACH ? ...` is a parser error; `import duckdb` costs ~75 ms | `uv run python` session 2026-10-10 |

## 3. duckdb-oracle Capability Matrix

| Capability | Finding | Evidence |
|---|---|---|
| Distribution | Not a community extension. Unsigned: requires `allow_unsigned_extensions`; install with `SET custom_extension_repository = 'https://cofin.github.io/duckdb-oracle'; INSTALL oracle; LOAD oracle;` (equivalently `INSTALL oracle FROM '<repo>'`). Release assets for linux_amd64/arm64, osx_arm64, windows_amd64 plus `SHA256SUMS.txt`. | README; releases API |
| DuckDB version | v0.2.2 targets DuckDB 1.5.5 only; no 1.5.6 build published. | releases API |
| Runtime | OCI client (`OCIEnvCreate(OCI_THREADED)`); Instant Client location/linkage not verified. | `src/oracle_connection_manager.cpp` |
| Table functions | `oracle_query(conn_ref, sql)`, `oracle_scan(conn_ref, schema, table)`, scalar `oracle_execute(conn_ref, sql)`. `conn_ref` is an **ATTACH alias** or a literal `user/password@connect_identifier`; bare secret names are rejected. | `src/oracle_functions.cpp`, `src/oracle_connection_resolver.cpp` |
| Secrets / ATTACH | `CREATE SECRET (TYPE oracle, HOST, PORT, SERVICE \| DATABASE, USER, PASSWORD, WALLET_PATH)` (no DSN/connection-string key; PASSWORD redacted), converted to EZConnect. `ATTACH '' AS ora (TYPE oracle, SECRET name)`; attachments are forced `READ_ONLY`. | `src/oracle_secret.cpp`, `src/storage/oracle_storage_extension.cpp` |
| Settings (complete) | `oracle_enable_pushdown`, `oracle_prefetch_rows`, `oracle_prefetch_memory`, `oracle_array_size`, `oracle_connection_cache`, `oracle_connection_limit` (default 8), `oracle_debug_show_queries`, `oracle_lazy_schema_loading`, `oracle_metadata_object_types`, `oracle_metadata_result_limit`, `oracle_use_current_schema`, `oracle_enable_spatial_types`. **No** `oracle_call_timeout_ms`, `oracle_session_init_sql`, LOB or time-zone settings. | `src/oracle_settings.cpp` |
| SQL passthrough & SCN | `oracle_query` prepares the SQL verbatim (`OCI_NTV_SYNTAX`), so `AS OF SCN <n>`, hints and `PARTITION (...)` pass through. A literal SCN is required (no bind support). Type rewrites wrap the text as `SELECT <cols> FROM (<sql>)`, preserving the inner SCN clause. | `src/oracle_scan.cpp` |
| Parallelism | One cursor per `oracle_query`; parallelism comes from issuing one query per GOE batch. Connections come from a process-wide pool keyed by connection string (limit `oracle_connection_limit`). | `src/oracle_scan.cpp`, `src/oracle_connection_manager.cpp` |
| Timeouts | Hard-coded 30 000 ms `OCI_ATTR_CALL_TIMEOUT` per statement/service context; 10 000 ms connect. | `src/oracle_scan.cpp`, `src/oracle_connection_manager.cpp` |
| Fetch buffers | Values fetched as `SQLT_STR` (BLOB as `SQLT_BIN`), buffer `max(4000, char_size*4)` capped at 65 535 bytes; overflow raises `IOException`. RAW-as-text conversion not verified. | `src/oracle_scan.cpp` |
| Auth | `OCISessionBegin(..., OCI_CRED_RDBMS, ...)` only; `WALLET_PATH` only sets `TNS_ADMIN` (TLS/tnsnames), not SEPS/external auth. | `src/oracle_connection_manager.cpp` |
| Session | After login runs only `ALTER SESSION SET NLS_DATE_FORMAT='YYYY-MM-DD HH24:MI:SS' NLS_TIMESTAMP_FORMAT='YYYY-MM-DD HH24:MI:SS.FF'`; no TIME_ZONE; session time zone follows the client `ORA_SDTZ` environment variable. | `src/oracle_connection_manager.cpp` |

## 4. GCS Write Path

| Path | ADC | Notes | Evidence |
|---|---|---|---|
| Core `httpfs` (`gs://`, `gcs://`) | No — S3-compatible XML API with HMAC `CREATE SECRET (TYPE gcs, KEY_ID, SECRET)`. Autoloads for `gs://` paths (`autoload_known_extensions=true`). | Not used. | DuckDB GCS guide, S3 API page |
| Community `gcs` (`INSTALL gcs FROM community`, signed, MIT, v0.0.8) | Yes. Secrets: `(TYPE gcp, PROVIDER credential_chain [, PROJECT_ID])`, `(TYPE gcp, PROVIDER service_account, SERVICE_ACCOUNT_KEY_PATH ...)`, `(TYPE gcp, PROVIDER access_token, ACCESS_TOKEN '...' [, PROJECT_ID])`. | Handles `gs://`, `gcs://`, `gcss://`; use `gcss://` so httpfs never claims the path. `COPY ... TO` uses resumable `WriteObject`. Settings: `gcs_enable_metadata_cache`, `gcs_metadata_cache_ttl`, `gcs_list_cache_ttl`, `gcs_max_*_cache_entries`, `gcs_transfer_concurrency` (read-side range concurrency). The storage client is cached in `client_context->registered_state` per connection and bucket. | duckdb-gcs README, `src/gcs_extension.cpp`, `src/gcs_secret.cpp`, `src/gcs_filesystem.cpp` |
| GOE `GOEGcs.copy_from_local` | Yes | Local file + Python upload; unnecessary for DuckDB because BigQuery staging is always `gs://`. | `src/goe/filesystem/goe_gcs.py:97-111` |

GOE credential policy (PRD 1, `gcp_adc_credential_unification_20261010`) requires every GCP client to obtain credentials from `goe.util.gcp_credentials.resolve_gcp_credentials`. The DuckDB transport therefore mints one OAuth2 access token from that bundle (scope `https://www.googleapis.com/auth/devstorage.read_write`) and provisions `PROVIDER access_token` secrets, which works identically for user ADC, service accounts, Workload Identity Federation and `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`. Each batch uses a fresh DuckDB connection, so the per-connection client cache always sees the current token.

## 5. GOE Integration Points (baseline `46890a8`; PRD 2 moves transport code to `src/goe/offload/transport/`)

| Concern | Anchor |
|---|---|
| Method constants / rule sets | `offload_transport.py:95-145` → `src/goe/offload/transport/constants.py`; `OFFLOAD_TRANSPORT_AUTO/GOE/GCP/SQOOP` in `offload_constants.py:101-104` |
| Validation & selection | `get_offload_transport_method_validation_fns` (`L491-524`), `validate_offload_transport_method` (`L527-550`), `choose_offload_transport_method` (`L553-598`) → `src/goe/offload/transport/factory.py` |
| Factory | `offload_transport_factory.py:19-200` → `src/goe/offload/transport/factory.py` |
| Base transport | `OffloadTransport.__init__(offload_source_table, offload_target_table, offload_operation, offload_options, messages, dfs_client)` (`L639-732`), SCN fixed at `L662-665`, `_rdbms_action` attribute (`L732`) |
| Splits / projection | `_get_transport_split_type` (`L1061-1080`), `_get_transport_row_source_query` (`L995-1023`), `_build_offload_query_lists` → `(colexpressions, colnames)` (`L1082-1119`), `_sql_projection_from_offload_query_expression_list` (`L1121-1136`), Spark id-range helper `_get_id_range` (`L1318-1332`) |
| Oracle SQL | `get_transport_split_type` (`oracle_offload_transport_rdbms_api.py:477-559`), `get_snapshot_clause` (`L561-570`), `get_transport_row_source_query` (`L572-731`, tags rows with `goe_offload_batch`), `get_rdbms_session_setup_hint` (`L446-475`), `get_rdbms_query_cast` (`L320-379`) |
| Staging contract | `parquet_staging_file.py::_from_canonical_column_to_parquet` (`L101-182`): STRING, INT32, INT64, FLOAT, DOUBLE, BINARY, BOOLEAN |
| BigQuery load | `BackendBigQueryTable.post_transport_tasks` (`bigquery_backend_table.py:512-514`), `part*` wildcard (`L128`) |

## 6. Scope for the GOE Chapter

- **R1 Registration:** `OFFLOAD_TRANSPORT_METHOD_DUCKDB = "DUCKDB"` and `OFFLOAD_TRANSPORT_DUCKDB = "DUCKDB"`; selectable only via `--offload-transport-method=DUCKDB` or `OFFLOAD_TRANSPORT=DUCKDB`.
- **R2 Availability gate:** BigQuery target, `gs` filesystem, Parquet staging, DuckDB version equals `OFFLOAD_TRANSPORT_DUCKDB_VERSION`, no Oracle wallet auth, EZConnect `host[:port]/service` DSN, table size `<= OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES`, no CLOB/NCLOB/BLOB/LONG/LONG RAW/RAW/XMLTYPE columns.
- **R3 Configuration:** `OFFLOAD_TRANSPORT_DUCKDB_{VERSION, EXTENSION_PATH, EXTENSION_DIR, EXTENSION_REPOSITORY, THREADS, MEMORY_LIMIT, TEMP_DIRECTORY, MAX_BYTES}`.
- **R4 Transport:** one `oracle_query` per batch via an ATTACH alias backed by a temporary oracle secret; `COPY` to `gcss://` with `access_token` secret; fresh connection per batch; extension load failure raises before any write.
- **R5 SCN:** every batch SQL contains `AS OF SCN <snapshot>` when consistent read is enabled.
- **R6 Time zone:** `ORA_SDTZ=UTC` before the first ATTACH (process-global; matches GOE's transport `TIME_ZONE='UTC'`).
- **R7 Secrets:** passwords and tokens are never logged; secrets are `TEMPORARY`.
- **R8 Tests:** unit tests for all split types, SCN enforcement, cast projection, URI conversion, secret SQL redaction, availability rejections, dry-run and cleanup.
