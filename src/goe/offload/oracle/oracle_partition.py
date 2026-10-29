# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Conversion helpers from OracleTableSnapshot partition metadata to RdbmsPartition structs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from numpy import datetime64

from goe.offload.offload_source_table import RdbmsPartition
from goe.offload.oracle.catalog import (
    OraclePartitionMeta,
    OracleSubpartitionMeta,
    OracleTableSnapshot,
    split_high_value_tokens,
)
from goe.offload.oracle.oracle_frontend_api import switch_oracle_open_partition_token

__all__ = [
    "rdbms_partitions_from_snapshot",
    "rdbms_subpartitions_from_snapshot",
]


def rdbms_partitions_from_snapshot(
    snapshot: OracleTableSnapshot,
    *,
    populate_hvs: bool = True,
    literal_converter: Callable[[OraclePartitionMeta], tuple[Any, ...]] | None = None,
) -> list[RdbmsPartition]:
    """Convert snapshot partitions into RdbmsPartition objects in descending position order."""
    partitions: list[RdbmsPartition] = []
    for p in snapshot.partitions:
        sub_names = [sp.subpartition_name for sp in p.subpartitions] if p.subpartitions else None
        hv_ind = (
            tuple(switch_oracle_open_partition_token(tok) for tok in split_high_value_tokens(p.high_value_csv))
            if populate_hvs
            else None
        )
        if populate_hvs:
            hv_py = (
                literal_converter(p)
                if literal_converter is not None
                else _normalize_snapshot_literals(p.high_value_literals)
            )
        else:
            hv_py = None
        partitions.append(
            RdbmsPartition.by_name(
                partition_count=1,
                partition_name=p.partition_name,
                partition_position=p.partition_position,
                subpartition_count=p.subpartition_count,
                subpartition_names=sub_names,
                high_values_csv=p.high_value_csv,
                partition_size=p.size_in_bytes,
                num_rows=p.num_rows,
                high_values_individual=hv_ind,
                high_values_python=hv_py,
            )
        )
    return partitions


def rdbms_subpartitions_from_snapshot(
    snapshot: OracleTableSnapshot,
    *,
    populate_hvs: bool = True,
    literal_converter: Callable[[OracleSubpartitionMeta], tuple[Any, ...]] | None = None,
) -> list[RdbmsPartition]:
    """Convert snapshot subpartitions into RdbmsPartition objects."""
    part_count = len(snapshot.partitions)
    sub_counts = {p.partition_name: p.subpartition_count for p in snapshot.partitions}
    subpartitions: list[RdbmsPartition] = []
    for sp in snapshot.subpartitions:
        hv_ind = (
            tuple(switch_oracle_open_partition_token(tok) for tok in split_high_value_tokens(sp.high_value_csv))
            if populate_hvs
            else None
        )
        if populate_hvs:
            hv_py = (
                literal_converter(sp)
                if literal_converter is not None
                else _normalize_snapshot_literals(sp.high_value_literals)
            )
        else:
            hv_py = None
        subpartitions.append(
            RdbmsPartition.by_name(
                partition_count=part_count,
                partition_name=sp.partition_name,
                partition_position=sp.partition_position,
                subpartition_count=sub_counts.get(sp.partition_name, 1),
                subpartition_name=sp.subpartition_name,
                subpartition_position=sp.subpartition_position,
                high_values_csv=sp.high_value_csv,
                partition_size=sp.size_in_bytes,
                num_rows=sp.num_rows,
                high_values_individual=hv_ind,
                high_values_python=hv_py,
            )
        )
    if populate_hvs:
        subpartitions.sort(key=lambda x: x.high_values_python or (), reverse=True)
    return subpartitions


def _normalize_snapshot_literals(literals: tuple[Any, ...]) -> tuple[Any, ...]:
    normalized: list[Any] = []
    for val in literals:
        if isinstance(val, datetime):
            normalized.append(datetime64(val))
        elif isinstance(val, Decimal) and val == int(val):
            normalized.append(int(val))
        elif isinstance(val, str):
            normalized.append(switch_oracle_open_partition_token(val))
        else:
            normalized.append(val)
    return tuple(normalized)
