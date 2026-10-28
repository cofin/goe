# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OffloadPlanExecutor."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from goe.exceptions import OffloadException
from goe.offload.offload_messages import OffloadMessages
from goe.offload.schema.column_spec import ColumnDialect, ColumnSpec
from goe.orchestration.execution_id import ExecutionId
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
from goe.orchestration.stages.executor import OffloadPlanExecutor
from goe.persistence.models import OffloadMetadata


def test_executor_runs_all_steps_under_table_lock_and_saves_metadata() -> None:
    """Verify OffloadPlanExecutor.execute acquires the table lock, executes all steps in order, and saves metadata."""
    events: list[str] = []

    @contextmanager
    def lock_factory(owner: str, table_name: str) -> Iterator[None]:
        events.append(f"lock_enter:{owner}.{table_name}")
        try:
            yield
        finally:
            events.append(f"lock_exit:{owner}.{table_name}")

    backend = MagicMock()
    backend.execute_ddl.side_effect = lambda ddl, *, dry_run: events.append("execute_ddl")
    backend.ingest_chunk.side_effect = lambda plan, chunk, *, staged_rows, dry_run: (
        events.append("ingest_chunk") or staged_rows
    )
    backend.cleanup_staging.side_effect = lambda plan, *, dry_run: events.append("cleanup_staging")

    transport = MagicMock()
    transport.setup_staging.side_effect = lambda plan, *, dry_run: events.append("setup_staging")
    transport.transport_chunk.side_effect = lambda plan, chunk, *, dry_run: (
        events.append("transport_chunk") or (150, 4096)
    )

    verifier = MagicMock()
    verifier.verify.side_effect = lambda plan, *, expected_rows, dry_run: (
        events.append(f"verify:{expected_rows}") or True
    )

    repository = MagicMock()
    repository.save_offload_metadata.side_effect = lambda metadata, *, dry_run: (
        events.append("save_metadata") or metadata
    )

    executor = OffloadPlanExecutor(
        backend=backend,
        transport=transport,
        verifier=verifier,
        repository=repository,
        lock_factory=lock_factory,
        messages=OffloadMessages(),
    )

    plan = _build_plan(execute=True, nothing_to_offload=False)
    report = executor.execute(plan)

    assert report.status == "SUCCESS"
    assert report.executed is True
    assert report.verified is True
    assert report.rows_transported == 150
    assert report.rows_loaded == 150
    assert report.bytes_transported == 4096
    assert report.chunks_executed == 1
    assert report.saved_metadata == plan.planned_metadata
    assert events == [
        "lock_enter:SH.SALES",
        "execute_ddl",
        "setup_staging",
        "transport_chunk",
        "ingest_chunk",
        "cleanup_staging",
        "verify:150",
        "save_metadata",
        "lock_exit:SH.SALES",
    ]


def test_executor_dry_run_skips_mutations_and_returns_dry_run_report() -> None:
    """Verify plan.execute=False skips backend DDL, transport execution, and metadata persistence."""

    @contextmanager
    def lock_factory(owner: str, table_name: str) -> Iterator[None]:
        yield

    backend = MagicMock()
    transport = MagicMock()
    verifier = MagicMock()
    repository = MagicMock()

    executor = OffloadPlanExecutor(
        backend=backend,
        transport=transport,
        verifier=verifier,
        repository=repository,
        lock_factory=lock_factory,
        messages=OffloadMessages(),
    )

    plan = _build_plan(execute=False, nothing_to_offload=False)
    report = executor.execute(plan)

    assert report.status == "DRY_RUN"
    assert report.executed is False
    backend.execute_ddl.assert_not_called()
    transport.setup_staging.assert_not_called()
    transport.transport_chunk.assert_not_called()
    backend.ingest_chunk.assert_not_called()
    backend.cleanup_staging.assert_not_called()
    verifier.verify.assert_not_called()
    repository.save_offload_metadata.assert_not_called()


def test_executor_short_circuits_when_nothing_to_offload() -> None:
    """Verify when plan.has_nothing_to_offload is True, execution short-circuits with status NO_OP."""

    @contextmanager
    def lock_factory(owner: str, table_name: str) -> Iterator[None]:
        yield

    backend = MagicMock()
    transport = MagicMock()
    verifier = MagicMock()
    repository = MagicMock()

    executor = OffloadPlanExecutor(
        backend=backend,
        transport=transport,
        verifier=verifier,
        repository=repository,
        lock_factory=lock_factory,
        messages=OffloadMessages(),
    )

    plan = _build_plan(execute=True, nothing_to_offload=True, create_backend_table=False, create_ddl=(), alter_ddl=())
    assert plan.has_nothing_to_offload is True

    report = executor.execute(plan)

    assert report.status == "NO_OP"
    assert report.executed is False
    backend.execute_ddl.assert_not_called()
    transport.transport_chunk.assert_not_called()
    verifier.verify.assert_not_called()
    repository.save_offload_metadata.assert_not_called()


def test_executor_cleans_staging_and_skips_metadata_save_on_verification_failure() -> None:
    """Verify verification failure cleans staging in finally and never calls save_offload_metadata."""

    @contextmanager
    def lock_factory(owner: str, table_name: str) -> Iterator[None]:
        yield

    backend = MagicMock()
    backend.ingest_chunk.return_value = 100
    transport = MagicMock()
    transport.transport_chunk.return_value = (100, 2048)
    verifier = MagicMock()
    verifier.verify.side_effect = OffloadException("Row count mismatch")
    repository = MagicMock()

    executor = OffloadPlanExecutor(
        backend=backend,
        transport=transport,
        verifier=verifier,
        repository=repository,
        lock_factory=lock_factory,
        messages=OffloadMessages(),
    )

    plan = _build_plan(execute=True, nothing_to_offload=False)
    with pytest.raises(OffloadException, match="Row count mismatch"):
        executor.execute(plan)

    backend.cleanup_staging.assert_called_once_with(plan, dry_run=False)
    repository.save_offload_metadata.assert_not_called()


def _build_plan(
    *,
    execute: bool,
    nothing_to_offload: bool,
    create_backend_table: bool = True,
    create_ddl: tuple[str, ...] = ("CREATE TABLE sh.sales (id INT64)",),
    alter_ddl: tuple[str, ...] = (),
) -> OffloadPlan:
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    part_slice = SourcePartitionSlice(
        partition_name="P1",
        partition_position=1,
        high_value_raw="202501",
        high_value_literals=("202501",),
        byte_size=1024,
        row_count=150,
    )
    planned_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        offload_type="RANGE",
        backend_owner="sh",
        backend_table="sales",
        command_execution=ExecutionId.from_str("00000000-0000-0000-0000-000000000001"),
    )
    return OffloadPlan(
        execution_id="00000000-0000-0000-0000-000000000001",
        execute=execute,
        discovery=DiscoveryState(
            frontend_type="oracle",
            source_owner="SH",
            source_table_name="SALES",
            iot_type=None,
            partition_type="RANGE",
            subpartition_type=None,
            partition_columns=("ID",),
            subpartition_columns=(),
            columns=(col,),
            partitions=() if nothing_to_offload else (part_slice,),
            snapshot_scn=123456,
            estimated_row_count=150,
            estimated_size_bytes=1024,
            primary_key_columns=("ID",),
        ),
        prior_state=PriorMetadataState(
            backend_table_exists=False,
        ),
        boundary=PartitionBoundaryPlan(
            offload_mode="INCREMENTAL_RANGE",
            offload_type="INCREMENTAL",
            target_high_value_raw=None if nothing_to_offload else "202501",
            target_high_value_literals=() if nothing_to_offload else ("202501",),
            partitions_to_offload=() if nothing_to_offload else (part_slice,),
            partition_chunks=() if nothing_to_offload else ((part_slice,),),
            nothing_to_offload=nothing_to_offload,
        ),
        predicate=PredicatePlan(),
        schema_plan=SchemaEvolutionPlan(
            backend_type="bigquery",
            target_owner="sh",
            target_table_name="sales",
            canonical_columns=(col,),
            target_columns=(col,),
            create_backend_table=create_backend_table,
            create_table_ddl=create_ddl,
            alter_table_ddl=alter_ddl,
        ),
        transport_plan=StagingTransportPlan(
            transport_method="QUERY_IMPORT",
            staging_format="PARQUET",
            staging_uri="gs://bucket/sh_sales",
        ),
        load_plan=BackendLoadPlan(
            ingest_strategy="DIRECT_LOAD",
            verify_mode="row_count",
        ),
        planned_metadata=planned_meta,
    )
