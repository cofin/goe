# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ListenerOperationsService dry-run offload preview."""

from __future__ import annotations

import pytest

from goe.config.options import OffloadOperationOptions
from goe.exceptions import OffloadException, OffloadOptionError
from goe.listener import exceptions, schemas
from goe.listener.mcp import ConfirmationGate
from goe.listener.services.operations import ListenerOperationsService
from goe.offload.schema.column_spec import ColumnDialect, ColumnSpec
from goe.orchestration.models import (
    BackendLoadPlan,
    DiscoveryState,
    OffloadPlan,
    PartitionBoundaryPlan,
    PredicatePlan,
    PriorMetadataState,
    SchemaEvolutionPlan,
    SourcePartitionSlice,
    StagingTransportPlan,
)


def test_preview_offload_forces_dry_run_and_mints_execute_token() -> None:
    """Verify preview_offload forces execute=False, projects OffloadPlan, and mints a ConfirmationChallenge."""
    captured_options: list[OffloadOperationOptions] = []

    def _fake_plan_builder(options: OffloadOperationOptions) -> tuple[OffloadPlan, list[str]]:
        captured_options.append(options)
        return _sample_plan(nothing_to_offload=False), ["Planned 2 partitions"]

    gate = ConfirmationGate(secret="ops-preview-secret", ttl_seconds=300)
    service = ListenerOperationsService(
        confirmation_gate=gate,
        plan_builder=_fake_plan_builder,
    )
    req_options = schemas.OffloadOptions(owner_table="SH.SALES", execute=True, reset_backend_table=True)
    preview = service.preview_offload(req_options)

    assert len(captured_options) == 1
    assert captured_options[0].execute is False
    assert preview.owner_table == "SH.SALES"
    assert preview.target_owner == "sh"
    assert preview.target_table == "sales"
    assert preview.offload_mode == "INCREMENTAL_RANGE"
    assert preview.offload_type == "INCREMENTAL"
    assert preview.nothing_to_offload is False
    assert preview.partition_names == ["P_2025_01", "P_2025_02"]
    assert preview.chunk_count == 1
    assert preview.estimated_row_count == 1500
    assert preview.estimated_size_bytes == 65536
    assert preview.transport_method == "DUCKDB"
    assert preview.staging_format == "PARQUET"
    assert preview.ingest_strategy == "DIRECT_LOAD"
    assert preview.create_backend_table is True
    assert preview.create_table_ddl == ["CREATE TABLE sh.sales (ID INT64);"]
    assert preview.alter_table_ddl == []
    assert preview.frontend_where_clause == "TIME_ID < DATE '2025-03-01'"
    assert preview.notices == ["Planned 2 partitions"]
    assert preview.confirmation_challenge is not None

    expected_execute_payload = {**req_options.to_params_dict(), "execute": True}
    assert gate.verify_token(
        token=preview.confirmation_challenge.confirmation_token,
        tool_name="execute_offload",
        owner_table="SH.SALES",
        payload=expected_execute_payload,
    )


def test_preview_offload_nothing_to_offload_omits_confirmation_challenge() -> None:
    """Verify nothing_to_offload=True plans return confirmation_challenge=None."""
    gate = ConfirmationGate(secret="ops-preview-secret", ttl_seconds=300)
    service = ListenerOperationsService(
        confirmation_gate=gate,
        plan_builder=lambda _opts: (_sample_plan(nothing_to_offload=True), ["No new partitions to offload"]),
    )
    preview = service.preview_offload(schemas.OffloadOptions(owner_table="SH.SALES", execute=False))
    assert preview.nothing_to_offload is True
    assert preview.confirmation_challenge is None


def test_preview_offload_maps_missing_table_and_option_errors() -> None:
    """Verify missing source table maps to 404 ApplicationError and option errors map to 400."""

    def _raise_missing(_opts: OffloadOperationOptions) -> tuple[OffloadPlan, list[str]]:
        raise OffloadException("Source table does not exist: SH.MISSING")

    def _raise_bad_opt(_opts: OffloadOperationOptions) -> tuple[OffloadPlan, list[str]]:
        raise OffloadOptionError("Invalid offload option combination")

    missing_service = ListenerOperationsService(plan_builder=_raise_missing)
    with pytest.raises(exceptions.ApplicationError) as exc_404:
        missing_service.preview_offload(schemas.OffloadOptions(owner_table="SH.MISSING"))
    assert exc_404.value.status_code == 404

    bad_opt_service = ListenerOperationsService(plan_builder=_raise_bad_opt)
    with pytest.raises(exceptions.ApplicationError) as exc_400:
        bad_opt_service.preview_offload(schemas.OffloadOptions(owner_table="SH.SALES"))
    assert exc_400.value.status_code == 400


def test_synchronize_schema_and_validate_table_services() -> None:
    """Verify synchronize_schema executes DDL under lock and validate_table runs CrossDbValidator."""
    executed_ddl: list[str] = []

    def _fake_sync_runner(
        owner: str,
        table_name: str,
        execute: bool,
    ) -> schemas.SchemaSyncExecutionResult:
        if execute:
            executed_ddl.append(f"ALTER TABLE {owner.lower()}.{table_name.lower()} ADD COLUMN PROMO_CODE STRING")
        return schemas.SchemaSyncExecutionResult(
            owner_table=f"{owner}.{table_name}",
            backend="BIGQUERY",
            has_drift=True,
            applied=execute,
            added_columns=["PROMO_CODE"],
            widened_columns=[],
            ddl_statements=[f"ALTER TABLE {owner.lower()}.{table_name.lower()} ADD COLUMN PROMO_CODE STRING"],
            warnings=[],
        )

    def _fake_validator_runner(
        request: schemas.ValidateTableRequest,
    ) -> schemas.ValidationResultSummary:
        return schemas.ValidationResultSummary(
            owner_table=request.owner_table.upper(),
            passed=not request.include_row_diff,
            execute=request.execute,
            aggregate_functions=request.aggregate_functions or ["COUNT", "MIN", "MAX"],
            safe_boundary_applied=not request.skip_boundary_check,
            summary_message="Compared aggregations of columns: ID",
            differing_rows=[{"ID": "42"}] if request.include_row_diff else [],
        )

    service = ListenerOperationsService(
        sync_runner=_fake_sync_runner,
        validator_runner=_fake_validator_runner,
    )
    sync_preview = service.synchronize_schema(schemas.SchemaSyncRequest(owner_table="SH.SALES", execute=False))
    assert sync_preview.has_drift is True
    assert sync_preview.applied is False
    assert executed_ddl == []

    sync_exec = service.synchronize_schema(schemas.SchemaSyncRequest(owner_table="SH.SALES", execute=True))
    assert sync_exec.applied is True
    assert len(executed_ddl) == 1

    val_ok = service.validate_table(schemas.ValidateTableRequest(owner_table="SH.SALES", filters="ID > 10"))
    assert val_ok.passed is True
    assert val_ok.safe_boundary_applied is True

    val_diff = service.validate_table(schemas.ValidateTableRequest(owner_table="SH.SALES", include_row_diff=True))
    assert val_diff.passed is False
    assert val_diff.differing_rows == [{"ID": "42"}]

    with pytest.raises(exceptions.ApplicationError) as bad_filter_exc:
        service.validate_table(
            schemas.ValidateTableRequest(
                owner_table="SH.SALES",
                filters="1=1; DROP TABLE SH.SALES",
            )
        )
    assert bad_filter_exc.value.status_code == 400


def _sample_plan(*, nothing_to_offload: bool) -> OffloadPlan:
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    p1 = SourcePartitionSlice(
        partition_name="P_2025_01",
        partition_position=1,
        high_value_raw="2025-02-01",
        byte_size=32768,
        row_count=750,
    )
    p2 = SourcePartitionSlice(
        partition_name="P_2025_02",
        partition_position=2,
        high_value_raw="2025-03-01",
        byte_size=32768,
        row_count=750,
    )
    slices = () if nothing_to_offload else (p1, p2)
    chunks = () if nothing_to_offload else ((p1, p2),)
    discovery = DiscoveryState(
        frontend_type="ORACLE",
        source_owner="SH",
        source_table_name="SALES",
        iot_type=None,
        partition_type="RANGE",
        subpartition_type=None,
        partition_columns=("TIME_ID",),
        subpartition_columns=(),
        columns=(col,),
        partitions=(p1, p2),
        snapshot_scn=123456,
        estimated_row_count=1500,
        estimated_size_bytes=65536,
    )
    return OffloadPlan(
        execution_id="dry-run",
        execute=False,
        discovery=discovery,
        prior_state=PriorMetadataState(backend_table_exists=False),
        boundary=PartitionBoundaryPlan(
            offload_mode="INCREMENTAL_RANGE",
            offload_type="INCREMENTAL",
            partitions_to_offload=slices,
            partition_chunks=chunks,
            nothing_to_offload=nothing_to_offload,
        ),
        predicate=PredicatePlan(
            ipa_predicate_type="RANGE",
            frontend_where_clause="TIME_ID < DATE '2025-03-01'",
        ),
        schema_plan=SchemaEvolutionPlan(
            backend_type="BIGQUERY",
            target_owner="sh",
            target_table_name="sales",
            canonical_columns=(col,),
            target_columns=(col,),
            create_backend_table=not nothing_to_offload,
            create_table_ddl=("CREATE TABLE sh.sales (ID INT64);",) if not nothing_to_offload else (),
            alter_table_ddl=(),
        ),
        transport_plan=StagingTransportPlan(
            transport_method="DUCKDB",
            staging_format="PARQUET",
        ),
        load_plan=BackendLoadPlan(ingest_strategy="DIRECT_LOAD"),
    )
