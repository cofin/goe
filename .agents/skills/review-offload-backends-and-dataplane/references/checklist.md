# Review Checklist: Canonical Typing, Cloud Backends, DuckDB 2.0, Arrow & Storage (`DPL`)

## `DPL-01`: Lossless `ColumnSpec` & `TYPE_REGISTRY` Mapping

All column conversions route through `ColumnSpec` and `TYPE_REGISTRY`; unconstrained Oracle `NUMBER`/`FLOAT` columns require sampling (`is_safe_mapping() == False`), and 38-digit integers/decimals map to `INTEGER_38` or `NUMERIC`/`BIGNUMERIC` without float downcasting.

## `DPL-02`: `CachedBackendCatalog` Write-Through Invalidation

Backend DDL/load mutations (`create_table`, `drop_table`, `add_columns`, `load_table_from_uri`, `insert_into_final_table`) invalidate `CachedBackendCatalog` for `(db_name, table_name)` immediately.

## `DPL-03`: Keyless GCP ADC & Explicit `gcsfs` Token Passing

All GCP clients (`bigquery.Client`, `storage.Client`, `kms.KeyManagementServiceClient`, `fsspec.filesystem('gs', token=bundle.credentials)`) obtain credentials from `resolve_gcp_credentials` (`src/goe/config/gcp_credentials.py`); never pass `token=None` to `gcsfs` or confuse `GOOGLE_DATAPROC_SERVICE_ACCOUNT` (workload SA) with `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` (caller impersonation).

## `DPL-04`: DuckDB 2.0 Cgroup Clamping, Optional `httpfs` & SCN Invariant

`DuckDBEngine` clamps memory to 75% of `CgroupQuota.detect()`, skips `LOAD httpfs` when `cloud_secret is None` and no `gs://`/`s3://`/`abfss://` URI is used, sets `parquet_metadata_cache = true` after extension load, and `OffloadTransportDuckDB` calls `verify_batch_scn_invariant` before opening a connection.

## `DPL-05`: `QueryImport` and `DuckDB` Parquet Schema Parity

Changes to `canonical_columns_to_arrow_schema` / `ArrowParquetStagingWriter` (`src/goe/offload/staging/arrow_writers.py`) and `build_cast_projection` (`src/goe/offload/transport/duckdb/parquet_writer.py`) preserve identical physical Parquet schemas, decimal precision/scale, and UTC timestamp semantics.

## `DPL-06`: Optional Backend Dependency Guards (`import_optional_dependency`)

Modules for optional extras (`snowflake-connector-python`, `better_impyla`, `requests_kerberos`, `azure.core.exceptions.ResourceNotFoundError`) guard imports via `import_optional_dependency` so `uv sync --dev --locked` (without `--all-extras`) passes unit tests.
