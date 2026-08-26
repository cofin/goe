# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Message schemas for the GOE Listener service."""

from typing import Any, Literal
from uuid import UUID

from msgspec import field

from goe.lib.schemas import BaseStruct, CamelizedBaseStruct

__all__ = (
    "ColumnDetail",
    "ColumnDetails",
    "CommandExecution",
    "CommandExecutionLog",
    "CommandExecutionStep",
    "CommandExecutions",
    "CommandScheduled",
    "ErrorMessage",
    "HealthCheck",
    "ListenerConfig",
    "OffloadOptions",
    "OffloadableSchema",
    "OffloadableSchemas",
    "PartitionDetail",
    "PartitionDetails",
    "TableDetail",
    "TableDetails",
)


class HealthCheck(BaseStruct):
    """System health check schema."""

    status: str = "OK"


class ListenerConfig(BaseStruct):
    """Listener configuration metadata schema."""

    endpoint_id: str
    listener_group_id: str
    db_unique_name: str
    active_listeners: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    frontend_type: str = "ORACLE"
    backend_type: str = "BIGQUERY"


class OffloadableSchema(BaseStruct):
    """Offloadable schema descriptor."""

    schema_name: str
    hybrid_schema_exists: bool = False
    table_count: int = 0
    schema_size_in_bytes: float = 0.0


class OffloadableSchemas(BaseStruct):
    """List of offloadable schemas response."""

    count: int
    results: list[dict[str, Any]] = field(default_factory=list)


class TableDetail(BaseStruct):
    """Table metadata schema."""

    table_name: str
    offload_status: str | None = None
    table_size_in_bytes: float = 0.0


class TableDetails(BaseStruct):
    """List of table details response."""

    count: int
    results: list[dict[str, Any]] = field(default_factory=list)


class ColumnDetail(BaseStruct):
    """Column metadata schema."""

    column_name: str
    data_type: str
    data_scale: int | None = None
    is_nullable: bool = True
    partition_position: int | None = None
    subpartition_position: int | None = None


class ColumnDetails(BaseStruct):
    """List of column details response."""

    count: int
    results: list[dict[str, Any]] = field(default_factory=list)


class PartitionDetail(BaseStruct):
    """Partition metadata schema."""

    partition_name: str
    partition_position: int = 0
    high_value: str = ""
    subpartitions: list[dict[str, Any]] = field(default_factory=list)


class PartitionDetails(BaseStruct):
    """List of partition details response."""

    count: int
    results: list[dict[str, Any]] = field(default_factory=list)


class CommandExecution(BaseStruct):
    """Command execution summary schema."""

    execution_id: str | bytes
    command_type_code: str
    status_code: str
    command_type: str | None = None
    status: str | None = None
    command_log_path: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)


class CommandExecutions(BaseStruct):
    """List of command executions response."""

    count: int
    results: list[dict[str, Any]] = field(default_factory=list)


class CommandExecutionStep(BaseStruct):
    """Command execution step details."""

    step_name: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    duration_seconds: float = 0.0


class CommandExecutionLog(BaseStruct):
    """Command execution log file content schema."""

    name: str
    is_file: bool = True
    message: str = ""


class OffloadOptions(BaseStruct):
    """Options payload for submitting an offload operation."""

    owner_table: str
    offload_type: str | None = None
    target_table_name: str | None = None
    offload_predicate: str | None = None
    date_range_column: str | None = None
    date_range_start: str | None = None
    date_range_end: str | None = None
    partitions: list[str] | None = None
    subpartitions: list[str] | None = None
    older_than_date: str | None = None
    less_than_value: str | None = None
    offload_strategy: str | None = None
    create_backend_table: bool | None = None
    allow_floating_point: bool | None = None
    preserve_case: bool | None = None
    compress_backend_table: bool | None = None
    bucket_hash_column: str | None = None
    bucket_hash_buckets: int | None = None
    sort_columns: list[str] | None = None
    partition_functions: list[str] | None = None
    offload_chunk_column: str | None = None
    offload_chunk_count: int | None = None
    offload_sort_columns: list[str] | None = None
    hybrid_view: bool | None = None
    create_hybrid_view: bool | None = None
    drop_hybrid_view: bool | None = None
    replace_hybrid_view: bool | None = None
    execute: bool = True
    quiet: bool = False
    verbose: bool = False


class CommandScheduled(BaseStruct):
    """Response returned when a command is queued/scheduled."""

    execution_id: str
    status: str = "QUEUED"


class ErrorMessage(BaseStruct):
    """Standard error response schema."""

    detail: str
    status_code: int = 400
