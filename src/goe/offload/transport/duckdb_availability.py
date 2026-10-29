# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Static eligibility checks for the opt-in DUCKDB offload transport.

The checks need no network access; extension download and load errors surface when the transport starts.
"""

from typing import TYPE_CHECKING, Any

import duckdb
from packaging.version import Version

from goe.offload.offload_constants import DBTYPE_BIGQUERY, FILE_STORAGE_FORMAT_PARQUET
from goe.offload.offload_messages import VVERBOSE
from goe.offload.schema.column_spec import (
    ORACLE_TYPE_BLOB,
    ORACLE_TYPE_CLOB,
    ORACLE_TYPE_LONG,
    ORACLE_TYPE_LONG_RAW,
    ORACLE_TYPE_NCLOB,
    ORACLE_TYPE_XMLTYPE,
)
from goe.offload.transport.duckdb_constants import MIN_SUPPORTED_DUCKDB_VERSION

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_table import OffloadSourceTableInterface

DUCKDB_SUPPORTED_FS_SCHEMES: frozenset[str] = frozenset(
    {
        "gs",
        "s3",
        "s3a",
        "az",
        "abfs",
        "abfss",
        "wasb",
        "wasbs",
    }
)
DUCKDB_UNSUPPORTED_ORACLE_TYPES: frozenset[str] = frozenset(
    {
        ORACLE_TYPE_BLOB,
        ORACLE_TYPE_CLOB,
        ORACLE_TYPE_LONG,
        ORACLE_TYPE_LONG_RAW,
        ORACLE_TYPE_NCLOB,
        ORACLE_TYPE_XMLTYPE,
    }
)


def duckdb_unavailable_reason(
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface | None" = None,
) -> str | None:
    """Return why the DUCKDB transport cannot run this offload, or None when it is eligible."""
    if config.target != DBTYPE_BIGQUERY:
        return "DUCKDB transport only supports BigQuery targets"
    scheme = (config.offload_fs_scheme or "").lower()
    if scheme not in DUCKDB_SUPPORTED_FS_SCHEMES:
        return (
            "DUCKDB transport requires a supported cloud OFFLOAD_FS_SCHEME "
            f"({', '.join(sorted(DUCKDB_SUPPORTED_FS_SCHEMES))}), found: {config.offload_fs_scheme}"
        )
    if config.offload_staging_format != FILE_STORAGE_FORMAT_PARQUET:
        return f"DUCKDB transport requires OFFLOAD_STAGING_FORMAT=PARQUET, found: {config.offload_staging_format}"
    required_version = config.offload_transport_duckdb_version or MIN_SUPPORTED_DUCKDB_VERSION
    if Version(required_version) < Version(MIN_SUPPORTED_DUCKDB_VERSION) or Version(duckdb.__version__) < Version(
        required_version
    ):
        return (
            f"Installed DuckDB {duckdb.__version__} does not satisfy "
            f"OFFLOAD_TRANSPORT_DUCKDB_VERSION={required_version} (minimum {MIN_SUPPORTED_DUCKDB_VERSION})"
        )
    if offload_source_table is not None:
        table_bytes = offload_source_table.size_in_bytes or 0
        if table_bytes > config.offload_transport_duckdb_max_bytes:
            return (
                f"Table size ({table_bytes}) > {config.offload_transport_duckdb_max_bytes} "
                "(OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES)"
            )
        unsupported = sorted(set(offload_source_table.data_types_in_use()) & DUCKDB_UNSUPPORTED_ORACLE_TYPES)
        if unsupported:
            return f"DUCKDB transport does not support column types: {', '.join(unsupported)}"
    return None


def is_duckdb_available(
    offload_operation: Any,
    config: "OrchestrationConfig",
    offload_source_table: "OffloadSourceTableInterface | None" = None,
    messages: "OffloadMessages | None" = None,
) -> bool:
    """Return True when the DUCKDB transport can run this offload; log the reason at VVERBOSE otherwise.

    offload_operation is accepted for parity with the other availability functions.
    """
    reason = duckdb_unavailable_reason(config, offload_source_table)
    if reason and messages:
        messages.log(reason, detail=VVERBOSE)
    return reason is None
