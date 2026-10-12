# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import datetime
from typing import Any

import msgspec
from sqlspec.utils.serializers import to_json


class StepDetailSchema(msgspec.Struct, kw_only=True):
    """Schema representing step execution details."""

    step_name: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    details: dict[str, Any] | None = None


class CommandExecutionSchema(msgspec.Struct, kw_only=True):
    """Schema representing command execution metadata persisted in repo."""

    execution_id: str
    command_type: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    parameters: dict[str, Any] | None = None
    step_details: list[dict[str, Any]] | None = None


class OffloadMetadataSchema(msgspec.Struct, kw_only=True):
    """Schema representing persisted offload table metadata."""

    offloaded_owner: str
    offloaded_table: str
    target_owner: str
    target_table: str
    offload_status: str | None = None
    offload_snapshot: str | None = None
    offload_predicate: str | None = None
    offload_bucket_column: str | None = None
    offload_sort_columns: str | None = None
    incremental_key: str | None = None
    incremental_high_value: str | None = None
    incremental_range: str | None = None
    incremental_predicate_type: str | None = None
    incremental_predicate_value: str | None = None


class LogEventSchema(msgspec.Struct, kw_only=True):
    """Schema representing real-time log event stream."""

    message: str
    timestamp: str | None = None
    level: str | None = None
    execution_id: str | None = None


class PartitionMetadataSchema(msgspec.Struct, kw_only=True):
    """Schema representing partition descriptor."""

    partition_name: str
    high_value: str | None = None
    position: int | None = None


class ColumnDetail(msgspec.Struct, kw_only=True):
    """Column detail metadata struct."""

    column_name: str
    data_type: str
    data_precision: int | None = None
    data_scale: int | None = None
    is_nullable: bool = True
    partition_position: int | None = None
    subpartition_position: int | None = None


class PartitionDetail(msgspec.Struct, kw_only=True):
    """Partition detail metadata struct."""

    partition_name: str
    partition_position: int = 0
    high_value: str = ""
    subpartitions: list[dict[str, Any]] = msgspec.field(default_factory=list)

    @classmethod
    def from_orm(cls, obj: Any) -> "PartitionDetail":
        return cls(
            partition_name=getattr(obj, "partition_name", str(obj)),
            partition_position=getattr(obj, "partition_position", 0),
            high_value=getattr(obj, "high_value", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_name": self.partition_name,
            "partition_position": self.partition_position,
            "high_value": self.high_value,
            "subpartitions": self.subpartitions,
        }


class SubPartitionDetail(msgspec.Struct, kw_only=True):
    """Subpartition detail metadata struct."""

    partition_name: str = ""
    partition_position: int = 0
    subpartition_name: str
    subpartition_position: int = 0
    high_value: str = ""

    @classmethod
    def from_orm(cls, obj: Any) -> "SubPartitionDetail":
        return cls(
            partition_name=getattr(obj, "partition_name", ""),
            partition_position=getattr(obj, "partition_position", 0),
            subpartition_name=getattr(obj, "subpartition_name", str(obj)),
            subpartition_position=getattr(obj, "subpartition_position", 0),
            high_value=getattr(obj, "high_value", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_name": self.partition_name,
            "partition_position": self.partition_position,
            "subpartition_name": self.subpartition_name,
            "subpartition_position": self.subpartition_position,
            "high_value": self.high_value,
        }


class OffloadableSchemaRow(msgspec.Struct, kw_only=True):
    """Row returned by the ``get_offloadable_schemas`` repository statement."""

    schema_name: str
    hybrid_schema_exists: str
    table_count: int | float | None
    schema_size_in_bytes: int | float | None


class SchemaTableRow(msgspec.Struct, kw_only=True):
    """Row returned by the ``get_schema_tables`` repository statement."""

    table_name: str
    table_size_in_bytes: int | float | None
    table_offloaded_size_in_bytes: int | float | None
    table_reclaimed_size_in_bytes: int | float | None
    estimated_row_count: int | float | None
    statistics_last_gathered_on: datetime.datetime | None
    partitioning_type: str | None
    subpartitioning_type: str | None
    table_compression: str | None
    table_compress_for: str | None
    is_offloaded: str
    is_partitioned: str
    is_subpartitioned: str
    is_compressed: str
    is_offloadable: str
    reason_not_offloadable: str | None


class CommandExecutionRow(msgspec.Struct, kw_only=True):
    """Row returned by the ``get_command_executions`` and ``get_command_execution`` repository statements."""

    execution_id: bytes
    command_type_code: str
    command_type: str
    status_code: str
    status: str
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    command_log_path: str
    command_input: str
    command_parameters: str | None
    goe_version: str
    goe_build: str


class CommandExecutionStepRow(msgspec.Struct, kw_only=True):
    """Row returned by the ``get_command_execution_steps_*`` repository statements."""

    execution_id: bytes
    step_id: int
    step_code: str
    step_title: str
    step_status_code: str
    step_status: str
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    step_details: str | None


def encode_schema(struct: msgspec.Struct) -> str:
    """Encode a msgspec Struct to a JSON string."""
    return to_json(struct)


def encode_schema_bytes(struct: msgspec.Struct) -> bytes:
    """Encode a msgspec Struct to JSON bytes."""
    return to_json(struct, as_bytes=True)


def decode_schema[T: msgspec.Struct](schema_type: type[T], payload: bytes | str) -> T:
    """Decode a JSON payload into a typed msgspec Struct."""
    if isinstance(payload, str):
        payload = payload.encode()
    return msgspec.json.decode(payload, type=schema_type)
