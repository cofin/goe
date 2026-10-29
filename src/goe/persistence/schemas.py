# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""msgspec-based JSON schemas and serializers for GOE persistence."""

import datetime
from typing import Any

import msgspec

from goe.serializers import decode_json, encode_json, encode_json_bytes
from goe.typing import BaseStruct, FrozenBaseStruct


class StepDetailSchema(FrozenBaseStruct, frozen=True, kw_only=True):
    """Schema for command step details stored as JSON in the repository."""

    step_name: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    duration_seconds: float | None = None
    details: dict[str, Any] = msgspec.field(default_factory=dict)


class CommandExecutionSchema(FrozenBaseStruct, frozen=True, kw_only=True):
    """Schema for command execution parameters and metadata."""

    execution_id: str
    command_type: str
    status: str
    parameters: dict[str, Any] = msgspec.field(default_factory=dict)
    step_details: list[dict[str, Any]] = msgspec.field(default_factory=list)


class LogEventSchema(FrozenBaseStruct, frozen=True, kw_only=True):
    """Schema for structured log events."""

    message: str
    level: str = "INFO"
    execution_id: str | None = None
    timestamp: str | None = None
    extra: dict[str, Any] = msgspec.field(default_factory=dict)


class PartitionMetadataSchema(FrozenBaseStruct, frozen=True, kw_only=True):
    """Schema for partition metadata stored or transmitted via JSON."""

    partition_name: str
    high_values_csv: str | None = None
    partition_size: int | None = None
    num_rows: int | None = None
    subpartition_names: list[str] = msgspec.field(default_factory=list)


class ColumnDetail(BaseStruct, kw_only=True):
    """Column metadata returned by ``get_table_columns``."""

    column_name: str
    data_type: str
    data_precision: int | None = None
    data_scale: int | None = None
    is_nullable: bool
    partition_position: int | None = None
    subpartition_position: int | None = None

    @classmethod
    def from_orm(cls, column: Any) -> "ColumnDetail":
        """Construct ``ColumnDetail`` from an ``OracleColumn`` instance."""
        return cls(
            column_name=column.name,
            data_type=column.data_type,
            data_precision=getattr(column, "data_precision", None),
            data_scale=column.data_scale,
            is_nullable=bool(column.nullable),
        )


class PartitionDetail(BaseStruct, kw_only=True):
    """Partition metadata returned by ``get_table_partitions``."""

    partition_name: str | None
    partition_position: int | None
    high_value: Any
    row_count: int | None
    total_size_in_bytes: int | None

    @classmethod
    def from_orm(cls, partition: Any) -> "PartitionDetail":
        """Construct ``PartitionDetail`` from an offload source partition object."""
        return cls(
            partition_name=partition.partition_name,
            partition_position=partition.partition_position,
            high_value=partition.high_values_csv,
            row_count=partition.num_rows,
            total_size_in_bytes=partition.partition_size,
        )


class SubPartitionDetail(BaseStruct, kw_only=True):
    """Subpartition metadata returned by ``get_table_subpartitions``."""

    partition_name: str | None = None
    partition_position: int | None = None
    subpartition_name: str | None = None
    subpartition_position: int | None = None
    high_value: str | None = None

    @classmethod
    def from_orm(cls, subpartition: Any) -> "SubPartitionDetail":
        """Construct ``SubPartitionDetail`` from an offload source subpartition object."""
        return cls(
            partition_name=getattr(subpartition, "partition_name", None),
            partition_position=getattr(subpartition, "partition_position", None),
            subpartition_name=subpartition.subpartition_name,
            subpartition_position=subpartition.subpartition_position,
            high_value=getattr(subpartition, "high_value", None) or getattr(subpartition, "high_values_csv", None),
        )


class OffloadableSchemaRow(FrozenBaseStruct, frozen=True, kw_only=True):
    """Row model for ``get_offloadable_schemas`` in ``oracle_repo.sql``."""

    schema_name: str
    hybrid_schema_exists: str
    table_count: int
    schema_size_in_bytes: int | None = None


class SchemaTableRow(FrozenBaseStruct, frozen=True, kw_only=True):
    """Row model for ``get_schema_tables`` in ``oracle_repo.sql``."""

    table_name: str
    table_size_in_bytes: int | None = None
    table_offloaded_size_in_bytes: int | None = None
    table_reclaimed_size_in_bytes: int | None = None
    estimated_row_count: int | None = None
    statistics_last_gathered_on: datetime.datetime | None = None
    partitioning_type: str | None = None
    subpartitioning_type: str | None = None
    table_compression: str | None = None
    table_compress_for: str | None = None
    is_offloaded: str
    is_partitioned: str
    is_subpartitioned: str
    is_compressed: str
    is_offloadable: str
    reason_not_offloadable: str | None = None


class CommandExecutionRow(FrozenBaseStruct, frozen=True, kw_only=True):
    """Row model for ``get_command_executions`` and ``get_command_execution`` in ``oracle_repo.sql``."""

    execution_id: Any
    command_type_code: str
    command_type: str
    status_code: str
    status: str
    started_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    command_log_path: str
    command_input: str
    command_parameters: Any = None
    goe_version: str
    goe_build: str


class CommandExecutionStepRow(FrozenBaseStruct, frozen=True, kw_only=True):
    """Row model for ``get_command_execution_steps_*`` in ``oracle_repo.sql``."""

    execution_id: Any
    step_id: int
    step_code: str
    step_title: str
    step_status_code: str
    step_status: str
    started_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    step_details: Any = None


def encode_schema(obj: Any) -> str:
    """Serialize a schema object or dict to a JSON string using centralized serializers."""
    return encode_json(obj)


def encode_schema_bytes(obj: Any) -> bytes:
    """Serialize a schema object or dict to UTF-8 JSON bytes using centralized serializers."""
    return encode_json_bytes(obj)


def decode_schema[T](schema_type: type[T], data: str | bytes) -> T:
    """Deserialize JSON string or bytes into a typed msgspec Struct."""
    return msgspec.convert(decode_json(data), type=schema_type)
