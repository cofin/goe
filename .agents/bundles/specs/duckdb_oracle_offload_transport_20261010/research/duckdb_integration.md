---
type: Research
title: DuckDB & duckdb-oracle Integration Feasibility for GOE
description: Evaluates whether DuckDB with the cofin/duckdb-oracle, duckdb-gcs, and duckdb-bigquery extensions should become a GOE offload transport, validation engine, or dev backend, and defines the scope for a gated Flow chapter.
tags: [research, duckdb, gcs, transport, validation]
created_at: 2026-10-10T15:05:00Z
---

# DuckDB & duckdb-oracle Integration Feasibility for GOE

## 1. Executive Summary

**Verdict: worth pursuing for an opt-in `DUCKDB` offload transport combining `cofin/duckdb-oracle` and `northpolesec/duckdb-gcs` (`INSTALL gcs FROM community`), gated on upstream `duckdb-oracle` fixes.** That transport replaces the Python row-by-row encoder used by Query Import for small and medium tables. It runs Oracle queries through `oracle_query`, executes a DuckDB `COPY ... TO 'gcss://<bucket>/<staging_prefix>/part-0000N.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)` streaming directly from DuckDB's C++ worker threads (`google-cloud-cpp`) to GCS via the community `gcs` extension, and then triggers the BigQuery load and `INSERT … SELECT` pipeline.

- **(a) DuckDB + `duckdb-oracle` + `duckdb-gcs` transport: high value (gated).** GOE already depends on `duckdb==1.5.5` transitively ([pyproject.toml:35](../../../../pyproject.toml), `uv.lock:886-887`). That is the exact DuckDB version `duckdb-oracle` v0.2.2 and `duckdb-gcs` v0.0.8 target. GOE's Parquet staging contract is mostly string-encoded, and those strings are produced by Oracle-side `TO_CHAR` expressions that GOE already generates. Four `duckdb-oracle` gaps must be gated before production use on affected workloads:
  1. A hard-coded 30 s per-call OCI timeout (`U1`).
  2. No external (SEPS wallet) authentication (`U3`).
  3. Per-value read buffers capped at 64 KiB, which breaks LOBs (`U4`).
  4. Distribution: the extension is unsigned, served from a custom repository, and needs Oracle Instant Client (`U5`).
- **(b) Cross-engine aggregate validation: not useful.** `CrossDbValidator` already pushes aggregates down to Oracle and BigQuery in parallel, using native drivers ([offload_validation.py:506-528](../../../../src/goe/offload/offload_validation.py)). Adding DuckDB would add a third engine and gain nothing. It would also break on the 30 s timeout and on NUMBER aggregates that map to DOUBLE.
- **(c) Local dev/test backend: not useful.** A DuckDB GOE backend would mean re-implementing `BackendApiInterface` and `BackendTableInterface`: about 4,100 lines of base code plus about 2,800 lines for the BigQuery implementation. `duckdb-bigquery` is a client for real BigQuery, not an emulator.
- **(d) Direct DuckDB-to-GCS streaming writes via the community `gcs` extension (`northpolesec/duckdb-gcs`): mandatory for GCS staging.** Core `httpfs` claims `gs://` and `gcs://` and only supports S3 XML HMAC keys or a static bearer token (no ADC). The community `gcs` extension (`INSTALL gcs FROM community`, powered by `google-cloud-cpp` native C++ storage threads) registers the **`gcss://`** URI scheme and streams Parquet multipart writes directly from DuckDB's C++ worker threads without serializing under the Python GIL or staging to local disk first. Local `temp_directory` + `_dfs_client.copy_from_local` is retained strictly as a fallback for non-GCS staging backends.

## 2. Sources and Snapshot

| Source | Ref inspected | URL |
|---|---|---|
| duckdb-oracle | `a60199171a546064a632cbc879ffe2c75f574fe5` (2026-07-22), ext v0.2.2 | https://github.com/cofin/duckdb-oracle |
| duckdb-gcs | `60c5eb9d6ab72df41dfc2f064773e257a9ff106f` (2026-09-01); community registry pins v0.0.8 @ `84082773` | https://github.com/northpolesec/duckdb-gcs |
| duckdb-bigquery | `1568f8e93fd40f58fb39d37a016a422e0260aebb` (2026-10-04), v0.12.0 + unreleased | https://github.com/hafenkran/duckdb-bigquery |
| duckdb-httpfs | `23b865d8350660a0ca4f18884634acae17b8dc09` (2026-10-08) | https://github.com/duckdb/duckdb-httpfs |
| DuckDB GCS guide | current docs | https://duckdb.org/docs/current/guides/network_cloud_storage/gcs_import.html |
| DuckDB PyPI | `duckdb` 1.5.6 (latest at research time) | https://pypi.org/pypi/duckdb/json |
| Community registry | `extensions/gcs/description.yml` present; `extensions/oracle/description.yml` → HTTP 404 | https://github.com/duckdb/community-extensions |

## 3. duckdb-oracle Capability Matrix

File paths are relative to the repository root at the commit above.

| Capability | Finding | Evidence |
|---|---|---|
| Install / distribution | **Unsigned.** Must set `allow_unsigned_extensions` (`-unsigned` in the CLI). Installed from the custom repo `SET custom_extension_repository='https://cofin.github.io/duckdb-oracle'; INSTALL oracle;`. **Not** in the DuckDB community registry. | README "Quick Start"; `.github/workflows/release-unsigned.yml` (gh-pages deploy); community registry 404 for `extensions/oracle/description.yml` |
| Supported DuckDB | Only **v1.5.5**, for ext v0.2.2. History: v1.4.1, 1.4.3, 1.5.1, 1.5.4, 1.5.5. Extension binaries are DuckDB-version-specific, so upgrades must move in lockstep. | `docs/COMPATIBILITY.md`; `.github/workflows/main-distribution-pipeline.yml:19` (`duckdb_version: v1.5.5`) |
| Platforms | linux_amd64, linux_arm64, osx_arm64, windows_amd64. Excludes wasm, osx_amd64, and musl. | `description.yml` (`excluded_platforms`); `main-distribution-pipeline.yml:22` |
| Client library | **OCI thick client.** Needs Oracle Instant Client at runtime (and Basic + SDK to build). | README "Development"; `description.yml` "Requires Oracle Instant Client runtime"; `scripts/setup_oci_linux.sh` |
| Auth | User and password only: `OCISessionBegin(..., OCI_CRED_RDBMS, ...)`. `WALLET_PATH` just sets `TNS_ADMIN` under a process-global mutex, for TNS aliases and mTLS. **No external/SEPS auth** (`OCI_CRED_EXT`) and no Kerberos. | `src/oracle_connection_manager.cpp` (CreateConnection, ~L270-L310; `ScopedTnsAdmin` L11-L36); `src/oracle_secret.cpp:67-80` |
| Connection mgmt | Process-wide `OracleConnectionManager` with `OCI_THREADED` and a cache (`oracle_connection_limit` default 8). OCI statement cache is **disabled** (`stmt_cache_size = 0`). | `CHANGELOG.md` [1.0.0]; `description.yml` settings; `oracle_connection_manager.cpp` (~L324-L327) |
| **Call timeout** | **Hard-coded**: 10 s server-handle call/connect timeout before attach, then **30 s `OCI_ATTR_CALL_TIMEOUT`** on the service context and on every scan statement. There is no setting to change it. Oracle defines this attribute as a per-round-trip limit, so any single execute or fetch that takes longer than 30 s fails. | `oracle_connection_manager.cpp` (~L277-L284, ~L329-L332); `src/oracle_scan.cpp:84-88`, `:304-307` |
| Session NLS | Sets only `NLS_DATE_FORMAT='YYYY-MM-DD HH24:MI:SS'` and `NLS_TIMESTAMP_FORMAT='YYYY-MM-DD HH24:MI:SS.FF'`. Does **not** set `NLS_TIMESTAMP_TZ_FORMAT` or `TIME_ZONE`. There is no user-supplied session-init hook. | `oracle_connection_manager.cpp` (~L312-L322) |
| Projection pushdown | Yes (`projection_pushdown = true`). | `src/storage/oracle_table_entry.cpp:237-243`; `src/oracle_functions.cpp:160-174` |
| Filter pushdown | Yes, via `pushdown_complex_filter` (`=`, ranges, BETWEEN, IS NULL, IN, LIKE), toggled by `oracle_enable_pushdown`. `filter_pushdown = false`, so DuckDB still applies the filter client-side as well. | `src/oracle_pushdown.cpp:184-431`; `oracle_table_entry.cpp:238-241` |
| Raw SQL passthrough | `oracle_query(conn, sql)` sends trusted Oracle SQL verbatim. GOE can embed `AS OF SCN`, hints, `PARTITION (...)`, and ROWID-range predicates. `oracle_execute` runs DDL/DML. | `description.yml` functions; README "Secrets" note |
| **Parallel scan** | **None.** The scan registers only a global init (`OracleInitGlobal`, local init `nullptr`), with no `MaxThreads` and no partition or ROWID splitting. One OCI cursor per scan. Partition metadata is read but used only by `oracle_debug_partition_metadata`. | `oracle_functions.cpp:162-170`; `oracle_table_entry.cpp:237`; `src/oracle_scan.cpp:268-402`; `src/storage/oracle_catalog.cpp:339-390` |
| **SCN / flashback** | **No native support.** There are no `AS OF SCN` or SCN references in `src/`. It works only by putting the clause inside `oracle_query` SQL. | grep `scn\|flashback\|AS OF` over `src/` returns only unrelated `serialize` hits |
| Fetch path | Every column is defined as `SQLT_STR`, or `SQLT_BIN` for BLOB, then parsed client-side. Array fetch is used (`oracle_array_size` 256, `oracle_prefetch_rows` 1024). | `oracle_scan.cpp:339-395`; `src/oracle_type_conversion.cpp:158-205` |
| **Per-value buffer cap** | The buffer is `max(4000, oci_size*4)`, **capped at 65,535 bytes** (`ub2` max). This bounds LOB and long values on the read path. | `oracle_scan.cpp:341-350` |

## 4. Direct DuckDB → GCS Streaming with the Community `gcs` Extension (`northpolesec/duckdb-gcs`)

| Path | ADC? | Direct C++ Write? | Evidence |
|---|---|---|---|
| Core `httpfs` (`gs://`, `gcs://`, S3 XML interop API) | **No.** Requires S3 HMAC `KEY_ID`/`SECRET` or static `bearer_token` with no refresh. Fails with ADC. | Yes (S3 multipart) | `duckdb-httpfs/src/s3/s3_provider.cpp:240, 317, 345-347, 366, 453-458` |
| Community `gcs` (`northpolesec/duckdb-gcs`, `INSTALL gcs FROM community`) | **Yes.** Supports `PROVIDER credential_chain` (calls `google::cloud::MakeGoogleDefaultCredentials()`) and `PROVIDER access_token`. | **Yes (`gcss://`).** `COPY … TO 'gcss://<bucket>/<prefix>/part-0000N.parquet'` streams directly from DuckDB C++ worker threads via `google-cloud-cpp` without GIL serialization or local disk staging. | `duckdb-gcs/src/gcs_secret.cpp:14,31-42`; `src/gcs_filesystem.cpp:770-793`; community `description.yml` v0.0.8 |
| GOE's Python uploader (`GOEGcs.copy_from_local`) | **Yes.** `google.cloud.storage.Client()` uses ADC. | No (local disk stage + Python upload) | [goe_gcs.py:68](../../../../src/goe/filesystem/goe_gcs.py), `:97` (retained as fallback for non-GCS staging backends) |

### Production Architecture for GOE's Native `gcs` Extension Integration

1. **Extension Loading (`LOAD gcs` first, locked `INSTALL gcs FROM community` fallback):**
   - Attempt `connection.execute("LOAD gcs")` first, which incurs zero network calls when pre-seeded in `OFFLOAD_TRANSPORT_DUCKDB_EXTENSION_DIR` or `~/.duckdb/extensions`.
   - If `LOAD gcs` raises, acquire a process-wide thread lock (`_gcs_setup_lock`) and execute `connection.execute("INSTALL gcs FROM community")` followed by `connection.execute("LOAD gcs")`.
2. **Performance Pragmas:**
   ```sql
   SET gcs_enable_metadata_cache = true;
   SET gcs_metadata_cache_ttl = 3600;
   SET gcs_list_cache_ttl = 3600;
   SET gcs_transfer_concurrency = <threads>;
   ```
3. **`gcss://` URI Scheme Conversion (`to_duckdb_gcs_uri`):**
   - Because built-in `httpfs` claims `gs://` and `gcs://`, the community `gcs` extension registers the **`gcss://`** scheme.
   - Convert `gs://<bucket>/<prefix>/part-{i:05d}.parquet` (and `gcs://...`) to `gcss://<bucket>/<prefix>/part-{i:05d}.parquet` when executing DuckDB `COPY (...) TO 'gcss://...' (FORMAT PARQUET, COMPRESSION SNAPPY)`.
   - Retain local `temp_directory` + `_dfs_client.copy_from_local` only as a fallback for non-GCS staging backends (`OFFLOAD_FS_SCHEME != "gs"`).
4. **Dual-Mode ADC Secret Provisioning (`PROVIDER credential_chain` vs `PROVIDER access_token`):**
   - Resolve credentials via `resolve_gcp_credentials(config)` (`src/goe/util/gcp_credentials.py`).
   - **Mode 1 — GCP Compute / Direct Service Account (`GCECredentials`, Cloud Run `K_SERVICE`/`K_REVISION`, or `ServiceAccountCredentials` without impersonation):**
     - Check `SELECT count(*) FROM duckdb_secrets() WHERE name = 'goe_gcs'` first; if already `> 0`, skip re-executing DDL to prevent optimistic catalog write-write conflicts.
     - Otherwise execute:
       ```sql
       CREATE OR REPLACE SECRET goe_gcs (TYPE gcp, PROVIDER credential_chain, PROJECT_ID ?)
       ```
       Always pass `PROJECT_ID` when known (without `PROJECT_ID`, `google-cloud-cpp` fails to resolve billing/quotas and raises `IO Error`).
   - **Mode 2 — Developer Workstation User ADC (`authorized_user`) or Impersonated Service Account (`impersonated_credentials.Credentials` / `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`):**
     - Because `google-cloud-cpp` `credential_chain` does not support `authorized_user` or Python-side impersonation, mint/refresh an OAuth2 access token scoped to `https://www.googleapis.com/auth/devstorage.read_write` (refreshing whenever `expiry` is `None` or within a 10-minute / 600-second margin) and execute:
       ```sql
       CREATE OR REPLACE SECRET goe_gcs (TYPE gcp, PROVIDER access_token, ACCESS_TOKEN ?)
       ```
   - **`registered_state` C++ Client Caching Invariant:**
     - `northpolesec/duckdb-gcs` caches `google::cloud::storage::Client` in `client_context->registered_state` per DuckDB connection and checks `registered_state` before `SecretManager`, so `CREATE OR REPLACE SECRET` on an existing connection does not refresh its cached C++ storage client.
     - `OffloadTransportDuckDB` therefore opens a fresh DuckDB connection per offload execution / batch worker and recycles connections if a multi-batch run approaches the 10-minute token expiry margin.

## 5. GOE Integration Points

| Concern | Anchor | Relevance |
|---|---|---|
| Transport method constants and selection | [offload_transport.py:95-145](../../../../src/goe/offload/offload_transport.py) (`OFFLOAD_TRANSPORT_METHOD_*`, `OFFLOAD_TRANSPORT_GOE_METHODS`); `::get_offload_transport_method_validation_fns` (L491-524); `::choose_offload_transport_method` (L553-598) | A new `OFFLOAD_TRANSPORT_METHOD_DUCKDB` plus an `is_duckdb_available()` validator plugs in here. |
| Factory | [offload_transport_factory.py:29](../../../../src/goe/offload/factory/offload_transport_factory.py) | Add a branch for the new class. |
| Base transport state | `offload_transport.py::OffloadTransport.__init__` (L639-720). The transport SCN is fixed at L662-665 (`offload_transport_snapshot` or `get_current_scn()`). | Every DuckDB batch must reuse `self._offload_transport_snapshot`. |
| Split planning (reuse) | `::OffloadTransport._get_transport_split_type` (L1061-1080); `::_get_transport_row_source_query` (L995-1023) | Produces partition, subpartition, extent (`offload.offload_rowid_ranges`), MOD(ORA_HASH), or id-range UNION ALL row sources, each tagged `goe_offload_batch`. |
| Oracle split/SCN SQL | [oracle_offload_transport_rdbms_api.py::get_transport_split_type](../../../../src/goe/offload/oracle/oracle_offload_transport_rdbms_api.py) (L477-559); `::get_snapshot_clause` (L561-570); `::get_transport_row_source_query` (L572-731) | `AS OF SCN` goes into every branch when consistent read is on, so `oracle_query` passthrough keeps SCN consistency. |
| Projection and casts (reuse) | `offload_transport.py::_build_offload_query_lists` (L1082-1119); `oracle_offload_transport_rdbms_api.py::get_rdbms_query_cast` (L320-379) | With `convert_expressions_on_rdbms_side=True`, DATE, TIMESTAMP, and string-staged NUMBER all become Oracle-side `TO_CHAR`. TZ uses `TO_CHAR(... TZH:TZM)` and INTERVAL uses `TO_CHAR`, so the extension's type mapping is bypassed. |
| Staging contract | [parquet_staging_file.py::_from_canonical_column_to_parquet](../../../../src/goe/offload/staging/parquet/parquet_staging_file.py) (L101-182) | Parquet column types: STRING for DATE, TIMESTAMP, TZ, DECIMAL, INTEGER_38, and intervals; INT32/INT64/FLOAT/DOUBLE only for safe mappings; BINARY or base64 STRING; BOOLEAN. DuckDB must cast to exactly these types. |
| BigQuery load | [bigquery_backend_table.py::_create_load_table](../../../../src/goe/offload/bigquery/bigquery_backend_table.py) (L105-135); `::post_transport_tasks` (L512-514); `::load_final_table` (L456-473) | Unchanged. DuckDB output files are named `part-*.parquet` on GCS (`gs://` / `gcss://`). |

## 6. Recommended Scope for the GOE Flow Chapter

### Phase 0: Upstream gate (in `cofin/duckdb-oracle`; gated dynamically at runtime by GOE)

- **U1.** Add the setting `oracle_call_timeout_ms` (UBIGINT, default 30000; `0` disables).
- **U2.** Add the setting `oracle_session_init_sql` (VARCHAR, `;`-separated).
- **U3.** Add an external-auth secret mode (`EXTERNAL true` → `OCI_CRED_EXT`, no USER/PASSWORD) for SEPS wallets.
- **U4.** Support reading LOB values larger than 64 KiB, through piecewise or LOB-locator fetch.
- **U5.** Correct `LICENSE` to match `description.yml` (Apache-2.0) and publish release checksums.

### Phase 1: GOE transport (requirements)

- **R1. Method registration:** Register `OFFLOAD_TRANSPORT_METHOD_DUCKDB = "DUCKDB"` (opt-in only, excluded from `AUTO`).
- **R2. Availability gate (`is_duckdb_available`):** Validates `PARQUET` staging format, `DBTYPE_BIGQUERY` target, DuckDB version match (`1.5.5`), `offload_transport_duckdb_max_bytes`, U3 wallet gate, U4 LOB gate, and `LOAD oracle` + `LOAD gcs` probes.
- **R3. Configuration:** Add `OFFLOAD_TRANSPORT_DUCKDB_*` options (`VERSION`, `EXTENSION_PATH`, `EXTENSION_DIR`, `EXTENSION_REPOSITORY`, `THREADS`, `MEMORY_LIMIT`, `TEMP_DIRECTORY`, `MAX_BYTES`, `CALL_TIMEOUT_MS`).
- **R4. Class `OffloadTransportDuckDB(OffloadTransport)`:** Streams Oracle split batches in parallel directly to `gcss://<bucket>/<staging_prefix>/part-{i:05d}.parquet` using `northpolesec/duckdb-gcs` (`LOAD gcs`, performance pragmas, and dual-mode `goe_gcs` ADC secret provisioning), with local file + `_dfs_client.copy_from_local` fallback only for non-GCS staging schemes.
- **R5. SCN invariant:** Every batch query must contain `AS OF SCN {self._offload_transport_snapshot}` when `offload_transport_consistent_read=True`.
- **R6. Time zone invariant:** Set `os.environ["ORA_SDTZ"] = "UTC"` before loading `oracle`.
- **R7. Secrets hygiene:** Never interpolate or log raw Oracle passwords or GCS access tokens in `messages.log()`.
- **R8. Unit tests:** Cover all 5 split types, `AS OF SCN` enforcement, canonical Parquet cast projections, `gcss://` URI conversion, dual-mode `goe_gcs` secret provisioning (`credential_chain` with `PROJECT_ID` vs `access_token` with 10-minute refresh), availability-gate rejections, dry-run behavior, secret redaction, and temp directory cleanup.
