# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Constants for the opt-in DuckDB offload transport, importable without importing duckdb."""

OFFLOAD_TRANSPORT_METHOD_DUCKDB = "DUCKDB"
MIN_SUPPORTED_DUCKDB_VERSION = "2.0.0"
SUPPORTED_DUCKDB_VERSION_PREFIX = "2.0"
DUCKDB_ORACLE_ATTACH_ALIAS = "goe_ora"
DUCKDB_ORACLE_SECRET_NAME = "goe_ora_secret"
DUCKDB_GCS_SECRET_NAME = "goe_gcs"
DUCKDB_S3_SECRET_NAME = "goe_s3"
DUCKDB_AZURE_SECRET_NAME = "goe_azure"
DUCKDB_GCS_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
