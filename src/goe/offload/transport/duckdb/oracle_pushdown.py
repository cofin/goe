# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""DuckDB community oracle extension pushdown planner, cache lifecycle, and Arrow fallback router."""

import ctypes.util
from collections.abc import Sequence

import duckdb

from goe.offload.schema.column_spec import (
    ORACLE_TYPE_BFILE,
    ORACLE_TYPE_BLOB,
    ORACLE_TYPE_CLOB,
    ORACLE_TYPE_INTERVAL_DS,
    ORACLE_TYPE_INTERVAL_YM,
    ORACLE_TYPE_LONG,
    ORACLE_TYPE_LONG_RAW,
    ORACLE_TYPE_NCLOB,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
    ORACLE_TYPE_TIMESTAMP_TZ,
    ORACLE_TYPE_XMLTYPE,
    ColumnSpec,
)
from goe.offload.transport.duckdb.engine import (
    DuckDBEngine,
    attach_oracle,
    sql_string_literal,
    verify_batch_scn_invariant,
)
from goe.offload.transport.duckdb_constants import DUCKDB_ORACLE_ATTACH_ALIAS
from goe.typing import FrozenBaseStruct

__all__ = [
    "MAX_ORACLE_EXTENSION_NUMBER_PRECISION",
    "MAX_ORACLE_EXTENSION_PRECISION_CAP",
    "ORACLE_EXTENSION_FALLBACK_TYPES",
    "OracleExtensionTransport",
    "OracleFallbackAssessment",
    "OraclePushdownPlan",
]

ORACLE_EXTENSION_FALLBACK_TYPES: frozenset[str] = frozenset(
    {
        ORACLE_TYPE_INTERVAL_YM,
        ORACLE_TYPE_INTERVAL_DS,
        ORACLE_TYPE_TIMESTAMP_TZ,
        ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
        ORACLE_TYPE_BFILE,
        ORACLE_TYPE_XMLTYPE,
        ORACLE_TYPE_BLOB,
        ORACLE_TYPE_CLOB,
        ORACLE_TYPE_NCLOB,
        ORACLE_TYPE_LONG,
        ORACLE_TYPE_LONG_RAW,
        "JSON",
        "VECTOR",
        "SDO_GEOMETRY",
        "OBJECT",
    }
)
MAX_ORACLE_EXTENSION_NUMBER_PRECISION = 18


class OracleFallbackAssessment(FrozenBaseStruct, frozen=True, kw_only=True):
    """Decision record indicating whether extraction must fall back from duckdb-oracle to Arrow streaming."""

    requires_arrow_fallback: bool
    reasons: tuple[str, ...] = ()


class OraclePushdownPlan(FrozenBaseStruct, frozen=True, kw_only=True):
    """Validated set of parallel Oracle split queries pinned to an optional snapshot SCN."""

    batch_queries: tuple[str, ...]
    cast_projection: str
    consistent_read: bool = True
    snapshot_scn: int | None = None


class OracleExtensionTransport:
    """Executes parallel AS OF SCN Oracle pushdown queries through duckdb-oracle v0.3.1."""

    def __init__(self, engine: DuckDBEngine) -> None:
        self._engine = engine

    @staticmethod
    def has_oci_client_library() -> bool:
        """Return True when Oracle Instant Client libclntsh is discoverable on the host."""
        return bool(ctypes.util.find_library("clntsh"))

    @classmethod
    def assess_table_eligibility(
        cls,
        columns: Sequence[ColumnSpec],
        *,
        has_oci_library: bool | None = None,
    ) -> OracleFallbackAssessment:
        """Determine whether a table can use duckdb-oracle pushdown or must fall back to Arrow extraction."""
        oci_present = cls.has_oci_client_library() if has_oci_library is None else has_oci_library
        reasons: list[str] = []
        if not oci_present:
            reasons.append("Oracle Instant Client (libclntsh) is not available; routing to clientless Arrow extractor")
        for col in columns:
            dtype = (col.data_type or "").upper()
            if dtype in ORACLE_EXTENSION_FALLBACK_TYPES or any(
                dtype.startswith(prefix)
                for prefix in ("INTERVAL", "TIMESTAMP", "SDO_")
                if prefix != "TIMESTAMP" or "TIME ZONE" in dtype
            ):
                reasons.append(f"Column {col.name} has type {dtype} requiring Arrow extractor")
            elif dtype == ORACLE_TYPE_NUMBER:
                precision = getattr(col, "data_precision", None)
                scale = getattr(col, "data_scale", None)
                if precision is None or precision > MAX_ORACLE_EXTENSION_PRECISION_CAP(precision, scale):
                    reasons.append(
                        f"Column {col.name} has NUMBER({precision}, {scale}) exceeding 18-digit OCI pushdown fidelity"
                    )
        return OracleFallbackAssessment(
            requires_arrow_fallback=bool(reasons),
            reasons=tuple(reasons),
        )

    def prepare_session(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        user: str | None,
        password: str | None,
        dsn: str,
        wallet_path: str | None = None,
    ) -> None:
        """Attach the Oracle source secret and flush the duckdb-oracle metadata cache before extraction."""
        attach_oracle(conn, user=user, password=password, dsn=dsn, wallet_path=wallet_path)
        conn.execute("SELECT oracle_clear_cache();")

    def build_oracle_query_relation_sql(self, plan: OraclePushdownPlan, batch_index: int) -> str:
        """Return the SELECT ... FROM oracle_query(...) SQL for one verified split batch."""
        oracle_sql = plan.batch_queries[batch_index]
        verify_batch_scn_invariant(oracle_sql, plan.consistent_read, plan.snapshot_scn)
        return (
            f"SELECT {plan.cast_projection} FROM oracle_query("
            f"{sql_string_literal(DUCKDB_ORACLE_ATTACH_ALIAS)}, {sql_string_literal(oracle_sql)})"
        )


def MAX_ORACLE_EXTENSION_PRECISION_CAP(precision: int | None, scale: int | None) -> int:
    """Return the maximum safe decimal precision for native duckdb-oracle pushdown."""
    if precision is None or (scale is not None and (scale < 0 or scale > precision)):
        return -1
    return MAX_ORACLE_EXTENSION_NUMBER_PRECISION
