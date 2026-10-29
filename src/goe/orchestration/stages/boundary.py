# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Pure partition boundary, IPA watermark, chunking, and predicate resolution stage."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from goe.config.options import OffloadOperationOptions
from goe.exceptions import OffloadException
from goe.offload import offload_constants
from goe.offload.offload_messages import VVERBOSE, OffloadMessages
from goe.offload.offload_metadata_functions import (
    OFFLOAD_TYPE_FULL,
    OFFLOAD_TYPE_INCREMENTAL,
    decode_metadata_incremental_high_values_from_metadata,
    incremental_key_csv_from_part_keys,
)
from goe.offload.offload_source_table import OFFLOAD_PARTITION_TYPE_LIST
from goe.offload.option_validation import active_data_append_options
from goe.offload.predicates import PredicateCompiler
from goe.offload.registry import create_source_table
from goe.orchestration.models import (
    DiscoveryState,
    OffloadMode,
    OffloadSourcePartition,
    OffloadSourcePartitions,
    PartitionBoundaryPlan,
    PredicatePlan,
    PriorMetadataState,
    SourcePartitionSlice,
)
from goe.persistence.models import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPES_WITH_PREDICATE_IN_HV,
    hwm_column_names_from_predicates,
)

if TYPE_CHECKING:
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_source_table import OffloadSourceTableInterface
    from goe.orchestration.stages.plan_resolution import OffloadOperation

__all__ = [
    "INCREMENTAL_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT",
    "INVALID_HV_FOR_LIST_AS_RANGE_EXCEPTION_TEXT",
    "IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT",
    "LAPBO_TYPE_90_10",
    "LAPBO_TYPE_100_0",
    "LAPBO_TYPE_100_10",
    "MAX_QUERY_OPTIMISTIC_PRUNE_CLAUSE",
    "NO_DEFAULT_PARTITION_NOTICE_TEXT",
    "NO_MATCHING_PARTITION_EXCEPTION_TEXT",
    "NO_MAXVALUE_PARTITION_NOTICE_TEXT",
    "OFFLOAD_SOURCE_CLIENT_OFFLOAD",
    "OFFLOAD_TYPE_CHANGE_FOR_PBO_EXCEPTION_TEXT",
    "PREDICATE_APPEND_HWM_MESSAGE_TEXT",
    "PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT",
    "PREDICATE_TYPE_NO_MODIFY_HV_EXCEPTION_TEXT",
    "PREDICATE_TYPE_NO_MODIFY_RESET_EXCEPTION_TEXT",
    "PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT",
    "PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT",
    "RANGE_AND_PREDICATE_WITHOUT_PART_KEY_EXCEPTION_TEXT",
    "TOO_MANY_PARTITION_NAMES_EXCEPTION_TEXT",
    "BoundaryResolutionStage",
    "OffloadSourceDataException",
    "OffloadSourceDataInterface",
    "OffloadSourceDataIpaRange",
    "OffloadSourcePartition",
    "OffloadSourcePartitions",
    "chunk_partitions",
    "get_current_offload_hv",
    "get_offload_data_manager",
    "get_offload_type_for_config",
    "get_prior_offloaded_hv",
    "is_default_partition",
    "offload_source_data_factory",
    "offload_type_force_effects",
]


class OffloadSourceDataException(Exception):
    """Exception raised during partition boundary and source data resolution."""


OFFLOAD_SOURCE_CLIENT_OFFLOAD = "offload"
LAPBO_TYPE_90_10 = "90/10"
LAPBO_TYPE_100_10 = "100/10"
LAPBO_TYPE_100_0 = "100/0"
MAX_QUERY_OPTIMISTIC_PRUNE_CLAUSE = "max_query_optimistic_prune_clause"

NO_DEFAULT_PARTITION_NOTICE_TEXT = f"with high_value of {offload_constants.PART_OUT_OF_LIST}"
NO_MATCHING_PARTITION_EXCEPTION_TEXT = "No partition found matching name"
NO_MAXVALUE_PARTITION_NOTICE_TEXT = f"with high_value of {offload_constants.PART_OUT_OF_RANGE}"
INCREMENTAL_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT = "Offload type invalid when DEFAULT partition has been offloaded"
INVALID_HV_FOR_LIST_AS_RANGE_EXCEPTION_TEXT = (
    "Partitions have key values which are incompatible with LIST_AS_RANGE offloading"
)
IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT = f"Cannot offload {offload_constants.PART_OUT_OF_LIST} partition"
OFFLOAD_TYPE_CHANGE_FOR_PBO_EXCEPTION_TEXT = (
    "Switching between offload type FULL/INCREMENTAL is not supported for Predicate-Based Offload"
)
PREDICATE_APPEND_HWM_MESSAGE_TEXT = "Appended IPA high value to offload predicate"
PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT = "--offload-predicate is incompatible with INCREMENTAL_PREDICATE_TYPE"
PREDICATE_TYPE_NO_MODIFY_HV_EXCEPTION_TEXT = (
    "Option --no-modify-hybrid-view cannot be used with INCREMENTAL_PREDICATE_TYPE"
)
PREDICATE_TYPE_NO_MODIFY_RESET_EXCEPTION_TEXT = (
    "Options --no-modify-hybrid-view and --reset-hybrid-view are not compatible"
)
PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT = "OFFLOAD_TYPE FULL is not compatible with INCREMENTAL_PREDICATE_TYPE"
PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT = "--offload-predicate-type required for existing predicate type"
RANGE_AND_PREDICATE_WITHOUT_PART_KEY_EXCEPTION_TEXT = (
    "Offload predicate must contain a predicate for all existing partition key columns"
)
TOO_MANY_PARTITION_NAMES_EXCEPTION_TEXT = "Only one partition name can be included"


def is_default_partition(partition: Any) -> bool:
    """Return True if the partition represents an Oracle MAXVALUE or DEFAULT partition."""
    if isinstance(partition, SourcePartitionSlice):
        if partition.is_default:
            return True
        normalized = partition.high_value_raw.strip().upper()
        return normalized in {"MAXVALUE", "DEFAULT", offload_constants.PART_OUT_OF_LIST}
    part_vals = getattr(partition, "partition_values_python", None)
    if part_vals is not None:
        upper_vals = [s.upper() if isinstance(s, str) else s for s in part_vals]
        return upper_vals == [offload_constants.PART_OUT_OF_LIST]
    return False


def chunk_partitions(
    partitions: tuple[SourcePartitionSlice, ...],
    *,
    max_chunk_size_bytes: int | None = None,
    max_chunk_count: int | None = None,
) -> tuple[tuple[SourcePartitionSlice, ...], ...]:
    """Group ordered partition slices into chunks bounded by byte size and partition count."""
    if not partitions:
        return ()
    chunks: list[tuple[SourcePartitionSlice, ...]] = []
    current_chunk: list[SourcePartitionSlice] = []
    current_bytes = 0
    for part in partitions:
        exceeds_count = max_chunk_count is not None and max_chunk_count > 0 and len(current_chunk) >= max_chunk_count
        exceeds_size = (
            max_chunk_size_bytes is not None
            and max_chunk_size_bytes > 0
            and bool(current_chunk)
            and (current_bytes + part.byte_size) > max_chunk_size_bytes
        )
        if exceeds_count or exceeds_size:
            chunks.append(tuple(current_chunk))
            current_chunk = [part]
            current_bytes = part.byte_size
        else:
            current_chunk.append(part)
            current_bytes += part.byte_size
    if current_chunk:
        chunks.append(tuple(current_chunk))
    return tuple(chunks)


def get_offload_type_for_config(*args: Any, **kwargs: Any) -> Any:
    """Determine effective FULL or INCREMENTAL offload_type from table state and options."""
    if len(args) == 3 and isinstance(args[0], DiscoveryState):
        discovery: DiscoveryState = args[0]
        prior_state: PriorMetadataState = args[1]
        options: OffloadOperationOptions = args[2]
        return _get_offload_type_for_stage(discovery, prior_state, options)
    return _get_offload_type_legacy(*args, **kwargs)


class OffloadSourceDataIpaRange:
    """Compatibility range partition chunking helper for golden and unit partition tests."""

    def __init__(
        self,
        offload_source_table: Any,
        offload_target_table: Any,
        offload_operation: Any,
        existing_metadata: Any,
        messages: Any,
        client_type: str = OFFLOAD_SOURCE_CLIENT_OFFLOAD,
    ) -> None:
        """Initialize the compatibility range chunking helper."""
        self._offload_source_table = offload_source_table
        self._offload_target_table = offload_target_table
        self._offload_operation = offload_operation
        self._existing_metadata = existing_metadata
        self._messages = messages
        self._client_type = client_type
        self._user_requested_max_offload_chunk_size = int(
            getattr(offload_operation, "max_offload_chunk_size", 1_000_000_000) or 1_000_000_000
        )
        self._user_requested_max_offload_chunk_count = int(
            getattr(offload_operation, "max_offload_chunk_count", 100) or 100
        )
        self._partitions_to_offload = OffloadSourcePartitions()

    @property
    def partitions_to_offload(self) -> OffloadSourcePartitions:
        """Return partitions currently staged for offload."""
        return self._partitions_to_offload

    def get_partitions_to_offload_chunks(
        self,
    ) -> Iterator[tuple[OffloadSourcePartitions, OffloadSourcePartitions]]:
        """Yield (chunk_partitions, remaining_partitions) pairs bounded by size and count."""
        remaining = self._partitions_to_offload.get_partitions()[:]
        remaining.reverse()
        while remaining:
            chunk = [remaining.pop(0)]
            chunk_size = chunk[0].size_in_bytes or 0
            while (
                remaining
                and (chunk_size + (remaining[0].size_in_bytes or 0)) < self._user_requested_max_offload_chunk_size
                and len(chunk) < self._user_requested_max_offload_chunk_count
            ):
                p = remaining.pop(0)
                chunk.append(p)
                chunk_size += p.size_in_bytes or 0
            with_matching_hwm = self._partitions_of_matching_hwm(chunk[-1].partition_values_python, remaining)
            if with_matching_hwm:
                chunk.extend(with_matching_hwm)
                remaining = remaining[len(with_matching_hwm) :]
            chunk.reverse()
            yield (
                OffloadSourcePartitions(chunk),
                OffloadSourcePartitions(remaining[:]),
            )

    def _override_partitions_to_offload(self, new_partitions: OffloadSourcePartitions | list[Any]) -> None:
        """Override the partitions to offload collection."""
        if isinstance(new_partitions, OffloadSourcePartitions):
            self._partitions_to_offload = new_partitions
        else:
            self._partitions_to_offload = OffloadSourcePartitions(new_partitions)

    def _partitions_of_matching_hwm(
        self,
        hwm_values: Any,
        remaining: list[OffloadSourcePartition],
    ) -> list[OffloadSourcePartition]:
        """Return contiguous leading partitions from remaining that share hwm_values."""
        matched: list[OffloadSourcePartition] = []
        for p in remaining:
            if p.partition_values_python == hwm_values:
                matched.append(p)
            else:
                break
        return matched


OffloadSourceDataInterface = Any


def offload_source_data_factory(
    offload_source_table: Any,
    offload_target_table: Any,
    offload_operation: Any,
    hybrid_metadata: Any,
    messages: Any,
    source_client_type: str = OFFLOAD_SOURCE_CLIENT_OFFLOAD,
    rdbms_partition_columns_override: Any = None,
    col_offload_source_table_override: Any = None,
) -> Any:
    """Construct a source data client adapter for partition chunking."""
    del rdbms_partition_columns_override, col_offload_source_table_override
    return OffloadSourceDataIpaRange(
        offload_source_table,
        offload_target_table,
        offload_operation,
        hybrid_metadata,
        messages,
        client_type=source_client_type,
    )


class BoundaryResolutionStage:
    """Resolve partition watermarks, partition chunks, and SQL predicates without side effects."""

    def __init__(self, predicate_compiler: PredicateCompiler) -> None:
        """Initialize the boundary resolution stage with a dialect PredicateCompiler."""
        self._predicate_compiler = predicate_compiler

    def run(
        self,
        discovery: DiscoveryState,
        prior_state: PriorMetadataState,
        options: OffloadOperationOptions,
        *,
        backend_dialect: str,
    ) -> tuple[PartitionBoundaryPlan, PredicatePlan]:
        """Compute immutable PartitionBoundaryPlan and PredicatePlan for the discovered table."""
        prior_meta = prior_state.prior_metadata if prior_state.is_incremental_continuation else None
        ipa_type = self._resolve_ipa_predicate_type(discovery, prior_meta, options)

        if options.offload_predicate is not None or ipa_type == "PREDICATE":
            return self._resolve_predicate_offload(
                discovery,
                prior_meta,
                options,
                ipa_type=ipa_type or "PREDICATE",
                backend_dialect=backend_dialect,
            )

        if discovery.partition_type == "RANGE" or ipa_type == "LIST_AS_RANGE":
            return self._resolve_range_boundary(
                discovery,
                prior_meta,
                options,
                ipa_type=ipa_type or "RANGE",
                backend_dialect=backend_dialect,
            )

        if discovery.partition_type == "LIST":
            return self._resolve_list_boundary(
                discovery,
                prior_meta,
                options,
                ipa_type=ipa_type or "LIST",
            )

        return self._resolve_full_table(discovery, options)

    def _resolve_ipa_predicate_type(
        self,
        discovery: DiscoveryState,
        prior_meta: object | None,
        options: OffloadOperationOptions,
    ) -> str | None:
        """Validate and resolve the effective IPA predicate type against prior metadata."""
        prior_ipa = getattr(prior_meta, "incremental_predicate_type", None) if prior_meta else None
        requested = options.ipa_predicate_type
        if prior_ipa and requested and requested != prior_ipa:
            raise OffloadException(PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT)
        if (
            prior_ipa
            and options.offload_predicate is not None
            and prior_ipa
            not in {
                "PREDICATE",
                "RANGE_AND_PREDICATE",
                "LIST_AS_RANGE_AND_PREDICATE",
            }
        ):
            raise OffloadException(PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT)
        if requested:
            return requested
        if prior_ipa:
            return str(prior_ipa)
        if options.offload_predicate is not None:
            return "PREDICATE"
        return discovery.partition_type

    def _resolve_predicate_offload(
        self,
        discovery: DiscoveryState,
        prior_meta: object | None,
        options: OffloadOperationOptions,
        *,
        ipa_type: str,
        backend_dialect: str,
    ) -> tuple[PartitionBoundaryPlan, PredicatePlan]:
        """Compile predicate-based offload (PBO) clauses via PredicateCompiler."""
        if options.offload_type == "FULL":
            raise OffloadException(PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT)
        if options.offload_predicate is None:
            raise OffloadException(PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT)

        raw_predicate = options.offload_predicate
        predicate_dsl = raw_predicate.dsl if hasattr(raw_predicate, "dsl") else str(raw_predicate)
        frontend_sql = self._predicate_compiler.compile_predicate(
            raw_predicate,
            dialect=discovery.frontend_type.lower(),
            columns=discovery.columns,
        )
        backend_sql = self._predicate_compiler.compile_predicate(
            raw_predicate,
            dialect=backend_dialect,
            columns=discovery.columns,
        )
        boundary = PartitionBoundaryPlan(
            offload_mode="PREDICATE",
            offload_type="INCREMENTAL",
            prior_high_value_raw=getattr(prior_meta, "incremental_high_value", None),
            target_high_value_raw=getattr(prior_meta, "incremental_high_value", None),
            nothing_to_offload=False,
        )
        predicate = PredicatePlan(
            ipa_predicate_type=ipa_type,
            offload_predicate_dsl=predicate_dsl,
            frontend_where_clause=frontend_sql,
            backend_where_clause=backend_sql,
            verification_where_clause=backend_sql,
        )
        return boundary, predicate

    def _resolve_range_boundary(
        self,
        discovery: DiscoveryState,
        prior_meta: object | None,
        options: OffloadOperationOptions,
        *,
        ipa_type: str,
        backend_dialect: str,
    ) -> tuple[PartitionBoundaryPlan, PredicatePlan]:
        """Resolve RANGE or LIST_AS_RANGE partition watermarks and chunked slices."""
        effective_type = _get_offload_type_for_stage(
            discovery,
            PriorMetadataState(
                prior_metadata=prior_meta,  # type: ignore[arg-type]
                backend_table_exists=prior_meta is not None,
            ),
            options,
        )
        prior_hv = getattr(prior_meta, "incremental_high_value", None) if prior_meta else None
        target_literal = (
            str(options.less_than_value)
            if options.less_than_value is not None
            else (str(options.older_than_date) if options.older_than_date else None)
        )

        if effective_type == "FULL" and target_literal is None and prior_hv is None:
            return self._resolve_full_table(discovery, options)

        qualifying: list[SourcePartitionSlice] = []
        target_hv_raw: str | None = None
        target_hv_literals: tuple[str, ...] = ()

        for part in discovery.partitions:
            if is_default_partition(part):
                if target_literal is not None and target_literal.upper() in {"MAXVALUE", "DEFAULT"}:
                    raise OffloadException(IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT)
                if target_literal is not None or effective_type == "INCREMENTAL":
                    continue
            if prior_hv is not None and part.high_value_raw <= str(prior_hv):
                continue
            if target_literal is not None and part.high_value_raw > target_literal:
                continue
            qualifying.append(part)
            target_hv_raw = part.high_value_raw
            target_hv_literals = part.high_value_literals

        if not qualifying and prior_hv is None and target_literal is not None:
            raise OffloadException(NO_MATCHING_PARTITION_EXCEPTION_TEXT)

        slices = tuple(qualifying)
        max_size = int(options.max_offload_chunk_size) if isinstance(options.max_offload_chunk_size, int) else None
        max_count = int(options.max_offload_chunk_count) if isinstance(options.max_offload_chunk_count, int) else None
        chunks = chunk_partitions(
            slices,
            max_chunk_size_bytes=max_size,
            max_chunk_count=max_count,
        )
        part_col = discovery.partition_columns[0] if discovery.partition_columns else None
        where_parts: list[str] = []
        if part_col and prior_hv is not None:
            where_parts.append(f"{part_col} >= {prior_hv}")
        if part_col and target_hv_raw is not None:
            where_parts.append(f"{part_col} < {target_hv_raw}")
        where_clause = " AND ".join(where_parts) if where_parts else None

        mode: OffloadMode = "INCREMENTAL_LIST_AS_RANGE" if ipa_type == "LIST_AS_RANGE" else "INCREMENTAL_RANGE"
        boundary = PartitionBoundaryPlan(
            offload_mode=mode,
            offload_type="INCREMENTAL" if effective_type == "INCREMENTAL" else "FULL",
            prior_high_value_raw=str(prior_hv) if prior_hv is not None else None,
            target_high_value_raw=target_hv_raw or (str(prior_hv) if prior_hv else None),
            target_high_value_literals=target_hv_literals,
            partitions_to_offload=slices,
            partition_chunks=chunks,
            offload_by_subpartition=bool(discovery.subpartition_type and any(p.subpartition_names for p in slices)),
            nothing_to_offload=len(slices) == 0,
        )
        predicate = PredicatePlan(
            ipa_predicate_type=ipa_type,
            frontend_where_clause=where_clause,
            backend_where_clause=where_clause,
            verification_where_clause=where_clause,
            prior_where_clause=(f"{part_col} < {prior_hv}" if part_col and prior_hv is not None else None),
        )
        return boundary, predicate

    def _resolve_list_boundary(
        self,
        discovery: DiscoveryState,
        prior_meta: object | None,
        options: OffloadOperationOptions,
        *,
        ipa_type: str,
    ) -> tuple[PartitionBoundaryPlan, PredicatePlan]:
        """Resolve LIST partition watermarks and filter out previously offloaded value sets."""
        effective_type = _get_offload_type_for_stage(
            discovery,
            PriorMetadataState(
                prior_metadata=prior_meta,  # type: ignore[arg-type]
                backend_table_exists=prior_meta is not None,
            ),
            options,
        )
        prior_hv_raw = getattr(prior_meta, "incremental_high_value", None) if prior_meta else None
        prior_values: set[str] = (
            {v.strip() for v in str(prior_hv_raw).split(",") if v.strip()} if prior_hv_raw else set()
        )
        requested_values = set(options.equal_to_values or ())

        if effective_type == "FULL" and not requested_values and not prior_values:
            return self._resolve_full_table(discovery, options)

        qualifying: list[SourcePartitionSlice] = []
        accumulated_literals: list[str] = list(prior_values)

        for part in discovery.partitions:
            if is_default_partition(part):
                if requested_values and ("DEFAULT" in requested_values or "MAXVALUE" in requested_values):
                    raise OffloadException(IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT)
                continue
            part_vals = set(part.high_value_literals) or {part.high_value_raw}
            if part_vals.issubset(prior_values):
                continue
            if requested_values and not part_vals.intersection(requested_values):
                continue
            qualifying.append(part)
            for lit in part.high_value_literals or (part.high_value_raw,):
                if lit not in accumulated_literals:
                    accumulated_literals.append(lit)

        slices = tuple(qualifying)
        max_size = int(options.max_offload_chunk_size) if isinstance(options.max_offload_chunk_size, int) else None
        max_count = int(options.max_offload_chunk_count) if isinstance(options.max_offload_chunk_count, int) else None
        chunks = chunk_partitions(
            slices,
            max_chunk_size_bytes=max_size,
            max_chunk_count=max_count,
        )
        new_literals: list[str] = [
            lit for part in slices for lit in (part.high_value_literals or (part.high_value_raw,))
        ]
        part_col = discovery.partition_columns[0] if discovery.partition_columns else None
        where_clause = f"{part_col} IN ({', '.join(new_literals)})" if part_col and new_literals else None
        boundary = PartitionBoundaryPlan(
            offload_mode="INCREMENTAL_LIST",
            offload_type="INCREMENTAL",
            prior_high_value_raw=str(prior_hv_raw) if prior_hv_raw else None,
            prior_high_value_literals=tuple(sorted(prior_values)),
            target_high_value_raw=", ".join(accumulated_literals) if accumulated_literals else None,
            target_high_value_literals=tuple(accumulated_literals),
            partitions_to_offload=slices,
            partition_chunks=chunks,
            nothing_to_offload=len(slices) == 0,
        )
        predicate = PredicatePlan(
            ipa_predicate_type=ipa_type,
            frontend_where_clause=where_clause,
            backend_where_clause=where_clause,
            verification_where_clause=where_clause,
        )
        return boundary, predicate

    def _resolve_full_table(
        self,
        discovery: DiscoveryState,
        options: OffloadOperationOptions,
    ) -> tuple[PartitionBoundaryPlan, PredicatePlan]:
        """Resolve a full table offload (partitioned or non-partitioned)."""
        slices = discovery.partitions
        max_size = int(options.max_offload_chunk_size) if isinstance(options.max_offload_chunk_size, int) else None
        max_count = int(options.max_offload_chunk_count) if isinstance(options.max_offload_chunk_count, int) else None
        chunks = chunk_partitions(
            slices,
            max_chunk_size_bytes=max_size,
            max_chunk_count=max_count,
        )
        boundary = PartitionBoundaryPlan(
            offload_mode="FULL",
            offload_type="FULL",
            partitions_to_offload=slices,
            partition_chunks=chunks,
            nothing_to_offload=False,
        )
        predicate = PredicatePlan()
        return boundary, predicate


def get_current_offload_hv(
    offload_source_table: OffloadSourceTableInterface,
    source_data_client: OffloadSourceDataInterface,
    offload_operation: Any,
    messages: OffloadMessages,
) -> Any:
    """Identify the high watermark for an incremental partition append offload."""
    new_hvs = None

    if source_data_client.partitions_to_offload.count() > 0:
        if offload_operation.ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST:
            hvs_individual, hvs_python = [], []
            for p in source_data_client.partitions_to_offload.get_partitions():
                hvs_individual.append(p.partition_values_individual)
                hvs_python.append(p.partition_values_python)
            new_hvs = [hvs_individual, hvs_python]
        else:
            max_partition = source_data_client.partitions_to_offload.get_partition_by_index(0)
            new_hvs = [
                max_partition.partition_values_individual,
                max_partition.partition_values_python,
            ]
        messages.log(
            "Identified new_hvs from partitions_to_offload: %s" % str(new_hvs),
            detail=VVERBOSE,
        )
    elif offload_operation.offload_type == "INCREMENTAL" and not offload_operation.reset_backend_table:
        current_metadata = offload_operation.get_hybrid_metadata()
        (
            _,
            _,
            partition_literal_hvs,
        ) = decode_metadata_incremental_high_values_from_metadata(current_metadata, offload_source_table)
        new_hvs = [partition_literal_hvs, partition_literal_hvs]
        messages.log("Identified new_hvs from metadata: %s" % str(new_hvs), detail=VVERBOSE)

    return new_hvs


def get_prior_offloaded_hv(
    rdbms_table: OffloadSourceTableInterface,
    source_data_client: OffloadSourceDataInterface,
    offload_operation: Any,
    messages: OffloadMessages,
) -> Any:
    """Identify the prior offloaded partition high watermark for a RANGE offload."""
    prior_hvs = None

    if (
        offload_operation
        and offload_operation.pre_offload_hybrid_metadata
        and offload_operation.pre_offload_hybrid_metadata.incremental_high_value
    ):
        messages.log("Assigning prior_hv from pre-offload metadata", detail=VVERBOSE)
        (
            _,
            real_hvs,
            literal_hvs,
        ) = decode_metadata_incremental_high_values_from_metadata(
            offload_operation.pre_offload_hybrid_metadata, rdbms_table
        )
        messages.log("pre-offload metadata real values: %s" % str(real_hvs), detail=VVERBOSE)
        messages.log(
            "pre-offload metadata rdbms literals: %s" % str(literal_hvs),
            detail=VVERBOSE,
        )
        prior_hvs = [literal_hvs, real_hvs]

    if not prior_hvs and source_data_client:
        min_offloaded_partition = source_data_client.partitions_to_offload.get_partition_by_index(-1)
        if min_offloaded_partition:
            messages.log(
                "Searching original partitions for partition prior to: %s"
                % str(min_offloaded_partition.partition_values_python),
                detail=VVERBOSE,
            )
            prior_partition = source_data_client.source_partitions.get_prior_partition(
                partition=min_offloaded_partition
            )
            if prior_partition:
                prior_hvs = [
                    prior_partition.partition_values_individual,
                    prior_partition.partition_values_python,
                ]

    messages.log("Found prior_hvs: %s" % str(prior_hvs), detail=VVERBOSE)
    return prior_hvs


def get_offload_data_manager(
    offload_source_table: OffloadSourceTableInterface,
    offload_target_table: BackendTableInterface,
    offload_operation: OffloadOperation,
    offload_options: Any,
    messages: OffloadMessages,
    existing_metadata: Any,
    source_client_type: Any,
    partition_columns: Any = None,
    include_col_offload_source_table: bool = False,
) -> OffloadSourceDataInterface:
    """Construct and run partition detection on the OffloadSourceDataInterface manager."""
    if (
        offload_target_table.exists()
        and not offload_target_table.is_view()
        and not offload_operation.reset_backend_table
    ):
        messages.log("Pre-offload metadata: " + str(existing_metadata), detail=VVERBOSE)

    if include_col_offload_source_table and existing_metadata:
        col_offload_source_table_override = create_source_table(
            existing_metadata.hybrid_owner,
            existing_metadata.hybrid_view,
            offload_options,
            messages,
            offload_by_subpartition=offload_source_table.offload_by_subpartition,
        )
    else:
        col_offload_source_table_override = None

    source_data_client = offload_source_data_factory(
        offload_source_table,
        offload_target_table,
        offload_operation,
        existing_metadata,
        messages,
        source_client_type,
        rdbms_partition_columns_override=partition_columns,
        col_offload_source_table_override=col_offload_source_table_override,
    )

    source_data_client.offload_data_detection()

    return source_data_client


def offload_type_force_effects(
    hybrid_operation: OffloadOperation,
    source_data_client: OffloadSourceDataInterface,
    original_metadata: Any,
    offload_source_table: OffloadSourceTableInterface,
    messages: OffloadMessages,
) -> None:
    """Validate and apply force flags when switching OFFLOAD_TYPE or incremental keys."""
    if source_data_client.is_incremental_append_capable():
        original_offload_type = original_metadata.offload_type
        new_offload_type = hybrid_operation.offload_type
        if hybrid_operation.offload_by_subpartition and (
            original_offload_type,
            new_offload_type,
        ) == ("FULL", "INCREMENTAL"):
            raise OffloadException(offload_constants.OFFLOAD_TYPE_CHANGE_FOR_SUBPART_EXCEPTION_TEXT)

        if hybrid_operation.ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST and (
            original_offload_type,
            new_offload_type,
        ) == ("FULL", "INCREMENTAL"):
            active_lpa_opts = active_data_append_options(hybrid_operation, partition_type=OFFLOAD_PARTITION_TYPE_LIST)
            if active_lpa_opts:
                messages.notice(
                    "%s, only the partitions identified by %s will be queried from offloaded data"
                    % (
                        offload_constants.OFFLOAD_TYPE_CHANGE_FOR_LIST_MESSAGE_TEXT,
                        active_lpa_opts[0],
                    )
                )
            else:
                raise OffloadException(offload_constants.OFFLOAD_TYPE_CHANGE_FOR_LIST_EXCEPTION_TEXT)

        if not hybrid_operation.force:
            new_inc_key = None
            original_inc_key = original_metadata.incremental_key
            if hybrid_operation.hwm_in_hybrid_view and source_data_client.get_incremental_high_values():
                new_inc_key = incremental_key_csv_from_part_keys(offload_source_table.partition_columns)

            original_pred_cols, new_pred_cols = None, None
            if hybrid_operation.ipa_predicate_type in INCREMENTAL_PREDICATE_TYPES_WITH_PREDICATE_IN_HV:
                original_pred_cols = original_metadata.hwm_column_names()
                new_pred_cols = hwm_column_names_from_predicates(source_data_client.get_post_offload_predicates())

            if original_offload_type != new_offload_type:
                messages.notice(
                    'Enabling force option when switching OFFLOAD_TYPE ("%s" -> "%s")'
                    % (original_offload_type, new_offload_type)
                )
                hybrid_operation.force = True
            elif original_inc_key != new_inc_key:
                messages.notice(
                    'Enabling force option when switching INCREMENTAL_KEY ("%s" -> "%s")'
                    % (original_inc_key, new_inc_key)
                )
                hybrid_operation.force = True
            elif original_pred_cols != new_pred_cols and not source_data_client.nothing_to_offload():
                messages.notice(
                    'Enabling force option when columns in INCREMENTAL_PREDICATE_VALUE change ("%s" -> "%s")'
                    % (original_pred_cols, new_pred_cols)
                )
                hybrid_operation.force = True


def _get_offload_type_for_stage(
    discovery: DiscoveryState,
    prior_state: PriorMetadataState,
    options: OffloadOperationOptions,
) -> str:
    """Determine effective FULL or INCREMENTAL offload_type for staged boundary resolution."""
    partition_names = getattr(options, "partition_names", None) or options.partition_names_csv
    has_boundary_option = any(
        (
            options.older_than_date is not None,
            options.older_than_days is not None,
            options.less_than_value is not None,
            bool(options.equal_to_values),
            bool(partition_names),
        )
    )
    if options.offload_predicate is not None:
        return "INCREMENTAL"
    if not discovery.partition_type:
        return "FULL"
    if has_boundary_option:
        return "INCREMENTAL"
    if prior_state.is_incremental_continuation and prior_state.prior_metadata is not None:
        if prior_state.prior_metadata.incremental_key is not None:
            return options.offload_type or "INCREMENTAL"
    return options.offload_type or "FULL"


def _get_offload_type_legacy(
    owner: str,
    table_name: str,
    user_requested_offload_type: str | None,
    incr_append_capable: bool,
    ida_options_specified: Any,
    hybrid_metadata: Any,
    messages: Any,
    with_messages: bool = True,
) -> tuple[str, bool]:
    """Legacy 7/8-argument get_offload_type_for_config returning (offload_type, pred_for_90_10_in_hybrid_view)."""
    offload_type = OFFLOAD_TYPE_FULL
    pred_for_90_10_in_hybrid_view = False

    if user_requested_offload_type:
        offload_type = user_requested_offload_type
        if offload_type == OFFLOAD_TYPE_INCREMENTAL and not incr_append_capable:
            if with_messages:
                messages.warning(
                    'Offload type %s incompatible with table %s.%s, continuing with type "FULL"'
                    % (offload_type, owner, table_name),
                    ansi_type="red",
                )
            offload_type = OFFLOAD_TYPE_FULL
    elif hybrid_metadata:
        offload_type = hybrid_metadata.offload_type
        if hybrid_metadata.incremental_high_value or hybrid_metadata.incremental_predicate_value:
            if with_messages:
                if hybrid_metadata.incremental_high_value:
                    messages.log(
                        "Including HWM in hybrid view due to existing INCREMENTAL_HIGH_VALUE metadata",
                        detail=VVERBOSE,
                    )
                else:
                    messages.log(
                        "Including HWM in hybrid view due to existing INCREMENTAL_PREDICATE_VALUE metadata",
                        detail=VVERBOSE,
                    )
            pred_for_90_10_in_hybrid_view = True
    elif incr_append_capable and ida_options_specified:
        offload_type = OFFLOAD_TYPE_INCREMENTAL

    if not pred_for_90_10_in_hybrid_view:
        if offload_type == OFFLOAD_TYPE_INCREMENTAL:
            pred_for_90_10_in_hybrid_view = True
        elif ida_options_specified:
            if with_messages:
                messages.log(
                    "Including HWM in hybrid view due to command options",
                    detail=VVERBOSE,
                )
            pred_for_90_10_in_hybrid_view = True

    return offload_type, pred_for_90_10_in_hybrid_view
