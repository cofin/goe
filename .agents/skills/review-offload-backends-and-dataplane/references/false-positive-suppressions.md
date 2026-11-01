# False-Positive Suppressions: Canonical Typing, Cloud Backends, DuckDB 2.0, Arrow & Storage (`FP-DPL`)

## `FP-DPL-01`: DO NOT FLAG `DuckDBEngine` skipping `LOAD httpfs` when `cloud_secret is None`

- **Directive**: DO NOT FLAG `DuckDBEngine` skipping `LOAD httpfs` when `cloud_secret is None`.
- **Rationale**: Skipping `LOAD httpfs` when `cloud_secret is None` and staging to local filesystem paths allows offline unit tests and local staging runs to succeed without network-installed DuckDB extensions.

## `FP-DPL-02`: DO NOT FLAG `BigQueryLoadJobIngestStrategy` skipping staging table DDL in `NATIVE` direct-load mode

- **Directive**: DO NOT FLAG `BigQueryLoadJobIngestStrategy` skipping staging table DDL in `NATIVE` direct-load mode.
- **Rationale**: When `can_use_direct_load_uri()` holds, `BigQueryLoadJobIngestStrategy` loads staged Parquet URIs directly into the target BigQuery table via `load_table_from_uri` in 1 job with 0 SQL scan bytes billed.

## `FP-DPL-03`: DO NOT FLAG `LocalStore.delete_sync` single-key iteration in `StagingStorageService`

- **Directive**: DO NOT FLAG `LocalStore.delete_sync` single-key iteration in `StagingStorageService`.
- **Rationale**: `sqlspec.storage.LocalStore.delete_sync` accepts a single relative path string per call rather than a list of keys, whereas GCS/S3 delete in 1,000-key batches.

## `FP-DPL-04`: DO NOT FLAG `KerberosClient = object` fallback in `src/goe/filesystem/web_hdfs.py`

- **Directive**: DO NOT FLAG `KerberosClient = object` fallback in `src/goe/filesystem/web_hdfs.py`.
- **Rationale**: Guarding `requests_kerberos` with a fallback class allows `web_hdfs.py` to be imported and tested in base CI environments where the optional `hadoop` extra is not installed.
