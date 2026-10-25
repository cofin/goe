# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Canonical OracleSourceTable module."""

from __future__ import annotations

from goe.offload.oracle.oracle_offload_source_table import (
    ORACLE_SUPPORTED_LIST_DATA_TYPES,
    ORACLE_SUPPORTED_RANGE_DATA_TYPES,
    OracleSourceTable,
    oracle_datetime_literal_to_python,
    oracle_number_literal_to_python,
    oracle_version_is_smart_scan_unsafe,
    oracle_version_supports_exadata,
)

__all__ = [
    "ORACLE_SUPPORTED_LIST_DATA_TYPES",
    "ORACLE_SUPPORTED_RANGE_DATA_TYPES",
    "OracleSourceTable",
    "oracle_datetime_literal_to_python",
    "oracle_number_literal_to_python",
    "oracle_version_is_smart_scan_unsafe",
    "oracle_version_supports_exadata",
]
