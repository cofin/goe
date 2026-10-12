# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Constants for the opt-in DuckDB offload transport, importable without importing duckdb."""

OFFLOAD_TRANSPORT_METHOD_DUCKDB = "DUCKDB"
DUCKDB_ORACLE_ATTACH_ALIAS = "goe_ora"
DUCKDB_ORACLE_SECRET_NAME = "goe_ora_secret"
DUCKDB_GCS_SECRET_NAME = "goe_gcs"
DUCKDB_GCS_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
