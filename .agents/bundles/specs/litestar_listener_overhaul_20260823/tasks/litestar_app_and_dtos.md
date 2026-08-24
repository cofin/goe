---
type: Task
id: litestar_listener_overhaul_20260823:litestar_app_and_dtos
title: Build Litestar Application Factory, Controllers, Exception Handlers, and MsgspecDTOs
state: open
created_at: "2026-08-23T15:25:00Z"
updated_at: "2026-08-23T15:25:00Z"
tags:
  - task
  - litestar
  - api
  - dtos
  - controllers
depends_on: []
files:
  - src/goe/listener/app.py
  - src/goe/listener/dtos.py
  - src/goe/listener/controllers/__init__.py
  - src/goe/listener/controllers/system.py
  - src/goe/listener/controllers/orchestration.py
  - src/goe/listener/exceptions/__init__.py
  - src/goe/listener/exceptions/handlers.py
tests:
  - tests/unit/listener/test_system_controllers.py
  - tests/unit/listener/test_orchestration_controllers.py
verification_strategy: behavior_tdd
---

# Task: Build Litestar Application Factory, Controllers, Exception Handlers, and MsgspecDTOs

## Objective
Replace the legacy FastAPI application in `src/goe/listener/asgi.py` with a native Litestar application factory (`src/goe/listener/app.py`), defining modular `Controller` classes, `MsgspecDTO` structs, and custom error handlers for `/api/system/*` and `/api/orchestration/*`.

## Context
The GOE Listener exposes metadata, health status, and orchestration execution APIs consumed by the GOE Web Console and CLI. The legacy implementation used FastAPI 0.77.0 with Pydantic v1 models and custom Starlette exception handlers. This task establishes the Litestar application core and high-performance `msgspec` DTOs while guaranteeing 100% wire JSON contract compatibility.

## Implementation Steps

1. **Create `src/goe/listener/dtos.py`**:
   - Define typed `msgspec.Struct` models:
     - `HealthCheckDTO(status: str = "OK")`
     - `ListenerConfigDTO(endpoint_id: UUID, listener_group_id: UUID, db_unique_name: str, active_listeners: list[str], version: str, frontend_type: str, backend_type: str, offload_options: str | None, present_options: str | None = None, prepare_options: str | None = None)`
     - `OffloadableSchemaDTO(schema_name: str, hybrid_schema_exists: bool, table_count: int, schema_size_in_bytes: float)`
     - `OffloadableSchemasDTO(count: int, results: list[OffloadableSchemaDTO])`
     - `ColumnDetailDTO(column_name: str, data_type: str, data_precision: int | None, data_scale: int | None, is_nullable: bool, partition_position: int | None, subpartition_position: int | None)`
     - `ColumnDetailsDTO(count: int, results: list[ColumnDetailDTO])`
     - `SubPartitionDetailDTO(subpartition_name: str, subpartition_position: int, partition_name: str, partition_position: int, partition_size: int, num_rows: int, high_values_individual: list[str] = [])`
     - `PartitionDetailDTO(partition_name: str, partition_position: int, subpartition_count: int | None, partition_size: int, num_rows: int, is_subpartitioned: bool, subpartition_names: list[str] = [], high_values_individual: list[str] = [], subpartitions: list[SubPartitionDetailDTO] = [])`
     - `PartitionDetailsDTO(count: int, results: list[PartitionDetailDTO])`
     - `TableDetailDTO(table_name: str, table_size_in_bytes: int, table_offloaded_size_in_bytes: int = 0, table_reclaimed_size_in_bytes: int = 0, estimated_row_count: int | None = None, statistics_last_gathered_on: datetime | None = None, partitioning_type: str | None = None, subpartitioning_type: str | None = None, table_compression: str | None = None, table_compress_for: str | None = None, is_offloadable: bool = False, is_offloaded: bool = False, is_compressed: bool = False, is_partitioned: bool = False, is_subpartitioned: bool = False, reason_not_offloadable: str | None = None, column_details: list[ColumnDetailDTO] | None = None, partition_details: list[PartitionDetailDTO] | None = None)`
     - `TableDetailsDTO(count: int, results: list[TableDetailDTO])`
     - `CommandExecutionStepDTO(step_id: int, step_code: str, step_title: str, step_status_code: str, step_status: str, started_at: datetime, completed_at: datetime | None = None, step_details: str | None = None)`
     - `CommandExecutionDTO(execution_id: UUID, command_type_code: str, command_type: str, status_code: str, status: str, started_at: datetime, command_log_path: str, command_input: str, command_parameters: dict, goe_version: str, goe_build: str, completed_at: datetime | None = None, steps: list[CommandExecutionStepDTO] | None = None)`
     - `CommandExecutionsDTO(count: int, results: list[CommandExecutionDTO])`
     - `CommandExecutionLogDTO(name: str, is_file: bool, message: str, logged_at: datetime | None = None, contains_error: bool | None = None, log_type: str = "offload")`
     - `OffloadOptionsDTO`: Full offload options struct with field validations.
     - `CommandScheduledDTO(execution_id: UUID)`
     - `ErrorMessageDTO(code: int, message: str, details: dict[str, str] | None = None)`

2. **Create `src/goe/listener/controllers/system.py`**:
   - Define `SystemController(Controller)` with `path="/api/system"` and `tags=["System"]`:
     - `@get("/status/")` -> returns `HealthCheckDTO`
     - `@get("/config/")` -> returns `ListenerConfigDTO`
     - `@get("/schemas/")` -> returns `OffloadableSchemasDTO`
     - `@get("/schemas/{schema_name:str}/")` -> returns `TableDetailsDTO`
     - `@get("/schemas/{schema_name:str}/{table_name:str}/columns/")` -> returns `ColumnDetailsDTO`
     - `@get("/schemas/{schema_name:str}/{table_name:str}/partitions/")` -> returns `PartitionDetailsDTO`

3. **Create `src/goe/listener/controllers/orchestration.py`**:
   - Define `OrchestrationController(Controller)` with `path="/api/orchestration"` and `tags=["Orchestration"]`:
     - `@get("/executions/")` -> returns `CommandExecutionsDTO` (query `include_steps: bool = False`)
     - `@get("/executions/{execution_id:uuid}/")` -> returns `CommandExecutionDTO` (query `include_steps: bool = False`)
     - `@get("/executions/{execution_id:uuid}/execution-log/")` -> returns `CommandExecutionLogDTO`
     - `@post("/offload/")` -> returns `CommandScheduledDTO` (body `data: OffloadOptionsDTO`)

4. **Create `src/goe/listener/exceptions/handlers.py`**:
   - Implement custom exception handler functions returning standard `Response[ErrorMessageDTO]`:
     - `validation_exception_handler(request: Request, exc: ValidationException) -> Response[ErrorMessageDTO]` (HTTP 422)
     - `not_found_exception_handler(request: Request, exc: NotFoundException) -> Response[ErrorMessageDTO]` (HTTP 404)
     - `not_authorized_handler(request: Request, exc: NotAuthorizedException) -> Response[ErrorMessageDTO]` (HTTP 401)
     - `database_error_handler(request: Request, exc: Exception) -> Response[ErrorMessageDTO]` (HTTP 503)
     - `redis_error_handler(request: Request, exc: Exception) -> Response[ErrorMessageDTO]` (HTTP 503)

5. **Create `src/goe/listener/app.py`**:
   - Define `create_app() -> Litestar`:
     - Register `SystemController`, `OrchestrationController`.
     - Configure `OpenAPIConfig(title="GOE Listener", version=goe_version(), path="/schema", render_plugins=[ScalarRenderPlugin(path="/scalar"), SwaggerRenderPlugin(path="/docs"), RedocRenderPlugin(path="/redoc")])`.
     - Register `exception_handlers`.
     - Configure CORS, Compression, and Security Headers.

## Verification
- **Strategy**: `behavior_tdd`
- **Initial Evidence**: Run failing tests targeting new Litestar app instance before implementation.
- **Commands**:
  ```bash
  uv run pytest tests/unit/listener/test_system_controllers.py tests/unit/listener/test_orchestration_controllers.py -v
  ```
- **Final Evidence**: All system and orchestration controller tests pass with 200 OK responses matching exact JSON contracts.

## Acceptance Criteria
- [ ] `src/goe/listener/dtos.py` defines all required DTO structs without importing `pydantic`.
- [ ] `SystemController` and `OrchestrationController` handle all existing REST routes.
- [ ] Error responses strictly follow `{"code": int, "message": str, "details": dict}` shape.
- [ ] `create_app()` initializes cleanly without FastAPI or Uvicorn dependencies.
