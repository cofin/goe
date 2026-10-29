# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for immutable OffloadPlan and stage value objects in goe.orchestration.models."""

from __future__ import annotations

import gc
import tracemalloc

import pytest

from goe.offload.schema.column_spec import ColumnDialect, ColumnSpec
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.models import (
    BackendLoadPlan,
    DiscoveryState,
    OffloadExecutionReport,
    OffloadPlan,
    PartitionBoundaryPlan,
    PredicatePlan,
    PriorMetadataState,
    SchemaEvolutionPlan,
    SourcePartitionSlice,
    StagingTransportPlan,
)
from goe.persistence.models import OffloadMetadata
from goe.serializers import decode_json, encode_json


def test_models_are_frozen_and_untracked_by_gc() -> None:
    """Verify every stage model is frozen and excluded from cyclic GC tracking."""
    plan = _sample_offload_plan()
    report = OffloadExecutionReport(
        execution_id=plan.execution_id,
        source_owner="SH",
        source_table_name="SALES",
        target_owner="sh",
        target_table_name="sales",
        executed=True,
        status="SUCCESS",
        rows_transported=5000,
        rows_loaded=5000,
        bytes_transported=1048576,
        chunks_executed=1,
        verified=True,
        saved_metadata=plan.planned_metadata,
    )
    objects = (
        plan.discovery.partitions[0],
        plan.discovery,
        plan.prior_state,
        plan.boundary,
        plan.predicate,
        plan.schema_plan,
        plan.transport_plan,
        plan.load_plan,
        plan,
        report,
    )
    for obj in objects:
        assert not gc.is_tracked(obj)

    with pytest.raises(AttributeError):
        plan.execute = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        plan.discovery.partitions[0].partition_name = "MUTATED"  # type: ignore[misc]


def test_source_partition_slice_array_like_serialization() -> None:
    """Verify SourcePartitionSlice encodes as a compact JSON array and round-trips."""
    slice_obj = SourcePartitionSlice(
        partition_name="P_2025_01",
        partition_position=1,
        high_value_raw="TO_DATE('2025-02-01', 'YYYY-MM-DD')",
        high_value_literals=("'2025-02-01'",),
        byte_size=1048576,
        row_count=5000,
        subpartition_names=("SP1", "SP2"),
        is_default=False,
    )
    payload = encode_json(slice_obj)
    assert payload.startswith("[")
    assert payload.endswith("]")
    restored = decode_json(payload, target_type=SourcePartitionSlice)
    assert restored == slice_obj


def test_offload_plan_dry_run_summary_and_json_round_trip() -> None:
    """Verify OffloadPlan and OffloadExecutionReport round-trip through goe.serializers."""
    plan = _sample_offload_plan()
    assert plan.has_nothing_to_offload is False

    payload = encode_json(plan)
    restored = decode_json(payload, target_type=OffloadPlan)
    assert restored == plan

    report = OffloadExecutionReport(
        execution_id=plan.execution_id,
        source_owner="SH",
        source_table_name="SALES",
        target_owner="sh",
        target_table_name="sales",
        executed=False,
        status="DRY_RUN",
        rows_transported=0,
        rows_loaded=0,
        bytes_transported=0,
        chunks_executed=0,
        verified=False,
        saved_metadata=None,
    )
    assert decode_json(encode_json(report), target_type=OffloadExecutionReport) == report


def test_source_partition_slice_100k_memory_footprint_under_50mb() -> None:
    """Verify 100,000 SourcePartitionSlice instances allocate less than 50 MB of heap memory."""
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    slices = [
        SourcePartitionSlice(
            partition_name=f"P_{i:06d}",
            partition_position=i,
            high_value_raw="2025-01-01",
            high_value_literals=(str(i),),
            byte_size=65536,
            row_count=100,
            subpartition_names=(),
            is_default=False,
        )
        for i in range(100_000)
    ]
    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    allocated_bytes = sum(stat.size_diff for stat in stats if stat.size_diff > 0)
    assert len(slices) == 100_000
    assert not gc.is_tracked(slices[0])
    assert allocated_bytes < 50 * 1024 * 1024, f"Allocated {allocated_bytes} bytes (>= 50 MB)"


def _sample_offload_plan() -> OffloadPlan:
    col = ColumnSpec(
        dialect=ColumnDialect.ORACLE,
        name="ID",
        data_type="NUMBER",
        nullable=False,
        data_precision=10,
        data_scale=0,
    )
    part = SourcePartitionSlice(
        partition_name="P_2025_01",
        partition_position=1,
        high_value_raw="2025-02-01",
        high_value_literals=("'2025-02-01'",),
        byte_size=1048576,
        row_count=5000,
        subpartition_names=(),
        is_default=False,
    )
    exec_id = ExecutionId()
    metadata = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="TIME_ID",
        incremental_high_value="2025-02-01",
        incremental_predicate_type="RANGE",
        offload_snapshot=123456,
        command_execution=exec_id,
    )
    return OffloadPlan(
        execution_id=exec_id.as_str(),
        execute=True,
        discovery=DiscoveryState(
            frontend_type="ORACLE",
            source_owner="SH",
            source_table_name="SALES",
            iot_type=None,
            partition_type="RANGE",
            subpartition_type=None,
            partition_columns=("TIME_ID",),
            subpartition_columns=(),
            columns=(col,),
            partitions=(part,),
            snapshot_scn=123456,
            estimated_row_count=5000,
            estimated_size_bytes=1048576,
        ),
        prior_state=PriorMetadataState(
            prior_metadata=metadata,
            backend_table_exists=True,
            existing_backend_columns=(col,),
            existing_partition_digits=4,
        ),
        boundary=PartitionBoundaryPlan(
            offload_mode="INCREMENTAL_RANGE",
            offload_type="INCREMENTAL",
            prior_high_value_raw="2025-01-01",
            target_high_value_raw="2025-02-01",
            target_high_value_literals=("'2025-02-01'",),
            partitions_to_offload=(part,),
            partition_chunks=((part,),),
        ),
        predicate=PredicatePlan(
            ipa_predicate_type="RANGE",
            frontend_where_clause="TIME_ID >= '2025-01-01' AND TIME_ID < '2025-02-01'",
            backend_where_clause="TIME_ID >= '2025-01-01' AND TIME_ID < '2025-02-01'",
            verification_where_clause="TIME_ID >= '2025-01-01' AND TIME_ID < '2025-02-01'",
        ),
        schema_plan=SchemaEvolutionPlan(
            backend_type="BIGQUERY",
            target_owner="sh",
            target_table_name="sales",
            canonical_columns=(col,),
            target_columns=(col,),
            partition_columns=("TIME_ID",),
            sort_columns=("ID",),
        ),
        transport_plan=StagingTransportPlan(
            transport_method="DUCKDB",
            staging_format="PARQUET",
            staging_uri="gs://bucket/sh/sales",
            consistent_read_scn=123456,
        ),
        load_plan=BackendLoadPlan(
            ingest_strategy="DIRECT_LOAD",
            verify_mode="count",
        ),
        planned_metadata=metadata,
    )
