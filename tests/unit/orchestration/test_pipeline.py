# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OffloadPipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from goe.config.options import OffloadOperationOptions
from goe.offload.schema.column_spec import ColumnDialect, ColumnSpec
from goe.orchestration.models import (
    BackendLoadPlan,
    DiscoveryState,
    OffloadExecutionReport,
    OffloadPlan,
    PartitionBoundaryPlan,
    PredicatePlan,
    PriorMetadataState,
    SchemaEvolutionPlan,
    StagingTransportPlan,
)
from goe.orchestration.pipeline import OffloadPipeline


def test_offload_pipeline_plan_only_does_not_invoke_executor() -> None:
    """Verify OffloadPipeline.plan runs discovery, boundary, and planning stages with zero calls to executor."""
    discovery_stage, boundary_stage, planning_stage, executor, expected_plan = _mock_pipeline_components()
    pipeline = OffloadPipeline(
        discovery_stage=discovery_stage,
        boundary_stage=boundary_stage,
        planning_stage=planning_stage,
        executor=executor,
        backend_dialect="bigquery",
    )
    options = OffloadOperationOptions(owner="SH", table_name="SALES", execute=False)

    plan = pipeline.plan(options, execution_id="exec-123")

    assert plan == expected_plan
    discovery_stage.run.assert_called_once_with(
        options,
        target_owner="sh",
        target_table_name="sales",
    )
    boundary_stage.run.assert_called_once()
    planning_stage.run.assert_called_once()
    executor.execute.assert_not_called()


def test_offload_pipeline_run_executes_staged_plan_and_returns_report() -> None:
    """Verify OffloadPipeline.run builds an OffloadPlan and executes it via OffloadPlanExecutor."""
    discovery_stage, boundary_stage, planning_stage, executor, expected_plan = _mock_pipeline_components()
    expected_report = OffloadExecutionReport(
        execution_id="exec-456",
        source_owner="SH",
        source_table_name="SALES",
        target_owner="sh",
        target_table_name="sales",
        executed=True,
        status="SUCCESS",
        rows_transported=100,
        rows_loaded=100,
        verified=True,
    )
    executor.execute.return_value = expected_report

    pipeline = OffloadPipeline(
        discovery_stage=discovery_stage,
        boundary_stage=boundary_stage,
        planning_stage=planning_stage,
        executor=executor,
        backend_dialect="bigquery",
    )
    options = OffloadOperationOptions(owner="SH", table_name="SALES", execute=True)

    report = pipeline.run(options, execution_id="exec-456")

    assert report == expected_report
    executor.execute.assert_called_once_with(expected_plan)


def test_offload_pipeline_resolves_target_owner_and_table_name_casing() -> None:
    """Verify target owner/table naming and identifier case conversion rules match legacy OffloadOperation."""
    discovery_stage, boundary_stage, planning_stage, executor, _ = _mock_pipeline_components()

    pipeline_lower = OffloadPipeline(
        discovery_stage=discovery_stage,
        boundary_stage=boundary_stage,
        planning_stage=planning_stage,
        executor=executor,
        backend_dialect="bigquery",
        config=SimpleNamespace(backend_identifier_case="LOWER", db_name_pattern="%s"),
    )
    options_override = OffloadOperationOptions(
        owner="SH",
        table_name="SALES",
        target_owner_name="CUSTOM_DS.CUSTOM_SALES",
    )
    pipeline_lower.plan(options_override, execution_id="exec-1")
    discovery_stage.run.assert_called_with(
        options_override,
        target_owner="custom_ds",
        target_table_name="custom_sales",
    )

    pipeline_upper = OffloadPipeline(
        discovery_stage=discovery_stage,
        boundary_stage=boundary_stage,
        planning_stage=planning_stage,
        executor=executor,
        backend_dialect="snowflake",
        config=SimpleNamespace(backend_identifier_case="UPPER", db_name_pattern="PROD_%s"),
    )
    options_default = OffloadOperationOptions(owner="sh", table_name="sales")
    pipeline_upper.plan(options_default, execution_id="exec-2")
    discovery_stage.run.assert_called_with(
        options_default,
        target_owner="PROD_SH",
        target_table_name="SALES",
    )


def _mock_pipeline_components() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock, OffloadPlan]:
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    discovery = DiscoveryState(
        frontend_type="oracle",
        source_owner="SH",
        source_table_name="SALES",
        iot_type=None,
        partition_type=None,
        subpartition_type=None,
        partition_columns=(),
        subpartition_columns=(),
        columns=(col,),
        partitions=(),
    )
    prior_state = PriorMetadataState(backend_table_exists=False)
    boundary = PartitionBoundaryPlan(offload_mode="FULL", offload_type="FULL")
    predicate = PredicatePlan()
    expected_plan = OffloadPlan(
        execution_id="exec-123",
        execute=False,
        discovery=discovery,
        prior_state=prior_state,
        boundary=boundary,
        predicate=predicate,
        schema_plan=SchemaEvolutionPlan(
            backend_type="bigquery",
            target_owner="sh",
            target_table_name="sales",
            canonical_columns=(col,),
            target_columns=(col,),
            create_backend_table=True,
        ),
        transport_plan=StagingTransportPlan(
            transport_method="QUERY_IMPORT",
            staging_format="AVRO",
        ),
        load_plan=BackendLoadPlan(ingest_strategy="DIRECT_LOAD"),
    )

    discovery_stage = MagicMock()
    discovery_stage.run.return_value = (discovery, prior_state)

    boundary_stage = MagicMock()
    boundary_stage.run.return_value = (boundary, predicate)

    planning_stage = MagicMock()
    planning_stage.run.return_value = expected_plan

    executor = MagicMock()
    return discovery_stage, boundary_stage, planning_stage, executor, expected_plan
