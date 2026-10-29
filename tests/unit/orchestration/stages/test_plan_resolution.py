# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SchemaAndTransportPlanningStage in goe.orchestration.stages.plan_resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from goe.config.options import OffloadOperationOptions
from goe.offload.schema.column_spec import ColumnDialect, ColumnSpec
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.models import (
    DiscoveryState,
    PartitionBoundaryPlan,
    PredicatePlan,
    PriorMetadataState,
    SourcePartitionSlice,
)
from goe.orchestration.stages.plan_resolution import SchemaAndTransportPlanningStage
from goe.persistence.models import OffloadMetadata


def test_plan_resolution_builds_complete_immutable_offload_plan_for_new_table() -> None:
    """Verify SchemaAndTransportPlanningStage.run builds OffloadPlan for a new table without executing DDL."""
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    backend_planner, transport_planner = _mock_planners(col)
    stage = SchemaAndTransportPlanningStage(backend_planner, transport_planner)

    discovery = _sample_discovery(col)
    prior_state = PriorMetadataState(backend_table_exists=False)
    boundary = PartitionBoundaryPlan(offload_mode="FULL", offload_type="FULL")
    predicate = PredicatePlan()
    options = OffloadOperationOptions(
        owner="SH",
        table_name="SALES",
        execute=True,
        sort_columns_csv="ID",
    )
    exec_id = ExecutionId().as_str()
    plan = stage.run(
        execution_id=exec_id,
        discovery=discovery,
        prior_state=prior_state,
        boundary=boundary,
        predicate=predicate,
        options=options,
        target_owner="sh",
        target_table_name="sales",
    )

    assert plan.execution_id == exec_id
    assert plan.schema_plan.create_backend_table is True
    assert plan.schema_plan.drop_backend_table_first is False
    assert plan.schema_plan.create_table_ddl == ("CREATE TABLE sh.sales (ID INT64);",)
    assert plan.transport_plan.transport_method == "DUCKDB"
    assert plan.load_plan.ingest_strategy == "DIRECT_LOAD"
    assert plan.planned_metadata is not None
    assert plan.planned_metadata.backend_owner == "sh"
    assert plan.planned_metadata.backend_table == "sales"


def test_plan_resolution_retains_existing_partition_digits_on_incremental_append() -> None:
    """Verify synthetic_partition_digits retains existing_partition_digits on incremental append."""
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    backend_planner, transport_planner = _mock_planners(col)
    stage = SchemaAndTransportPlanningStage(backend_planner, transport_planner)

    discovery = _sample_discovery(col)
    prior_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="ID",
        incremental_high_value="100",
    )
    prior_state = PriorMetadataState(
        prior_metadata=prior_meta,
        backend_table_exists=True,
        existing_backend_columns=(col,),
        existing_partition_digits=6,
    )
    boundary = PartitionBoundaryPlan(
        offload_mode="INCREMENTAL_RANGE",
        offload_type="INCREMENTAL",
        target_high_value_raw="200",
    )
    options = OffloadOperationOptions(
        owner="SH",
        table_name="SALES",
        synthetic_partition_digits=12,
    )
    plan = stage.run(
        execution_id=ExecutionId().as_str(),
        discovery=discovery,
        prior_state=prior_state,
        boundary=boundary,
        predicate=PredicatePlan(ipa_predicate_type="RANGE"),
        options=options,
        target_owner="sh",
        target_table_name="sales",
    )

    assert plan.schema_plan.create_backend_table is False
    assert plan.schema_plan.synthetic_partition_digits == 6


def test_plan_resolution_selects_staged_insert_when_preserve_load_table_or_chunk_column_set() -> None:
    """Verify ingest_strategy is STAGED_INSERT when preserve_load_table or offload_chunk_column is set."""
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    backend_planner, transport_planner = _mock_planners(col)
    stage = SchemaAndTransportPlanningStage(backend_planner, transport_planner)

    discovery = _sample_discovery(col)
    options = OffloadOperationOptions(
        owner="SH",
        table_name="SALES",
        preserve_load_table=True,
    )
    plan = stage.run(
        execution_id=ExecutionId().as_str(),
        discovery=discovery,
        prior_state=PriorMetadataState(),
        boundary=PartitionBoundaryPlan(offload_mode="FULL", offload_type="FULL"),
        predicate=PredicatePlan(),
        options=options,
        target_owner="sh",
        target_table_name="sales",
    )

    assert plan.load_plan.ingest_strategy == "STAGED_INSERT"


def test_plan_resolution_marks_drop_and_recreate_on_reset_backend_table() -> None:
    """Verify drop_backend_table_first and create_backend_table are True when resetting existing table."""
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    backend_planner, transport_planner = _mock_planners(col)
    stage = SchemaAndTransportPlanningStage(backend_planner, transport_planner)

    discovery = _sample_discovery(col)
    prior_state = PriorMetadataState(
        backend_table_exists=True,
        reset_backend_table=True,
    )
    options = OffloadOperationOptions(
        owner="SH",
        table_name="SALES",
        reset_backend_table=True,
    )
    plan = stage.run(
        execution_id=ExecutionId().as_str(),
        discovery=discovery,
        prior_state=prior_state,
        boundary=PartitionBoundaryPlan(offload_mode="FULL", offload_type="FULL"),
        predicate=PredicatePlan(),
        options=options,
        target_owner="sh",
        target_table_name="sales",
    )

    assert plan.schema_plan.drop_backend_table_first is True
    assert plan.schema_plan.create_backend_table is True


def _sample_discovery(col: ColumnSpec) -> DiscoveryState:
    part = SourcePartitionSlice(partition_name="P1", partition_position=1, high_value_raw="100")
    return DiscoveryState(
        frontend_type="ORACLE",
        source_owner="SH",
        source_table_name="SALES",
        iot_type=None,
        partition_type="RANGE",
        subpartition_type=None,
        partition_columns=("ID",),
        subpartition_columns=(),
        columns=(col,),
        partitions=(part,),
        snapshot_scn=123456,
    )


def _mock_planners(col: ColumnSpec) -> tuple[MagicMock, MagicMock]:
    backend_planner = MagicMock()
    backend_planner.backend_type = "BIGQUERY"
    backend_planner.map_source_to_canonical.return_value = (col,)
    backend_planner.map_canonical_to_target.return_value = (col,)
    backend_planner.generate_create_table_ddl.return_value = ("CREATE TABLE sh.sales (ID INT64);",)
    backend_planner.generate_add_columns_ddl.return_value = ()
    backend_planner.select_ingest_strategy.return_value = "DIRECT_LOAD"
    backend_planner.generate_load_sql.return_value = ("INSERT INTO sh.sales SELECT * FROM sh_load.sales;",)

    transport_planner = MagicMock()
    transport_planner.choose_transport_method.return_value = "DUCKDB"
    transport_planner.resolve_staging_location.return_value = (
        "PARQUET",
        "gs://bucket/sh/sales",
        "sh_load",
        "sales",
    )
    transport_planner.build_extraction_queries.return_value = ("SELECT ID FROM SH.SALES AS OF SCN 123456",)
    return backend_planner, transport_planner
