# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Consolidated Oracle catalog snapshot service, LONG HIGH_VALUE parser, and RAW stat decoder."""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from goe.persistence.statements import NamedStatements
from goe.typing import FrozenBaseStruct

__all__ = [
    "OracleCatalogService",
    "OracleColumnMeta",
    "OracleConstraintMeta",
    "OracleIndexMeta",
    "OraclePartitionMeta",
    "OracleSessionContext",
    "OracleStorageStats",
    "OracleSubpartitionMeta",
    "OracleTableSnapshot",
    "decode_oracle_raw_stat",
    "parse_high_value_literals",
    "parse_single_high_value_token",
    "split_high_value_tokens",
]

_CATALOG_SQL_PATH = Path(__file__).parent / "sql" / "oracle_catalog.sql"

_TO_DATE_RE = re.compile(
    r"^TO_DATE\(\s*'\s*(?P<dt>-?\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*'",
    re.IGNORECASE,
)
_TIMESTAMP_RE = re.compile(
    r"^TIMESTAMP\s*'\s*(?P<dt>-?\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})(?:\.(?P<frac>\d+))?(?:\s*(?P<tz>[^']*))?\s*'$",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


class OracleSessionContext(FrozenBaseStruct, frozen=True):
    """Oracle database and session context fetched in a single round-trip."""

    version: str
    db_unique_name: str
    current_scn: int
    compatible: str
    db_block_size: int
    max_string_size: str
    cell_offload_processing: bool
    current_user: str


class OracleStorageStats(FrozenBaseStruct, frozen=True):
    """Table-level storage and optimizer statistics."""

    num_rows: int = 0
    blocks: int = 0
    avg_row_len: int = 0
    size_in_bytes: int = 0
    last_analyzed: datetime.datetime | None = None


class OracleColumnMeta(FrozenBaseStruct, frozen=True):
    """Oracle column catalog metadata and decoded optimizer endpoints."""

    column_id: int
    name: str
    data_type: str
    data_type_owner: str | None = None
    data_type_mod: str | None = None
    char_used: str | None = None
    data_length: int | None = None
    char_length: int | None = None
    data_precision: int | None = None
    data_scale: int | None = None
    nullable: bool = True
    data_default: str | None = None
    hidden: bool = False
    virtual: bool = False
    num_distinct: int = 0
    num_nulls: int = 0
    avg_col_len: int = 0
    low_value: Any = None
    high_value: Any = None
    partition_position: int | None = None
    subpartition_position: int | None = None


class OracleConstraintMeta(FrozenBaseStruct, frozen=True):
    """Oracle primary or unique constraint metadata."""

    constraint_name: str
    constraint_type: str
    status: str
    validated: str
    column_names: tuple[str, ...]


class OracleIndexMeta(FrozenBaseStruct, frozen=True):
    """Oracle index and ordered column metadata."""

    index_owner: str
    index_name: str
    index_type: str
    uniqueness: str
    column_names: tuple[str, ...]


class OracleSubpartitionMeta(FrozenBaseStruct, frozen=True):
    """Oracle subpartition metadata with parsed HIGH_VALUE literals."""

    partition_name: str
    partition_position: int
    subpartition_name: str
    subpartition_position: int
    high_value_csv: str
    high_value_literals: tuple[Any, ...]
    num_rows: int = 0
    blocks: int = 0
    avg_row_len: int = 0
    size_in_bytes: int = 0


class OraclePartitionMeta(FrozenBaseStruct, frozen=True):
    """Oracle partition metadata with parsed HIGH_VALUE literals and child subpartitions."""

    partition_name: str
    partition_position: int
    high_value_csv: str
    high_value_literals: tuple[Any, ...]
    subpartition_count: int = 0
    num_rows: int = 0
    blocks: int = 0
    avg_row_len: int = 0
    size_in_bytes: int = 0
    subpartitions: tuple[OracleSubpartitionMeta, ...] = ()


class OracleTableSnapshot(FrozenBaseStruct, frozen=True):
    """Complete immutable snapshot of an Oracle source table's dictionary metadata."""

    owner: str
    table_name: str
    iot_type: str | None
    partitioned: bool
    partitioning_type: str | None
    subpartitioning_type: str | None
    degree: str
    compression: str | None
    compress_for: str | None
    stats: OracleStorageStats
    columns: tuple[OracleColumnMeta, ...]
    constraints: tuple[OracleConstraintMeta, ...]
    indexes: tuple[OracleIndexMeta, ...]
    partitions: tuple[OraclePartitionMeta, ...] = ()
    subpartitions: tuple[OracleSubpartitionMeta, ...] = ()

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        """Return ordered primary key column names if a primary key exists."""
        for constraint in self.constraints:
            if constraint.constraint_type == "P":
                return constraint.column_names
        return ()

    @property
    def partition_column_names(self) -> tuple[str, ...]:
        """Return ordered partition key column names."""
        part_cols = [c for c in self.columns if c.partition_position is not None]
        part_cols.sort(key=lambda c: c.partition_position or 0)
        return tuple(c.name for c in part_cols)

    @property
    def subpartition_column_names(self) -> tuple[str, ...]:
        """Return ordered subpartition key column names."""
        subpart_cols = [c for c in self.columns if c.subpartition_position is not None]
        subpart_cols.sort(key=lambda c: c.subpartition_position or 0)
        return tuple(c.name for c in subpart_cols)


def split_high_value_tokens(high_value_csv: str | None) -> tuple[str, ...]:
    """Split an Oracle HIGH_VALUE expression list on top-level commas."""
    if not high_value_csv:
        return ()
    tokens: list[str] = []
    buf: list[str] = []
    paren_depth = 0
    in_quote = False
    i = 0
    length = len(high_value_csv)
    while i < length:
        ch = high_value_csv[i]
        if ch == "'":
            if in_quote and i + 1 < length and high_value_csv[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_quote = not in_quote
            buf.append(ch)
        elif not in_quote:
            if ch == "(":
                paren_depth += 1
                buf.append(ch)
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
                buf.append(ch)
            elif ch == "," and paren_depth == 0:
                token = "".join(buf).strip()
                if token:
                    tokens.append(token)
                buf.clear()
            else:
                buf.append(ch)
        else:
            buf.append(ch)
        i += 1
    trailing = "".join(buf).strip()
    if trailing:
        tokens.append(trailing)
    return tuple(tokens)


def parse_single_high_value_token(token: str) -> Any:
    """Parse a single Oracle partition HIGH_VALUE literal expression in pure Python."""
    stripped = token.strip()
    upper = stripped.upper()
    if upper in {"MAXVALUE", "DEFAULT"}:
        return upper
    if upper == "NULL":
        return None
    m_date = _TO_DATE_RE.match(stripped)
    if m_date:
        dt_str = " ".join(m_date.group("dt").split())
        if dt_str.startswith("-"):
            return stripped
        return datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    m_ts = _TIMESTAMP_RE.match(stripped)
    if m_ts:
        dt_str = " ".join(m_ts.group("dt").split())
        if dt_str.startswith("-"):
            return stripped
        base = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        frac = m_ts.group("frac") or ""
        micros = int(frac[:6].ljust(6, "0")) if frac else 0
        return base.replace(microsecond=micros)
    if stripped.startswith("'") and stripped.endswith("'") and len(stripped) >= 2:
        return stripped[1:-1].replace("''", "'")
    if _NUMBER_RE.match(stripped):
        try:
            return Decimal(stripped)
        except InvalidOperation:
            return stripped
    return stripped


def parse_high_value_literals(high_value_csv: str | None) -> tuple[Any, ...]:
    """Parse a comma-separated Oracle HIGH_VALUE string into Python values."""
    return tuple(parse_single_high_value_token(tok) for tok in split_high_value_tokens(high_value_csv))


def decode_oracle_raw_stat(raw_bytes: bytes | None, data_type: str) -> Any:
    """Decode ALL_TAB_COLS.LOW_VALUE / HIGH_VALUE RAW bytes without an RDBMS round-trip."""
    if not raw_bytes:
        return None
    normalized_type = data_type.upper()
    if normalized_type in {"VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR"}:
        try:
            return raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            return None
    if normalized_type == "DATE" or normalized_type.startswith("TIMESTAMP"):
        if len(raw_bytes) < 7:
            return None
        year = (raw_bytes[0] - 100) * 100 + (raw_bytes[1] - 100)
        month = raw_bytes[2]
        day = raw_bytes[3]
        hour = raw_bytes[4] - 1
        minute = raw_bytes[5] - 1
        second = raw_bytes[6] - 1
        microsecond = 0
        if len(raw_bytes) >= 11:
            nanos = int.from_bytes(raw_bytes[7:11], byteorder="big", signed=False)
            microsecond = nanos // 1000
        try:
            return datetime.datetime(year, month, day, hour, minute, second, microsecond)
        except ValueError:
            return None
    if normalized_type in {"NUMBER", "FLOAT"}:
        return _decode_oracle_raw_number(raw_bytes)
    return raw_bytes


class OracleCatalogService:
    """Service that executes consolidated Oracle catalog queries through a SQLSpec driver."""

    def __init__(self, statements: NamedStatements | None = None) -> None:
        self._statements = statements or NamedStatements(_CATALOG_SQL_PATH)

    def fetch_session_context(self, driver: Any) -> OracleSessionContext:
        """Fetch Oracle instance, database, and session parameters in 1 round-trip."""
        row = driver.select_one_or_none(self._statements["get_session_context"]) or {}
        g = _row_getter(row)
        return OracleSessionContext(
            version=str(g("version") or ""),
            db_unique_name=str(g("db_unique_name") or ""),
            current_scn=int(g("current_scn") or 0),
            compatible=str(g("compatible") or ""),
            db_block_size=int(g("db_block_size") or 8192),
            max_string_size=str(g("max_string_size") or "STANDARD"),
            cell_offload_processing=str(g("cell_offload_processing") or "FALSE").upper() == "TRUE",
            current_user=str(g("current_user") or g("session_user") or ""),
        )

    def fetch_table_snapshot(self, driver: Any, owner: str, table_name: str) -> OracleTableSnapshot | None:
        """Fetch a complete OracleTableSnapshot for (owner, table_name)."""
        params = {"owner": owner.upper(), "table_name": table_name.upper()}
        overview = driver.select_one_or_none(self._statements["get_table_overview"], params)
        if not overview:
            return None
        og = _row_getter(overview)
        partitioned = str(og("partitioned") or "NO").upper() == "YES"
        subpart_type = og("subpartitioning_type")
        if subpart_type and str(subpart_type).upper() == "NONE":
            subpart_type = None

        stats = OracleStorageStats(
            num_rows=int(og("num_rows") or 0),
            blocks=int(og("blocks") or 0),
            avg_row_len=int(og("avg_row_len") or 0),
            size_in_bytes=int(og("size_bytes") or 0),
            last_analyzed=og("last_analyzed"),
        )

        col_rows = driver.select(self._statements["get_table_columns"], params)
        columns: list[OracleColumnMeta] = []
        for idx, crow in enumerate(col_rows, start=1):
            cg = _row_getter(crow)
            dtype = str(cg("data_type") or "")
            low_raw = cg("low_value")
            high_raw = cg("high_value")
            columns.append(
                OracleColumnMeta(
                    column_id=int(cg("column_id") or idx),
                    name=str(cg("column_name") or ""),
                    data_type=dtype,
                    data_type_owner=cg("data_type_owner"),
                    data_type_mod=cg("data_type_mod"),
                    char_used=cg("char_used"),
                    data_length=int(cg("data_length")) if cg("data_length") is not None else None,
                    char_length=int(cg("char_length")) if cg("char_length") is not None else None,
                    data_precision=int(cg("data_precision")) if cg("data_precision") is not None else None,
                    data_scale=int(cg("data_scale")) if cg("data_scale") is not None else None,
                    nullable=str(cg("nullable") or "Y").upper() == "Y",
                    data_default=str(cg("data_default")) if cg("data_default") is not None else None,
                    hidden=str(cg("hidden_column") or "NO").upper() == "YES",
                    virtual=str(cg("virtual_column") or "NO").upper() == "YES",
                    num_distinct=int(cg("num_distinct") or 0),
                    num_nulls=int(cg("num_nulls") or 0),
                    avg_col_len=int(cg("avg_col_len") or 0),
                    low_value=decode_oracle_raw_stat(low_raw, dtype) if isinstance(low_raw, bytes) else low_raw,
                    high_value=decode_oracle_raw_stat(high_raw, dtype) if isinstance(high_raw, bytes) else high_raw,
                    partition_position=int(cg("part_pos")) if cg("part_pos") is not None else None,
                    subpartition_position=int(cg("subpart_pos")) if cg("subpart_pos") is not None else None,
                )
            )

        cons_rows = driver.select(self._statements["get_table_constraints"], params)
        constraints = _group_constraints(cons_rows)

        idx_rows = driver.select(self._statements["get_table_indexes"], params)
        indexes = _group_indexes(idx_rows)

        partitions: tuple[OraclePartitionMeta, ...] = ()
        subpartitions: tuple[OracleSubpartitionMeta, ...] = ()
        if partitioned:
            part_rows = driver.select(self._statements["get_table_partitions"], params)
            subpart_by_part: dict[str, list[OracleSubpartitionMeta]] = {}
            if subpart_type:
                sub_rows = driver.select(self._statements["get_table_subpartitions"], params)
                sub_list: list[OracleSubpartitionMeta] = []
                for srow in sub_rows:
                    sg = _row_getter(srow)
                    hv_csv = str(sg("high_value") or "")
                    smeta = OracleSubpartitionMeta(
                        partition_name=str(sg("partition_name") or ""),
                        partition_position=int(sg("partition_position") or 0),
                        subpartition_name=str(sg("subpartition_name") or ""),
                        subpartition_position=int(sg("subpartition_position") or 0),
                        high_value_csv=hv_csv,
                        high_value_literals=parse_high_value_literals(hv_csv),
                        num_rows=int(sg("num_rows") or 0),
                        blocks=int(sg("blocks") or 0),
                        avg_row_len=int(sg("avg_row_len") or 0),
                        size_in_bytes=int(sg("size_bytes") or 0),
                    )
                    sub_list.append(smeta)
                    subpart_by_part.setdefault(smeta.partition_name, []).append(smeta)
                subpartitions = tuple(sub_list)

            part_list: list[OraclePartitionMeta] = []
            for prow in part_rows:
                pg = _row_getter(prow)
                pname = str(pg("partition_name") or "")
                hv_csv = str(pg("high_value") or "")
                part_list.append(
                    OraclePartitionMeta(
                        partition_name=pname,
                        partition_position=int(pg("partition_position") or 0),
                        high_value_csv=hv_csv,
                        high_value_literals=parse_high_value_literals(hv_csv),
                        subpartition_count=int(pg("subpartition_count") or 0),
                        num_rows=int(pg("num_rows") or 0),
                        blocks=int(pg("blocks") or 0),
                        avg_row_len=int(pg("avg_row_len") or 0),
                        size_in_bytes=int(pg("size_bytes") or 0),
                        subpartitions=tuple(subpart_by_part.get(pname, ())),
                    )
                )
            partitions = tuple(part_list)

        return OracleTableSnapshot(
            owner=str(og("owner") or owner.upper()),
            table_name=str(og("table_name") or table_name.upper()),
            iot_type=og("iot_type"),
            partitioned=partitioned,
            partitioning_type=og("partitioning_type"),
            subpartitioning_type=subpart_type,
            degree=str(og("degree") or "1"),
            compression=og("compression"),
            compress_for=og("compress_for"),
            stats=stats,
            columns=tuple(columns),
            constraints=constraints,
            indexes=indexes,
            partitions=partitions,
            subpartitions=subpartitions,
        )


def _decode_oracle_raw_number(raw_bytes: bytes) -> Decimal | None:
    """Decode Oracle internal variable-length base-100 NUMBER encoding."""
    if not raw_bytes or raw_bytes == b"\x80":
        return Decimal(0)
    first = raw_bytes[0]
    if first & 0x80:
        exponent = (first & 0x7F) - 65
        digits = [b - 1 for b in raw_bytes[1:]]
        sign = 1
    else:
        exponent = (0xFF - first & 0x7F) - 65
        digits = [101 - b for b in raw_bytes[1:] if b != 102]
        sign = -1
    value = Decimal(0)
    for idx, digit in enumerate(digits):
        if digit < 0 or digit >= 100:
            return None
        power = (exponent - idx) * 2
        value += Decimal(digit) * (Decimal(10) ** power)
    return value * sign


def _row_getter(row: Mapping[str, Any] | Any) -> Any:
    """Return a case-insensitive column lookup callable for a row dictionary."""
    if isinstance(row, dict):
        lowered = {k.lower(): v for k, v in row.items()}
        return lambda key: lowered.get(key.lower())
    return lambda key: getattr(row, key, getattr(row, key.upper(), None))


def _group_constraints(rows: list[Any]) -> tuple[OracleConstraintMeta, ...]:
    grouped: dict[str, tuple[str, str, str, list[str]]] = {}
    for row in rows:
        g = _row_getter(row)
        cname = str(g("constraint_name") or "")
        ctype = str(g("constraint_type") or "")
        status = str(g("status") or "")
        validated = str(g("validated") or "")
        col = str(g("column_name") or "")
        if cname not in grouped:
            grouped[cname] = (ctype, status, validated, [])
        grouped[cname][3].append(col)
    return tuple(
        OracleConstraintMeta(
            constraint_name=cname,
            constraint_type=meta[0],
            status=meta[1],
            validated=meta[2],
            column_names=tuple(meta[3]),
        )
        for cname, meta in grouped.items()
    )


def _group_indexes(rows: list[Any]) -> tuple[OracleIndexMeta, ...]:
    grouped: dict[tuple[str, str], tuple[str, str, list[str]]] = {}
    for row in rows:
        g = _row_getter(row)
        iowner = str(g("index_owner") or "")
        iname = str(g("index_name") or "")
        itype = str(g("index_type") or "")
        uniq = str(g("uniqueness") or "")
        col = str(g("column_name") or "")
        key = (iowner, iname)
        if key not in grouped:
            grouped[key] = (itype, uniq, [])
        grouped[key][2].append(col)
    return tuple(
        OracleIndexMeta(
            index_owner=iowner,
            index_name=iname,
            index_type=meta[0],
            uniqueness=meta[1],
            column_names=tuple(meta[2]),
        )
        for (iowner, iname), meta in grouped.items()
    )
