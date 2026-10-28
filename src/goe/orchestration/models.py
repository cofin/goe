# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Immutable value objects for staged offload planning and stateless execution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

import msgspec

from goe.offload.offload_constants import PART_OUT_OF_LIST, PART_OUT_OF_RANGE
from goe.offload.offload_messages import VVERBOSE
from goe.offload.schema.column_spec import ColumnSpec
from goe.persistence.models import OffloadMetadata
from goe.typing import FrozenBaseStruct

if TYPE_CHECKING:
    from goe.offload.offload_messages import OffloadMessages

__all__ = [
    "BackendLoadPlan",
    "DiscoveryState",
    "OffloadExecutionReport",
    "OffloadMode",
    "OffloadPlan",
    "OffloadSourcePartition",
    "OffloadSourcePartitions",
    "PartitionBoundaryPlan",
    "PredicatePlan",
    "PriorMetadataState",
    "SchemaEvolutionPlan",
    "SourcePartitionSlice",
    "StagingTransportPlan",
]

type OffloadMode = Literal[
    "FULL",
    "INCREMENTAL_RANGE",
    "INCREMENTAL_LIST",
    "INCREMENTAL_LIST_AS_RANGE",
    "PREDICATE",
]


class SourcePartitionSlice(msgspec.Struct, frozen=True, gc=False, array_like=True):
    """Compact partition or subpartition descriptor for offload boundary planning."""

    partition_name: str
    partition_position: int = 0
    high_value_raw: str = ""
    high_value_literals: tuple[str, ...] = ()
    byte_size: int = 0
    row_count: int = 0
    subpartition_names: tuple[str, ...] = ()
    is_default: bool = False


class OffloadSourcePartition(msgspec.Struct, frozen=True, gc=False, array_like=True):
    """Partition descriptor used by transport and repository chunk adapters."""

    partition_name: str
    partition_literal: Any = None
    partition_values_python: Any = ()
    partition_values_individual: Any = ()
    size_in_bytes: int | None = None
    row_count: int | None = None
    common_partition_literal: Any = None
    subpartitions: Any = None

    def __str__(self) -> str:
        """Return string representation matching legacy OffloadSourcePartition."""
        return "OffloadSourcePartition(partition_name=%s, partition_literal=%r)" % (
            self.partition_name,
            self.partition_literal,
        )

    def as_legacy_tuple(self) -> tuple[Any, ...]:
        """Return 8-element legacy tuple representation."""
        return (
            self.partition_name,
            self.partition_literal,
            self.partition_values_python,
            self.size_in_bytes,
            self.row_count,
            self.partition_values_individual,
            self.common_partition_literal,
            self.subpartitions,
        )


class OffloadSourcePartitions:
    """Holds partitions in scope for offload transport and repository chunk recording."""

    def __init__(self, partitions: Sequence[OffloadSourcePartition] | None = None) -> None:
        """Initialize the partition collection."""
        self._partitions: list[OffloadSourcePartition] = list(partitions) if partitions else []

    def __str__(self) -> str:
        """Return human-readable summary of partition collection."""
        if self._partitions:
            return "OffloadSourcePartitions(partitions=%s, partition range=%s-%s)" % (
                len(self._partitions),
                self._partitions[0].partition_name,
                self._partitions[-1].partition_name,
            )
        return "OffloadSourcePartitions(None)"

    @staticmethod
    def from_source_table(
        offload_source_table: Any,
        partition_append_capable: bool = True,
    ) -> OffloadSourcePartitions:
        """Construct OffloadSourcePartitions from an OffloadSourceTable."""
        if offload_source_table.offload_by_subpartition:
            rdbms_partitions = offload_source_table.get_subpartitions(strict=partition_append_capable)
            hwm_info = offload_source_table.get_subpartition_boundary_info()
            partitions = [
                OffloadSourcePartition(
                    ora_partition.subpartition_name,
                    ora_partition.high_values_csv,
                    ora_partition.high_values_python,
                    ora_partition.high_values_individual,
                    ora_partition.partition_size,
                    ora_partition.num_rows,
                    hwm_info[ora_partition.high_values_python]["common"],
                    ora_partition.subpartition_names,
                )
                for ora_partition in (rdbms_partitions or [])
            ]
        else:
            rdbms_partitions = offload_source_table.get_partitions(strict=partition_append_capable)
            partitions = [
                OffloadSourcePartition(
                    ora_partition.partition_name,
                    ora_partition.high_values_csv,
                    ora_partition.high_values_python,
                    ora_partition.high_values_individual,
                    ora_partition.partition_size,
                    ora_partition.num_rows,
                    True,
                    ora_partition.subpartition_names,
                )
                for ora_partition in (rdbms_partitions or [])
            ]
        return OffloadSourcePartitions(partitions)

    def as_legacy_list(self) -> list[tuple[Any, ...]]:
        """Return list of legacy tuples."""
        return [p.as_legacy_tuple() for p in self._partitions]

    def count(self) -> int:
        """Return partition count."""
        return len(self._partitions)

    def get_partitions(self) -> list[OffloadSourcePartition]:
        """Return underlying list of partitions."""
        return self._partitions

    def partition_names(self) -> list[str]:
        """Return list of partition names."""
        return [p.partition_name for p in self._partitions]

    def row_count(self) -> int:
        """Return sum of row counts across partitions."""
        return sum(p.row_count or 0 for p in self._partitions)

    def set_partitions(self, partitions: Sequence[OffloadSourcePartition]) -> None:
        """Replace underlying partition list."""
        self._partitions = list(partitions)

    def size_in_bytes(self) -> int:
        """Return sum of byte sizes across partitions."""
        return sum(p.size_in_bytes or 0 for p in self._partitions)

    def subpartition_names(self) -> list[str]:
        """Return flattened list of subpartition names."""
        return [s for p in self._partitions if p.subpartitions is not None for s in p.subpartitions]

    def report_partitions(
        self,
        offload_by_subpartition: bool,
        messages: OffloadMessages,
        include_stats: bool = True,
    ) -> None:
        """Report partitions in standard offload stdout format."""
        part_description = "subpartitions" if offload_by_subpartition else "partitions"
        if not self._partitions:
            messages.log("0 %s" % part_description)
            return
        sizes = [p.size_in_bytes for p in self._partitions]
        rows_list = [p.row_count for p in self._partitions]
        size: int | str = "Unknown" if any(s is None for s in sizes) else sum(s for s in sizes if s is not None)
        rows: int | str = "Unknown" if any(r is None for r in rows_list) else sum(r for r in rows_list if r is not None)
        if include_stats:
            messages.log(
                "%s %s (%s - %s), total size %s, total rows (from stats) %s"
                % (
                    len(self._partitions),
                    part_description,
                    self._partitions[-1].partition_name,
                    self._partitions[0].partition_name,
                    size,
                    rows,
                )
            )
        else:
            messages.log("%s %s" % (len(self._partitions), part_description))
        if messages.debug_enabled():
            for p in self._partitions:
                messages.log("%s" % str(p), detail=VVERBOSE)

    def get_partition_by_index(self, index: int) -> OffloadSourcePartition | None:
        """Return partition at index or None."""
        return self._partitions[index] if self._partitions else None

    def get_prior_partition(
        self,
        partition: OffloadSourcePartition | None = None,
        partition_name: str | None = None,
        partition_values_python: Sequence[Any] | None = None,
    ) -> OffloadSourcePartition | None:
        """Find the partition immediately older than the target partition."""
        start_partition = partition
        if start_partition is None and partition_name is not None:
            matches = [p for p in self._partitions if p.partition_name == partition_name]
            start_partition = matches[0] if matches else None
        elif start_partition is None and partition_values_python is not None:
            target_tuple = tuple(partition_values_python)
            matches = [p for p in self._partitions if tuple(p.partition_values_python) == target_tuple]
            start_partition = matches[0] if matches else None
        if start_partition is None:
            return None
        for p in self._partitions:
            vals = [v.upper() if isinstance(v, str) else v for v in p.partition_values_python]
            if vals == [PART_OUT_OF_LIST]:
                continue
            if tuple(p.partition_values_python) < tuple(start_partition.partition_values_python):
                return p
        return None

    def has_maxvalue_partition(self) -> str | None:
        """Return the MAXVALUE partition name if present, else None."""
        if not self._partitions or self._partitions[0].partition_literal is None:
            return None
        if PART_OUT_OF_RANGE in self._partitions[0].partition_values_individual:
            return self._partitions[0].partition_name
        return None

    def has_default_partition(self, return_partition_object: bool = False) -> Any:
        """Return matching default partition name or object if present."""
        for p in self._partitions:
            vals = [v.upper() if isinstance(v, str) else v for v in p.partition_values_python]
            if vals == [PART_OUT_OF_LIST]:
                return p if return_partition_object else p.partition_name
        return None

    def split_partitions(
        self,
        filter_fn: Callable[[OffloadSourcePartition], bool],
    ) -> tuple[OffloadSourcePartitions, OffloadSourcePartitions]:
        """Split partitions into (matching, non_matching) OffloadSourcePartitions."""
        matched = [p for p in self._partitions if filter_fn(p)]
        unmatched = [p for p in self._partitions if not filter_fn(p)]
        return OffloadSourcePartitions(matched), OffloadSourcePartitions(unmatched)

    def apply_filter(self, filter_fn: Callable[[OffloadSourcePartition], bool]) -> None:
        """Keep only partitions matching filter_fn in place."""
        self._partitions = [p for p in self._partitions if filter_fn(p)]


class DiscoveryState(FrozenBaseStruct, frozen=True):
    """Hydrated source table and snapshot SCN captured during discovery."""

    frontend_type: str
    source_owner: str
    source_table_name: str
    iot_type: str | None
    partition_type: str | None
    subpartition_type: str | None
    partition_columns: tuple[str, ...]
    subpartition_columns: tuple[str, ...]
    columns: tuple[ColumnSpec, ...]
    partitions: tuple[SourcePartitionSlice, ...]
    snapshot_scn: int | None = None
    estimated_row_count: int = 0
    estimated_size_bytes: int = 0
    primary_key_columns: tuple[str, ...] = ()


class PriorMetadataState(FrozenBaseStruct, frozen=True):
    """Prior repository metadata and backend target existence state."""

    prior_metadata: OffloadMetadata | None = None
    backend_table_exists: bool = False
    existing_backend_columns: tuple[ColumnSpec, ...] = ()
    existing_partition_digits: int | None = None
    reset_backend_table: bool = False
    reset_hybrid_view: bool = False

    @property
    def is_incremental_continuation(self) -> bool:
        """Return whether a prior offload exists and is not being reset."""
        return self.prior_metadata is not None and self.backend_table_exists and not self.reset_backend_table


class PredicatePlan(FrozenBaseStruct, frozen=True):
    """Compiled frontend and backend SQL predicates for an offload slice."""

    ipa_predicate_type: str | None = None
    offload_predicate_dsl: str | None = None
    frontend_where_clause: str | None = None
    backend_where_clause: str | None = None
    verification_where_clause: str | None = None
    prior_where_clause: str | None = None
    bind_params: dict[str, str | int | float] = msgspec.field(default_factory=dict)


class PartitionBoundaryPlan(FrozenBaseStruct, frozen=True):
    """Resolved partition watermarks and chunked partition batches to offload."""

    offload_mode: OffloadMode
    offload_type: Literal["FULL", "INCREMENTAL"]
    prior_high_value_raw: str | None = None
    prior_high_value_literals: tuple[str, ...] = ()
    target_high_value_raw: str | None = None
    target_high_value_literals: tuple[str, ...] = ()
    partitions_to_offload: tuple[SourcePartitionSlice, ...] = ()
    partition_chunks: tuple[tuple[SourcePartitionSlice, ...], ...] = ()
    offload_by_subpartition: bool = False
    nothing_to_offload: bool = False


class SchemaEvolutionPlan(FrozenBaseStruct, frozen=True):
    """Resolved target table DDL, canonical column mappings, and synthetic partitioning."""

    backend_type: str
    target_owner: str
    target_table_name: str
    canonical_columns: tuple[ColumnSpec, ...]
    target_columns: tuple[ColumnSpec, ...]
    columns_to_add: tuple[ColumnSpec, ...] = ()
    partition_columns: tuple[str, ...] = ()
    partition_functions: tuple[str | None, ...] = ()
    synthetic_partition_digits: int | None = None
    sort_columns: tuple[str, ...] = ()
    create_backend_table: bool = False
    drop_backend_table_first: bool = False
    create_table_ddl: tuple[str, ...] = ()
    alter_table_ddl: tuple[str, ...] = ()
    ddl_file_path: str | None = None


class StagingTransportPlan(FrozenBaseStruct, frozen=True):
    """Transport method, staging URI, and extraction parallelism configuration."""

    transport_method: str
    staging_format: str
    staging_uri: str | None = None
    load_db_name: str | None = None
    load_table_name: str | None = None
    parallelism: int = 1
    offload_chunk_column: str | None = None
    offload_chunk_size: int | None = None
    preserve_load_table: bool = False
    compress_load_table: bool = False
    consistent_read_scn: int | None = None
    extraction_queries: tuple[str, ...] = ()


class BackendLoadPlan(FrozenBaseStruct, frozen=True):
    """Backend ingestion strategy, validation mode, and post-load steps."""

    ingest_strategy: Literal["DIRECT_LOAD", "STORAGE_WRITE_PENDING", "STAGED_INSERT"]
    verify_mode: str | None = None
    verify_parallelism: int = 1
    compute_backend_stats: bool = False
    pre_load_sql: tuple[str, ...] = ()
    load_sql: tuple[str, ...] = ()
    post_load_sql: tuple[str, ...] = ()


class OffloadPlan(FrozenBaseStruct, frozen=True):
    """Complete immutable execution blueprint produced before any target side effects."""

    execution_id: str
    execute: bool
    discovery: DiscoveryState
    prior_state: PriorMetadataState
    boundary: PartitionBoundaryPlan
    predicate: PredicatePlan
    schema_plan: SchemaEvolutionPlan
    transport_plan: StagingTransportPlan
    load_plan: BackendLoadPlan
    planned_metadata: OffloadMetadata | None = None

    @property
    def has_nothing_to_offload(self) -> bool:
        """Return True when boundary resolution found zero qualifying partitions or rows."""
        return self.boundary.nothing_to_offload and not self.schema_plan.create_backend_table


class OffloadExecutionReport(FrozenBaseStruct, frozen=True):
    """Final execution summary returned by OffloadPlanExecutor and OffloadPipeline."""

    execution_id: str
    source_owner: str
    source_table_name: str
    target_owner: str
    target_table_name: str
    executed: bool
    status: Literal["SUCCESS", "NO_OP", "DRY_RUN"]
    rows_transported: int = 0
    rows_loaded: int = 0
    bytes_transported: int = 0
    chunks_executed: int = 0
    verified: bool = False
    saved_metadata: OffloadMetadata | None = None
