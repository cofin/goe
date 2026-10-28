# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Stateless executor for immutable OffloadPlan blueprints."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from goe.exceptions import OffloadException
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration import command_steps
from goe.orchestration.models import (
    OffloadExecutionReport,
    OffloadPlan,
    SourcePartitionSlice,
)
from goe.persistence.models import OffloadMetadata

__all__ = [
    "BackendExecutionGateway",
    "MetadataPersistenceGateway",
    "OffloadPlanExecutor",
    "StatelessOffloadExecutor",
    "TransportExecutionGateway",
    "VerificationGateway",
]


class BackendExecutionGateway(Protocol):
    """Protocol for executing target DDL, backend ingestion, and staging cleanup."""

    def execute_ddl(self, statements: tuple[str, ...], *, dry_run: bool) -> None:
        """Execute target CREATE, DROP, or ALTER statements."""
        ...

    def ingest_chunk(
        self,
        plan: OffloadPlan,
        chunk: tuple[SourcePartitionSlice, ...],
        *,
        staged_rows: int,
        dry_run: bool,
    ) -> int:
        """Execute BackendIngestStrategy for a staged chunk and return loaded row count."""
        ...

    def cleanup_staging(self, plan: OffloadPlan, *, dry_run: bool) -> None:
        """Remove temporary staging files and load tables unless preserve_load_table is set."""
        ...


class TransportExecutionGateway(Protocol):
    """Protocol for staging source slices via DuckDB or Spark transport."""

    def setup_staging(self, plan: OffloadPlan, *, dry_run: bool) -> None:
        """Prepare staging storage directories or external load tables."""
        ...

    def transport_chunk(
        self,
        plan: OffloadPlan,
        chunk: tuple[SourcePartitionSlice, ...],
        *,
        dry_run: bool,
    ) -> tuple[int, int]:
        """Extract source data for a chunk and return (rows_transported, bytes_transported)."""
        ...


class VerificationGateway(Protocol):
    """Protocol for post-load cross-database row count and aggregate verification."""

    def verify(
        self,
        plan: OffloadPlan,
        *,
        expected_rows: int,
        dry_run: bool,
    ) -> bool:
        """Verify offloaded data in the backend against the frontend source."""
        ...


class MetadataPersistenceGateway(Protocol):
    """Protocol for saving OffloadMetadata to the orchestration repository."""

    def save_offload_metadata(
        self,
        metadata: OffloadMetadata,
        *,
        dry_run: bool,
    ) -> OffloadMetadata:
        """Persist updated OffloadMetadata to the repository."""
        ...


class OffloadPlanExecutor:
    """Stateless executor that runs an immutable OffloadPlan under an orchestration lock."""

    def __init__(
        self,
        *,
        backend: BackendExecutionGateway,
        transport: TransportExecutionGateway,
        verifier: VerificationGateway,
        repository: MetadataPersistenceGateway,
        lock_factory: Callable[[str, str], AbstractContextManager[object]],
        messages: OffloadMessages,
    ) -> None:
        """Initialize the stateless executor with execution gateways and table lock factory."""
        self._backend = backend
        self._transport = transport
        self._verifier = verifier
        self._repository = repository
        self._lock_factory = lock_factory
        self._messages = messages

    def execute(self, plan: OffloadPlan) -> OffloadExecutionReport:
        """Execute an OffloadPlan under the per-table orchestration lock."""
        owner = plan.discovery.source_owner
        table_name = plan.discovery.source_table_name
        dry_run = not plan.execute

        with self._lock_factory(owner, table_name):
            if plan.has_nothing_to_offload:
                self._messages.notice(f"No new data to offload for {owner}.{table_name}")
                return OffloadExecutionReport(
                    execution_id=plan.execution_id,
                    source_owner=owner,
                    source_table_name=table_name,
                    target_owner=plan.schema_plan.target_owner,
                    target_table_name=plan.schema_plan.target_table_name,
                    executed=False,
                    status="NO_OP",
                )

            self._execute_schema_step(plan, dry_run=dry_run)

            if plan.boundary.nothing_to_offload:
                saved = self._save_metadata_step(plan, dry_run=dry_run)
                return OffloadExecutionReport(
                    execution_id=plan.execution_id,
                    source_owner=owner,
                    source_table_name=table_name,
                    target_owner=plan.schema_plan.target_owner,
                    target_table_name=plan.schema_plan.target_table_name,
                    executed=plan.execute,
                    status="DRY_RUN" if dry_run else "SUCCESS",
                    saved_metadata=saved,
                )

            chunks = plan.boundary.partition_chunks or (plan.boundary.partitions_to_offload,)
            total_rows_transported = 0
            total_bytes_transported = 0
            total_rows_loaded = 0

            for chunk in chunks:
                rows_t, bytes_t, rows_l = self._execute_chunk(plan, chunk, dry_run=dry_run)
                total_rows_transported += rows_t
                total_bytes_transported += bytes_t
                total_rows_loaded += rows_l

            verified = self._verify_step(
                plan,
                expected_rows=total_rows_transported,
                dry_run=dry_run,
            )
            saved_meta = self._save_metadata_step(plan, dry_run=dry_run)

            return OffloadExecutionReport(
                execution_id=plan.execution_id,
                source_owner=owner,
                source_table_name=table_name,
                target_owner=plan.schema_plan.target_owner,
                target_table_name=plan.schema_plan.target_table_name,
                executed=plan.execute,
                status="DRY_RUN" if dry_run else "SUCCESS",
                rows_transported=total_rows_transported,
                rows_loaded=total_rows_loaded,
                bytes_transported=total_bytes_transported,
                chunks_executed=len(chunks),
                verified=verified,
                saved_metadata=saved_meta,
            )

    def _execute_schema_step(self, plan: OffloadPlan, *, dry_run: bool) -> None:
        """Execute target table creation or column evolution under STEP_CREATE_TABLE."""
        ddl = (*plan.schema_plan.create_table_ddl, *plan.schema_plan.alter_table_ddl)
        if not ddl:
            return

        def _step() -> None:
            for statement in ddl:
                self._messages.log(statement)
            if not dry_run:
                self._backend.execute_ddl(ddl, dry_run=dry_run)

        self._messages.offload_step(
            command_steps.STEP_CREATE_TABLE,
            _step,
            execute=plan.execute,
        )

    def _execute_chunk(
        self,
        plan: OffloadPlan,
        chunk: tuple[SourcePartitionSlice, ...],
        *,
        dry_run: bool,
    ) -> tuple[int, int, int]:
        """Run staging setup, transport, backend load, and guaranteed staging cleanup for one chunk."""
        rows_transported = 0
        bytes_transported = 0
        rows_loaded = 0
        try:
            self._messages.offload_step(
                command_steps.STEP_STAGING_SETUP,
                lambda: None if dry_run else self._transport.setup_staging(plan, dry_run=dry_run),
                execute=plan.execute,
            )

            def _transport() -> None:
                nonlocal rows_transported, bytes_transported
                if not dry_run:
                    rows_transported, bytes_transported = self._transport.transport_chunk(
                        plan,
                        chunk,
                        dry_run=dry_run,
                    )

            self._messages.offload_step(
                command_steps.STEP_STAGING_TRANSPORT,
                _transport,
                execute=plan.execute,
            )

            def _load() -> None:
                nonlocal rows_loaded
                if not dry_run:
                    rows_loaded = self._backend.ingest_chunk(
                        plan,
                        chunk,
                        staged_rows=rows_transported,
                        dry_run=dry_run,
                    )

            self._messages.offload_step(
                command_steps.STEP_FINAL_LOAD,
                _load,
                execute=plan.execute,
            )
        finally:
            if not plan.transport_plan.preserve_load_table:
                self._messages.offload_step(
                    command_steps.STEP_STAGING_CLEANUP,
                    lambda: None if dry_run else self._backend.cleanup_staging(plan, dry_run=dry_run),
                    execute=plan.execute,
                )
        return rows_transported, bytes_transported, rows_loaded

    def _verify_step(
        self,
        plan: OffloadPlan,
        *,
        expected_rows: int,
        dry_run: bool,
    ) -> bool:
        """Execute post-load row count or aggregate verification when configured."""
        if not plan.load_plan.verify_mode or plan.load_plan.verify_mode == "False":
            return False
        verified = False

        def _verify() -> None:
            nonlocal verified
            if dry_run:
                return
            verified = self._verifier.verify(
                plan,
                expected_rows=expected_rows,
                dry_run=dry_run,
            )
            if not verified:
                raise OffloadException(
                    f"Post-offload verification failed for "
                    f"{plan.discovery.source_owner}.{plan.discovery.source_table_name}"
                )

        self._messages.offload_step(
            command_steps.STEP_VERIFY_EXPORTED_DATA,
            _verify,
            execute=plan.execute,
        )
        return verified

    def _save_metadata_step(
        self,
        plan: OffloadPlan,
        *,
        dry_run: bool,
    ) -> OffloadMetadata | None:
        """Persist planned OffloadMetadata under STEP_SAVE_METADATA."""
        if plan.planned_metadata is None:
            return None
        saved: OffloadMetadata | None = None

        def _save() -> None:
            nonlocal saved
            if not dry_run and plan.planned_metadata is not None:
                saved = self._repository.save_offload_metadata(
                    plan.planned_metadata,
                    dry_run=dry_run,
                )

        self._messages.offload_step(
            command_steps.STEP_SAVE_METADATA,
            _save,
            execute=plan.execute,
        )
        return saved


StatelessOffloadExecutor = OffloadPlanExecutor
