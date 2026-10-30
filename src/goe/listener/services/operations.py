# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Domain operations service for GOE Listener dry-run offload preview, schema sync, and validation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, cast

import msgspec

from goe.config.options import OffloadOperationOptions
from goe.config.orchestration_config import OrchestrationConfig
from goe.exceptions import OffloadException, OffloadOptionError, OptionValueError, ValidationError
from goe.listener import exceptions, schemas
from goe.listener.mcp import ConfirmationGate
from goe.listener.services.system import SystemService
from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_validation import DEFAULT_AGGS, DEFAULT_SELECT_COLS, CrossDbValidator
from goe.offload.operation.data_type_controls import offload_source_to_canonical_mappings
from goe.offload.operation.partition_controls import derive_partition_digits
from goe.offload.predicates import PredicateCompiler, PredicateOffloadException
from goe.offload.registry import (
    create_backend_table,
    create_repository_client,
    create_source_table,
)
from goe.offload.schema.column_spec import ColumnSpec
from goe.offload.sql_ast.dialect_engine import SqlDialect
from goe.offload.transport.selector import choose_offload_transport_method
from goe.offload.validation.ast_builder import CrossDbValidationBuilder
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.models import (
    DiscoveryState,
    OffloadPlan,
    PartitionBoundaryPlan,
    PredicatePlan,
    SourcePartitionSlice,
)
from goe.orchestration.pipeline import OffloadPipeline, get_offload_target_table
from goe.orchestration.stages.boundary import BoundaryResolutionStage
from goe.orchestration.stages.discovery import SourceDiscoveryStage
from goe.orchestration.stages.executor import OffloadPlanExecutor
from goe.orchestration.stages.plan_resolution import (
    OffloadOperation,
    SchemaAndTransportPlanningStage,
)
from goe.persistence.models import OffloadMetadata
from goe.platform.locking import orchestration_lock_for_table
from goe.sync.differ import SchemaSyncService

__all__ = (
    "ListenerOperationsService",
    "get_operations_service",
)


class ListenerOperationsService:
    """Domain facade driving dry-run OffloadPipeline.plan, SchemaSyncService, and CrossDbValidator."""

    def __init__(
        self,
        *,
        orchestration_config: OrchestrationConfig | None = None,
        confirmation_gate: ConfirmationGate | None = None,
        plan_builder: Callable[[OffloadOperationOptions], tuple[OffloadPlan, list[str]]] | None = None,
        sync_runner: Callable[[str, str, bool], schemas.SchemaSyncExecutionResult] | None = None,
        validator_runner: Callable[[schemas.ValidateTableRequest], schemas.ValidationResultSummary] | None = None,
    ) -> None:
        """Initialize the operations service with configuration, confirmation gate, and optional test hooks."""
        self._config = orchestration_config
        self._confirmation_gate = confirmation_gate or ConfirmationGate()
        self._plan_builder = plan_builder
        self._sync_runner = sync_runner
        self._validator_runner = validator_runner

    def preview_offload(self, options: schemas.OffloadOptions) -> schemas.OffloadPlanPreview:
        """Build a side-effect-free dry-run OffloadPlanPreview and mint an execute_offload ConfirmationChallenge."""
        preview_options = msgspec.structs.replace(options, execute=False)
        try:
            operation_options = preview_options.to_operation_options()
            if self._plan_builder is not None:
                plan, notices = self._plan_builder(operation_options)
            else:
                plan, notices = self._build_live_offload_plan(operation_options)
        except exceptions.ApplicationError:
            raise
        except (OffloadOptionError, OptionValueError, ValueError) as exc:
            raise exceptions.ApplicationError(status_code=400, message=str(exc)) from exc
        except OffloadException as exc:
            msg = str(exc)
            status_code = 404 if ("does not exist" in msg.lower() or "not found" in msg.lower()) else 400
            raise exceptions.ApplicationError(status_code=status_code, message=msg) from exc

        challenge: schemas.ConfirmationChallenge | None = None
        if not plan.has_nothing_to_offload:
            execute_payload = {**options.to_params_dict(), "execute": True}
            challenge = self._confirmation_gate.issue_challenge(
                tool_name="execute_offload",
                owner_table=options.owner_table,
                payload=execute_payload,
            )

        return schemas.OffloadPlanPreview.from_offload_plan(
            plan,
            owner_table=options.owner_table,
            notices=notices,
            confirmation_challenge=challenge,
        )

    def synchronize_schema(self, request: schemas.SchemaSyncRequest) -> schemas.SchemaSyncExecutionResult:
        """Synchronize schema drift between frontend and backend under orchestration_lock_for_table."""
        owner, table_name = self._split_owner_table(request.owner_table)
        try:
            with orchestration_lock_for_table(owner, table_name, dry_run=not request.execute):
                if self._sync_runner is not None:
                    return self._sync_runner(owner, table_name, request.execute)
                return self._run_live_schema_sync(owner, table_name, request.execute)
        except exceptions.ApplicationError:
            raise
        except (OffloadOptionError, OptionValueError, ValidationError, ValueError) as exc:
            raise exceptions.ApplicationError(status_code=400, message=str(exc)) from exc
        except OffloadException as exc:
            msg = str(exc)
            status_code = 404 if ("does not exist" in msg.lower() or "not found" in msg.lower()) else 400
            raise exceptions.ApplicationError(status_code=status_code, message=msg) from exc

    def validate_table(self, request: schemas.ValidateTableRequest) -> schemas.ValidationResultSummary:
        """Run read-only cross-database aggregate validation and optional DuckDB row diff."""
        owner, table_name = self._split_owner_table(request.owner_table)
        parsed_filters: Any = None
        if request.filters and request.filters.strip():
            try:
                parsed_filters = CrossDbValidationBuilder("oracle").parse_filter_tuples(request.filters)
            except (PredicateOffloadException, ValidationError, OffloadException, ValueError) as exc:
                raise exceptions.ApplicationError(status_code=400, message=str(exc)) from exc

        try:
            if self._validator_runner is not None:
                return self._validator_runner(request)
            return self._run_live_validation(owner, table_name, request, parsed_filters)
        except exceptions.ApplicationError:
            raise
        except (PredicateOffloadException, ValidationError, OffloadOptionError, OptionValueError, ValueError) as exc:
            raise exceptions.ApplicationError(status_code=400, message=str(exc)) from exc
        except OffloadException as exc:
            msg = str(exc)
            status_code = 404 if ("does not exist" in msg.lower() or "not found" in msg.lower()) else 400
            raise exceptions.ApplicationError(status_code=status_code, message=msg) from exc

    @staticmethod
    def _split_owner_table(owner_table: str) -> tuple[str, str]:
        """Split OWNER.TABLE into uppercase (owner, table_name) or raise HTTP 400 ApplicationError."""
        cleaned = (owner_table or "").strip()
        if "." not in cleaned:
            raise exceptions.ApplicationError(
                status_code=400,
                message=f"Invalid owner_table '{owner_table}': expected SCHEMA.TABLE",
            )
        owner, table_name = cleaned.split(".", 1)
        if not owner.strip() or not table_name.strip():
            raise exceptions.ApplicationError(
                status_code=400,
                message=f"Invalid owner_table '{owner_table}': expected SCHEMA.TABLE",
            )
        return owner.strip().upper(), table_name.strip().upper()

    def _run_live_schema_sync(
        self,
        owner: str,
        table_name: str,
        execute: bool,
    ) -> schemas.SchemaSyncExecutionResult:
        """Compute and optionally execute schema evolution DDL against the backend table."""
        config = self._get_config()
        messages = OffloadMessages.from_options(config, execution_id=ExecutionId())
        sys_service = SystemService(config=config, messages=messages)
        raw_source = sys_service.get_table_columns(owner, table_name) or []
        source_cols = [SystemService._to_source_column_snapshot(col, idx) for idx, col in enumerate(raw_source, 1)]
        repo = SystemService.get_repo(config, messages)
        meta = repo.get_offload_metadata(owner, table_name)
        target_schema = meta.backend_owner if meta is not None else owner.lower()
        target_table = meta.backend_table if meta is not None else table_name.lower()
        backend_table = create_backend_table(
            target_schema,
            target_table,
            config.target,
            config,
            messages,
            dry_run=not execute,
        )
        try:
            raw_target = backend_table.get_columns() or []
            target_cols = [SystemService._to_target_column_snapshot(col, idx) for idx, col in enumerate(raw_target, 1)]
            dialect_name = str(config.target or "bigquery").lower()
            sync_service = SchemaSyncService(dialect=cast("SqlDialect", dialect_name))
            backend_api = backend_table.get_backend_api() if execute else None
            diff, statements = sync_service.sync_table(
                schema_name=owner,
                table_name=table_name,
                target_schema=target_schema,
                target_table=target_table,
                source_columns=source_cols,
                target_columns=target_cols,
                execute=execute,
                ddl_executor=(lambda stmt: backend_api.execute_ddl(stmt)) if backend_api is not None else None,
            )
            return schemas.SchemaSyncExecutionResult(
                owner_table=f"{owner}.{table_name}",
                backend=str(config.target or "BIGQUERY").upper(),
                has_drift=diff.has_changes,
                applied=bool(execute and statements),
                added_columns=[col.column_name for col in diff.additions],
                widened_columns=[col.column_name for col in diff.widenings],
                ddl_statements=list(statements),
                warnings=[str(w) for w in (messages.get_warnings() or [])],
            )
        finally:
            if hasattr(backend_table, "close"):
                backend_table.close()

    def _run_live_validation(
        self,
        owner: str,
        table_name: str,
        request: schemas.ValidateTableRequest,
        parsed_filters: Any,
    ) -> schemas.ValidationResultSummary:
        """Execute CrossDbValidator.validate and optional run_row_diff against frontend and backend."""
        config = self._get_config()
        messages = OffloadMessages.from_options(config, execution_id=ExecutionId())
        validator = CrossDbValidator(
            owner,
            table_name,
            config,
            messages=messages,
            execute=request.execute,
        )
        aggs = [fn.lower() for fn in request.aggregate_functions] if request.aggregate_functions else list(DEFAULT_AGGS)
        selects = request.select_columns if request.select_columns is not None else DEFAULT_SELECT_COLS
        safe_boundary = not request.skip_boundary_check
        passed, summary_message = validator.validate(
            selects=selects,
            filters=parsed_filters if parsed_filters is not None else request.filters,
            group_bys=request.group_bys,
            aggs=aggs,
            safe=safe_boundary,
            as_of_scn=request.as_of_scn,
            execute=request.execute,
            frontend_parallelism=request.frontend_parallelism,
        )
        differing_rows: list[dict[str, Any]] = []
        if not passed and request.include_row_diff and request.execute:
            differing_rows = validator.run_row_diff()
        return schemas.ValidationResultSummary(
            owner_table=f"{owner}.{table_name}",
            passed=bool(passed),
            execute=request.execute,
            aggregate_functions=[fn.upper() for fn in aggs],
            safe_boundary_applied=safe_boundary,
            summary_message=summary_message,
            differing_rows=differing_rows,
        )

    def _get_config(self) -> OrchestrationConfig:
        """Return the configured OrchestrationConfig or construct a default instance."""
        if self._config is None:
            self._config = OrchestrationConfig.from_dict({"suppress_stdout": True})
        return self._config

    def _build_live_offload_plan(
        self,
        operation_options: OffloadOperationOptions,
    ) -> tuple[OffloadPlan, list[str]]:
        """Run OffloadPipeline.plan in dry-run mode using read-only catalog and planner gateways."""
        config = self._get_config()
        exec_id = ExecutionId()
        messages = OffloadMessages.from_options(config, execution_id=exec_id)
        repo_client = create_repository_client(
            config,
            messages,
            dry_run=True,
            trace_action="repo_client(ListenerOperationsService.preview_offload)",
        )
        source_table: Any = None
        target_table: Any = None
        try:
            op_params = {
                k: v
                for k, v in msgspec.structs.asdict(operation_options).items()
                if v is not None and k != "operation_name"
            }
            op_params["execute"] = False
            operation = OffloadOperation.from_dict(
                op_params,
                config,
                messages,
                repo_client=repo_client,
                execution_id=exec_id,
            )
            source_table = create_source_table(
                operation.owner,
                operation.table_name,
                config,
                messages,
                dry_run=True,
            )
            target_table = get_offload_target_table(operation, config, messages)

            frontend_gw = _LiveFrontendDiscoveryGateway(source_table, str(config.db_type or "oracle"))
            repo_gw = _LiveMetadataRepositoryGateway(repo_client)
            backend_cat_gw = _LiveBackendCatalogGateway(target_table)
            backend_plan_gw = _LiveBackendPlannerGateway(
                source_table=source_table,
                target_table=target_table,
                operation=operation,
                config=config,
                messages=messages,
            )
            transport_plan_gw = _LiveTransportPlannerGateway(
                source_table=source_table,
                target_table=target_table,
                operation=operation,
                config=config,
                messages=messages,
            )
            noop_exec_gw = _NoopExecutionGateways()
            pipeline = OffloadPipeline(
                discovery_stage=SourceDiscoveryStage(frontend_gw, repo_gw, backend_cat_gw),
                boundary_stage=BoundaryResolutionStage(PredicateCompiler()),
                planning_stage=SchemaAndTransportPlanningStage(backend_plan_gw, transport_plan_gw),
                executor=OffloadPlanExecutor(
                    backend=noop_exec_gw,
                    transport=noop_exec_gw,
                    verifier=noop_exec_gw,
                    repository=noop_exec_gw,
                    lock_factory=lambda owner, table: orchestration_lock_for_table(owner, table, dry_run=True),
                    messages=messages,
                ),
                backend_dialect=str(config.target or "bigquery"),
                config=config,
            )
            plan = pipeline.plan(operation_options, execution_id=exec_id.as_str())
            notices = [str(m) for m in (messages.get_notices() or [])]
            return plan, notices
        finally:
            if source_table is not None and hasattr(source_table, "close"):
                source_table.close()
            if target_table is not None and hasattr(target_table, "close"):
                target_table.close()
            repo_client.close()


def get_operations_service() -> ListenerOperationsService:
    """Provide a ListenerOperationsService instance for Litestar dependency injection."""
    return ListenerOperationsService()


class _LiveFrontendDiscoveryGateway:
    """Read-only FrontendDiscoveryGateway wrapping OffloadSourceTableInterface."""

    def __init__(self, source_table: Any, frontend_type: str) -> None:
        self._source_table = source_table
        self._frontend_type = frontend_type.upper()

    @property
    def frontend_type(self) -> str:
        return self._frontend_type

    def table_exists(self, owner: str, table_name: str) -> bool:
        if hasattr(self._source_table, "exists"):
            return bool(self._source_table.exists())
        return bool(getattr(self._source_table, "columns", None))

    def get_discovery_state(
        self,
        owner: str,
        table_name: str,
        *,
        capture_scn: bool = True,
    ) -> DiscoveryState:
        raw_cols = getattr(self._source_table, "columns", None) or ()
        col_specs = tuple(raw_cols)
        part_cols = tuple(
            getattr(col, "name", str(col)) for col in (getattr(self._source_table, "partition_columns", None) or ())
        )
        subpart_cols = tuple(
            getattr(col, "name", str(col)) for col in (getattr(self._source_table, "subpartition_columns", None) or ())
        )
        raw_parts = (
            self._source_table.get_partitions(strict=False) if hasattr(self._source_table, "get_partitions") else ()
        )
        slices = tuple(
            SourcePartitionSlice(
                partition_name=str(getattr(p, "partition_name", "")),
                partition_position=int(getattr(p, "partition_position", idx) or idx),
                high_value_raw=str(getattr(p, "high_values_csv", "") or ""),
                high_value_literals=tuple(str(x) for x in (getattr(p, "high_values_individual", None) or ())),
                byte_size=int(getattr(p, "partition_size", 0) or 0),
                row_count=int(getattr(p, "num_rows", 0) or 0),
                subpartition_names=tuple(getattr(p, "subpartition_names", None) or ()),
            )
            for idx, p in enumerate(raw_parts or (), start=1)
        )
        scn: int | None = None
        if capture_scn and hasattr(self._source_table, "get_current_scn"):
            raw_scn = self._source_table.get_current_scn()
            scn = int(raw_scn) if raw_scn is not None else None
        return DiscoveryState(
            frontend_type=self._frontend_type,
            source_owner=owner.upper(),
            source_table_name=table_name.upper(),
            iot_type=getattr(self._source_table, "iot_type", None),
            partition_type=getattr(self._source_table, "partition_type", None),
            subpartition_type=getattr(self._source_table, "subpartition_type", None),
            partition_columns=part_cols,
            subpartition_columns=subpart_cols,
            columns=col_specs,
            partitions=slices,
            snapshot_scn=scn,
            estimated_row_count=int(getattr(self._source_table, "num_rows", 0) or 0),
            estimated_size_bytes=int(getattr(self._source_table, "size_in_bytes", 0) or 0),
            primary_key_columns=tuple(getattr(self._source_table, "primary_key_columns", None) or ()),
        )

    def unsupported_data_types(self, columns: tuple[ColumnSpec, ...]) -> tuple[str, ...]:
        return ()


class _LiveMetadataRepositoryGateway:
    """Read-only MetadataRepositoryGateway wrapping OracleRepositoryService."""

    def __init__(self, repo_client: Any) -> None:
        self._repo = repo_client

    def get_offload_metadata(self, owner: str, table_name: str) -> OffloadMetadata | None:
        return cast("OffloadMetadata | None", self._repo.get_offload_metadata(owner.upper(), table_name.upper()))


class _LiveBackendCatalogGateway:
    """Read-only BackendCatalogGateway wrapping BackendTableInterface."""

    def __init__(self, target_table: Any) -> None:
        self._target_table = target_table

    def get_table_columns(self, owner: str, table_name: str) -> tuple[ColumnSpec, ...] | None:
        if not self._target_table.exists():
            return None
        raw_cols = self._target_table.get_columns() or ()
        return tuple(raw_cols)

    def detect_synthetic_partition_digits(self, columns: tuple[ColumnSpec, ...]) -> int | None:
        digits = derive_partition_digits(self._target_table)
        return int(digits) if digits is not None else None


class _LiveBackendPlannerGateway:
    """Read-only BackendPlannerGateway wrapping BackendTableInterface and OffloadOperation."""

    def __init__(
        self,
        *,
        source_table: Any,
        target_table: Any,
        operation: OffloadOperation,
        config: OrchestrationConfig,
        messages: OffloadMessages,
    ) -> None:
        self._source_table = source_table
        self._target_table = target_table
        self._operation = operation
        self._config = config
        self._messages = messages

    @property
    def backend_type(self) -> str:
        return str(self._config.target or "BIGQUERY").upper()

    def map_source_to_canonical(
        self,
        source_columns: tuple[ColumnSpec, ...],
        options: OffloadOperationOptions,
    ) -> tuple[ColumnSpec, ...]:
        mapped = offload_source_to_canonical_mappings(
            self._source_table,
            self._target_table,
            self._operation,
            self._config.not_null_propagation,
            self._messages,
        )
        return tuple(mapped or source_columns)

    def map_canonical_to_target(
        self,
        canonical_columns: tuple[ColumnSpec, ...],
        existing_columns: tuple[ColumnSpec, ...],
        options: OffloadOperationOptions,
    ) -> tuple[ColumnSpec, ...]:
        if existing_columns and not options.reset_backend_table:
            return existing_columns
        converted = self._target_table.convert_canonical_columns_to_backend(list(canonical_columns))
        self._target_table.set_columns(converted)
        return tuple(converted or canonical_columns)

    def generate_create_table_ddl(
        self,
        target_owner: str,
        target_table_name: str,
        target_columns: tuple[ColumnSpec, ...],
        *,
        partition_columns: tuple[str, ...],
        sort_columns: tuple[str, ...],
    ) -> tuple[str, ...]:
        ddl = self._target_table.create_backend_table(with_terminator=True) or ()
        return tuple(str(stmt) for stmt in ddl)

    def generate_add_columns_ddl(
        self,
        target_owner: str,
        target_table_name: str,
        columns_to_add: tuple[ColumnSpec, ...],
    ) -> tuple[str, ...]:
        if not columns_to_add:
            return ()
        backend_api = self._target_table.get_backend_api()
        ddl = backend_api.add_columns(
            target_owner,
            target_table_name,
            [(col.name, col.format_data_type()) for col in columns_to_add],
            sync=False,
        )
        if isinstance(ddl, str):
            return (ddl,)
        return tuple(str(stmt) for stmt in (ddl or ()))

    def select_ingest_strategy(
        self,
        *,
        transport_method: str,
        options: OffloadOperationOptions,
        has_udf_partition_functions: bool,
    ) -> Literal["DIRECT_LOAD", "STORAGE_WRITE_PENDING", "STAGED_INSERT"]:
        if options.preserve_load_table or options.offload_chunk_column or has_udf_partition_functions:
            return "STAGED_INSERT"
        return "DIRECT_LOAD"

    def generate_load_sql(
        self,
        target_owner: str,
        target_table_name: str,
        load_db_name: str | None,
        load_table_name: str | None,
        target_columns: tuple[ColumnSpec, ...],
        *,
        ingest_strategy: str,
    ) -> tuple[str, ...]:
        if ingest_strategy == "STAGED_INSERT" and load_db_name and load_table_name:
            return (f"INSERT INTO {target_owner}.{target_table_name} SELECT * FROM {load_db_name}.{load_table_name}",)
        return ()


class _LiveTransportPlannerGateway:
    """Read-only TransportPlannerGateway resolving transport method and staging coordinates."""

    def __init__(
        self,
        *,
        source_table: Any,
        target_table: Any,
        operation: OffloadOperation,
        config: OrchestrationConfig,
        messages: OffloadMessages,
    ) -> None:
        self._source_table = source_table
        self._target_table = target_table
        self._operation = operation
        self._config = config
        self._messages = messages

    def choose_transport_method(
        self,
        discovery: DiscoveryState,
        options: OffloadOperationOptions,
    ) -> str:
        method = choose_offload_transport_method(
            self._operation,
            self._source_table,
            self._config,
            self._messages,
        )
        return str(method or "DUCKDB")

    def resolve_staging_location(
        self,
        target_owner: str,
        target_table_name: str,
        options: OffloadOperationOptions,
    ) -> tuple[str, str | None, str | None, str | None]:
        fmt = str(getattr(self._config, "offload_staging_format", None) or "PARQUET")
        load_db = getattr(self._target_table, "load_db_name", None)
        return (fmt, None, str(load_db) if load_db else None, target_table_name)

    def build_extraction_queries(
        self,
        discovery: DiscoveryState,
        boundary: PartitionBoundaryPlan,
        predicate: PredicatePlan,
        options: OffloadOperationOptions,
    ) -> tuple[str, ...]:
        where_clause = f" WHERE {predicate.frontend_where_clause}" if predicate.frontend_where_clause else ""
        return (f"SELECT * FROM {discovery.source_owner}.{discovery.source_table_name}{where_clause}",)


class _NoopExecutionGateways:
    """No-op execution gateways used when constructing OffloadPipeline strictly for .plan()."""

    def execute_ddl(self, statements: tuple[str, ...], *, dry_run: bool) -> None:
        return None

    def ingest_chunk(
        self,
        plan: OffloadPlan,
        chunk: tuple[SourcePartitionSlice, ...],
        *,
        staged_rows: int,
        dry_run: bool,
    ) -> int:
        return 0

    def cleanup_staging(self, plan: OffloadPlan, *, dry_run: bool) -> None:
        return None

    def setup_staging(self, plan: OffloadPlan, *, dry_run: bool) -> None:
        return None

    def transport_chunk(
        self,
        plan: OffloadPlan,
        chunk: tuple[SourcePartitionSlice, ...],
        *,
        dry_run: bool,
    ) -> tuple[int, int]:
        return (0, 0)

    def verify(
        self,
        plan: OffloadPlan,
        *,
        expected_rows: int,
        dry_run: bool,
    ) -> bool:
        return True

    def save_offload_metadata(
        self,
        metadata: OffloadMetadata,
        *,
        dry_run: bool,
    ) -> OffloadMetadata:
        return metadata
