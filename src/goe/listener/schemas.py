# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Message schemas for the GOE Listener service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import msgspec
from msgspec import field

from goe.config.options import (
    LISTENER_OFFLOAD_CSV_ALIASES,
    LISTENER_OFFLOAD_RENAME_ALIASES,
    OffloadOperationOptions,
)
from goe.orchestration.execution_id import ExecutionId
from goe.typing import FrozenBaseStruct

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
    "SubPartitionSummary",
    "TableDetail",
    "TableDetails",
)


class HealthCheck(FrozenBaseStruct, frozen=True):
    """System health check schema."""

    status: str = "OK"


class ListenerConfig(FrozenBaseStruct, frozen=True):
    """Listener configuration metadata schema."""

    endpoint_id: str
    listener_group_id: str
    db_unique_name: str
    active_listeners: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    frontend_type: str = "ORACLE"
    backend_type: str = "BIGQUERY"
    offload_options: dict[str, Any] | str | None = None
    present_options: Any = None
    prepare_options: Any = None


class OffloadableSchema(FrozenBaseStruct, frozen=True):
    """Offloadable schema descriptor."""

    schema_name: str
    hybrid_schema_exists: bool = False
    table_count: int = 0
    schema_size_in_bytes: float = 0.0

    @classmethod
    def from_item(cls, item: Any) -> OffloadableSchema:
        """Coerce a dict or struct row into an OffloadableSchema instance."""
        if isinstance(item, cls):
            return item
        data = _to_mapping(item)
        raw_hybrid = data.get("hybrid_schema_exists", False)
        if isinstance(raw_hybrid, str):
            hybrid_bool = raw_hybrid.strip().lower() in ("true", "1", "yes", "y")
        else:
            hybrid_bool = bool(raw_hybrid)
        return cls(
            schema_name=str(data.get("schema_name", "")),
            hybrid_schema_exists=hybrid_bool,
            table_count=int(data.get("table_count") or 0),
            schema_size_in_bytes=float(data.get("schema_size_in_bytes") or 0.0),
        )


class OffloadableSchemas(FrozenBaseStruct, frozen=True):
    """List of offloadable schemas response."""

    count: int
    results: list[OffloadableSchema] = field(default_factory=list)


class TableDetail(FrozenBaseStruct, frozen=True):
    """Table metadata schema."""

    table_name: str
    offload_status: str | None = None
    table_size_in_bytes: float = 0.0
    owner: str | None = None
    num_rows: int | None = None
    partitioned: str | bool | None = None
    offloaded: str | bool | None = None
    offload_type: str | None = None
    unsupported_data_type: str | None = None
    unsupported_data_type_count: int | None = None

    @classmethod
    def from_item(cls, item: Any) -> TableDetail:
        """Coerce a dict or struct row into a TableDetail instance."""
        if isinstance(item, cls):
            return item
        data = _to_mapping(item)
        return cls(
            table_name=str(data.get("table_name", "")),
            offload_status=data.get("offload_status"),
            table_size_in_bytes=float(data.get("table_size_in_bytes") or data.get("size_in_bytes") or 0.0),
            owner=data.get("owner"),
            num_rows=int(data["num_rows"]) if data.get("num_rows") is not None else None,
            partitioned=data.get("partitioned"),
            offloaded=data.get("offloaded"),
            offload_type=data.get("offload_type"),
            unsupported_data_type=data.get("unsupported_data_type"),
            unsupported_data_type_count=(
                int(data["unsupported_data_type_count"])
                if data.get("unsupported_data_type_count") is not None
                else None
            ),
        )


class TableDetails(FrozenBaseStruct, frozen=True):
    """List of table details response."""

    count: int
    results: list[TableDetail] = field(default_factory=list)


class ColumnDetail(FrozenBaseStruct, frozen=True):
    """Column metadata schema."""

    column_name: str
    data_type: str = ""
    data_precision: int | None = None
    data_scale: int | None = None
    is_nullable: bool = True
    partition_position: int | None = None
    subpartition_position: int | None = None
    column_id: int | None = None
    char_length: int | None = None
    data_default: str | None = None
    hidden_column: str | None = None
    virtual_column: str | None = None

    @classmethod
    def from_item(cls, item: Any) -> ColumnDetail:
        """Coerce a dict or struct row into a ColumnDetail instance."""
        if isinstance(item, cls):
            return item
        data = _to_mapping(item)
        nullable_raw = data.get("is_nullable", data.get("nullable", True))
        if isinstance(nullable_raw, str):
            is_nullable = nullable_raw.strip().upper() not in ("N", "FALSE", "0", "NO")
        else:
            is_nullable = bool(nullable_raw)
        return cls(
            column_name=str(data.get("column_name", "")),
            data_type=str(data.get("data_type", "")),
            data_precision=int(data["data_precision"]) if data.get("data_precision") is not None else None,
            data_scale=int(data["data_scale"]) if data.get("data_scale") is not None else None,
            is_nullable=is_nullable,
            partition_position=(
                int(data["partition_position"]) if data.get("partition_position") is not None else None
            ),
            subpartition_position=(
                int(data["subpartition_position"]) if data.get("subpartition_position") is not None else None
            ),
            column_id=int(data["column_id"]) if data.get("column_id") is not None else None,
            char_length=int(data["char_length"]) if data.get("char_length") is not None else None,
            data_default=str(data["data_default"]) if data.get("data_default") is not None else None,
            hidden_column=str(data["hidden_column"]) if data.get("hidden_column") is not None else None,
            virtual_column=str(data["virtual_column"]) if data.get("virtual_column") is not None else None,
        )


class ColumnDetails(FrozenBaseStruct, frozen=True):
    """List of column details response."""

    count: int
    results: list[ColumnDetail] = field(default_factory=list)


class SubPartitionSummary(FrozenBaseStruct, frozen=True):
    """Subpartition metadata summary schema."""

    subpartition_name: str
    partition_name: str | None = None
    partition_position: int | None = None
    subpartition_position: int = 0
    high_value: str = ""
    subpartition_size_in_bytes: float | int | None = None
    row_count: int | None = None

    @classmethod
    def from_item(cls, item: Any) -> SubPartitionSummary:
        """Coerce a dict or SubPartitionDetail struct into a SubPartitionSummary instance."""
        if isinstance(item, cls):
            return item
        data = _to_mapping(item)
        return cls(
            subpartition_name=str(data.get("subpartition_name", "")),
            partition_name=str(data["partition_name"]) if data.get("partition_name") is not None else None,
            partition_position=(
                int(data["partition_position"]) if data.get("partition_position") is not None else None
            ),
            subpartition_position=int(data.get("subpartition_position") or 0),
            high_value=str(data.get("high_value") or ""),
            subpartition_size_in_bytes=data.get("subpartition_size_in_bytes"),
            row_count=int(data["row_count"]) if data.get("row_count") is not None else None,
        )


class PartitionDetail(FrozenBaseStruct, frozen=True):
    """Partition metadata schema."""

    partition_name: str
    partition_position: int = 0
    high_value: str = ""
    subpartitions: list[SubPartitionSummary] = field(default_factory=list)
    partition_size_in_bytes: float | int | None = None
    row_count: int | None = None
    is_offloaded: bool | None = None

    @classmethod
    def from_item(
        cls,
        item: Any,
        *,
        subpartitions: list[SubPartitionSummary] | None = None,
    ) -> PartitionDetail:
        """Coerce a dict or struct row into a PartitionDetail instance."""
        data = _to_mapping(item)
        resolved_subparts = (
            subpartitions
            if subpartitions is not None
            else [SubPartitionSummary.from_item(sp) for sp in (data.get("subpartitions") or [])]
        )
        return cls(
            partition_name=str(data.get("partition_name", "")),
            partition_position=int(data.get("partition_position") or 0),
            high_value=str(data.get("high_value") or ""),
            subpartitions=resolved_subparts,
            partition_size_in_bytes=data.get("partition_size_in_bytes"),
            row_count=int(data["row_count"]) if data.get("row_count") is not None else None,
            is_offloaded=bool(data["is_offloaded"]) if data.get("is_offloaded") is not None else None,
        )


class PartitionDetails(FrozenBaseStruct, frozen=True):
    """List of partition details response."""

    count: int
    results: list[PartitionDetail] = field(default_factory=list)


class CommandExecutionStep(FrozenBaseStruct, frozen=True):
    """Command execution step details."""

    step_name: str = ""
    status: str = ""
    execution_id: str | None = None
    step_id: int | None = None
    step_code: str | None = None
    step_title: str | None = None
    status_code: str | None = None
    step_status_code: str | None = None
    step_status: str | None = None
    step_details: Any = None
    start_time: str | None = None
    end_time: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float = 0.0

    @classmethod
    def from_item(cls, item: Any) -> CommandExecutionStep:
        """Coerce a dict or struct row into a CommandExecutionStep instance."""
        if isinstance(item, cls):
            return item
        data = _to_mapping(item)
        raw_exec_id = data.get("execution_id")
        norm_exec_id = _normalize_exec_id(raw_exec_id) if raw_exec_id is not None else None
        step_code = data.get("step_code")
        step_title = data.get("step_title")
        step_name = str(data.get("step_name") or step_title or step_code or "")
        status_val = str(data.get("status") or data.get("step_status") or data.get("status_code") or "")
        return cls(
            step_name=step_name,
            status=status_val,
            execution_id=norm_exec_id,
            step_id=int(data["step_id"]) if data.get("step_id") is not None else None,
            step_code=str(step_code) if step_code is not None else None,
            step_title=str(step_title) if step_title is not None else None,
            status_code=str(data["status_code"]) if data.get("status_code") is not None else None,
            step_status_code=str(data["step_status_code"]) if data.get("step_status_code") is not None else None,
            step_status=str(data["step_status"]) if data.get("step_status") is not None else None,
            step_details=data.get("step_details"),
            start_time=str(data["start_time"]) if data.get("start_time") is not None else None,
            end_time=str(data["end_time"]) if data.get("end_time") is not None else None,
            started_at=str(data["started_at"]) if data.get("started_at") is not None else None,
            completed_at=str(data["completed_at"]) if data.get("completed_at") is not None else None,
            duration_seconds=float(data.get("duration_seconds") or 0.0),
        )


class CommandExecution(FrozenBaseStruct, frozen=True):
    """Command execution summary schema."""

    execution_id: str
    command_type_code: str = ""
    status_code: str = ""
    command_type: str | None = None
    status: str | None = None
    command_log_path: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    command_input: Any = None
    command_parameters: Any = None
    goe_version: str | None = None
    goe_build: str | None = None
    steps: list[CommandExecutionStep] = field(default_factory=list)

    @classmethod
    def from_item(
        cls,
        item: Any,
        *,
        steps: list[CommandExecutionStep] | None = None,
    ) -> CommandExecution:
        """Coerce a dict or struct row into a CommandExecution instance."""
        data = _to_mapping(item)
        norm_id = _normalize_exec_id(data.get("execution_id", ""))
        resolved_steps = (
            steps if steps is not None else [CommandExecutionStep.from_item(s) for s in (data.get("steps") or [])]
        )
        return cls(
            execution_id=norm_id,
            command_type_code=str(data.get("command_type_code") or ""),
            status_code=str(data.get("status_code") or data.get("status") or ""),
            command_type=str(data["command_type"]) if data.get("command_type") is not None else None,
            status=str(data["status"]) if data.get("status") is not None else None,
            command_log_path=str(data["command_log_path"]) if data.get("command_log_path") is not None else None,
            start_time=str(data["start_time"]) if data.get("start_time") is not None else None,
            end_time=str(data["end_time"]) if data.get("end_time") is not None else None,
            started_at=str(data["started_at"]) if data.get("started_at") is not None else None,
            completed_at=str(data["completed_at"]) if data.get("completed_at") is not None else None,
            command_input=data.get("command_input"),
            command_parameters=data.get("command_parameters"),
            goe_version=str(data["goe_version"]) if data.get("goe_version") is not None else None,
            goe_build=str(data["goe_build"]) if data.get("goe_build") is not None else None,
            steps=resolved_steps,
        )


class CommandExecutions(FrozenBaseStruct, frozen=True):
    """List of command executions response."""

    count: int
    results: list[CommandExecution] = field(default_factory=list)


class CommandExecutionLog(FrozenBaseStruct, frozen=True):
    """Command execution log file content schema."""

    name: str
    is_file: bool = False
    message: str = ""


class OffloadOptions(FrozenBaseStruct, frozen=True):
    """Options payload for submitting an offload operation."""

    owner_table: str
    allow_decimal_scale_rounding: bool | None = None
    allow_floating_point_conversions: bool | None = None
    allow_nanosecond_timestamp_columns: bool | None = None
    bucket_hash_col: str | None = None
    column_transformation_list: list[str] | None = None
    compress_load_table: bool | None = None
    compute_load_table_stats: bool | None = None
    create_backend_db: bool | None = None
    data_sample_parallelism: int | None = None
    data_sample_pct: str | int | float | None = None
    date_columns_csv: str | None = None
    ddl_file: str | None = None
    decimal_columns_csv_list: list[str] | None = None
    decimal_columns_type_list: list[str] | None = None
    decimal_padding_digits: int | None = None
    double_columns_csv: str | None = None
    equal_to_values: list[str] | None = None
    error_after_step: str | None = None
    error_before_step: str | None = None
    execute: bool = True
    force: bool | None = None
    hive_column_stats: bool | None = None
    impala_insert_hint: str | None = None
    integer_1_columns_csv: str | None = None
    integer_2_columns_csv: str | None = None
    integer_4_columns_csv: str | None = None
    integer_8_columns_csv: str | None = None
    integer_38_columns_csv: str | None = None
    ipa_predicate_type: str | None = None
    less_than_value: str | None = None
    max_offload_chunk_count: int | None = None
    max_offload_chunk_size: str | int | None = None
    not_null_columns_csv: str | None = None
    offload_by_subpartition: bool | None = None
    offload_chunk_column: str | None = None
    offload_distribute_enabled: bool | None = None
    offload_fs_container: str | None = None
    offload_fs_prefix: str | None = None
    offload_fs_scheme: str | None = None
    offload_partition_columns: str | None = None
    offload_partition_functions: str | None = None
    offload_partition_granularity: str | None = None
    offload_partition_lower_value: str | int | None = None
    offload_partition_upper_value: str | int | None = None
    offload_predicate: str | None = None
    offload_predicate_modify_hybrid_view: bool | None = None
    offload_stats_method: str | None = None
    offload_transport_consistent_read: str | bool | None = None
    offload_transport_dsn: str | None = None
    offload_transport_fetch_size: int | None = None
    offload_transport_jvm_overrides: str | None = None
    offload_transport_method: str | None = None
    offload_transport_parallelism: int | None = None
    offload_transport_queue_name: str | None = None
    offload_transport_small_table_threshold: str | int | float | None = None
    offload_transport_snapshot: str | int | None = None
    offload_transport_spark_properties: str | dict[str, Any] | None = None
    offload_transport_validation_polling_interval: str | int | float | None = None
    offload_type: str | None = None
    older_than_date: str | None = None
    older_than_days: str | int | None = None
    partition_names_csv: str | None = None
    preserve_load_table: bool | None = None
    purge_backend_table: bool | None = None
    reset_backend_table: bool | None = None
    reset_hybrid_view: bool | None = None
    reuse_backend_table: bool | None = None
    skip: list[str] | str | None = None
    sort_columns_csv: str | None = None
    storage_compression: str | None = None
    storage_format: str | None = None
    suppress_stdout: bool | None = None
    synthetic_partition_digits: int | None = None
    target_owner_name: str | None = None
    timestamp_tz_columns_csv: str | None = None
    unicode_string_columns_csv: str | None = None
    variable_string_columns_csv: str | None = None
    ver_check: bool | None = None
    verify_parallelism: int | None = None
    verify_row_count: str | bool | None = None
    target_table_name: str | None = None
    partitions: list[str] | str | None = None
    subpartitions: list[str] | str | None = None
    bucket_hash_column: str | None = None
    sort_columns: list[str] | str | None = None
    partition_functions: list[str] | str | None = None
    offload_chunk_count: int | None = None
    allow_floating_point: bool | None = None
    compress_backend_table: bool | None = None
    replace_hybrid_view: bool | None = None
    quiet: bool | None = None
    verbose: bool | None = None

    def to_params_dict(self) -> dict[str, Any]:
        """Convert OffloadOptions into a normalized dictionary restricted to EXPECTED_OFFLOAD_ARGS."""
        raw = {k: v for k, v in msgspec.structs.asdict(self).items() if v is not None}

        for alias_key, canonical_key in LISTENER_OFFLOAD_RENAME_ALIASES.items():
            if alias_key in raw and canonical_key not in raw:
                raw[canonical_key] = raw.pop(alias_key)
            else:
                raw.pop(alias_key, None)

        for alias_key, canonical_key in LISTENER_OFFLOAD_CSV_ALIASES.items():
            if alias_key in raw and canonical_key not in raw:
                val = raw.pop(alias_key)
                raw[canonical_key] = ",".join(val) if isinstance(val, list) else str(val)
            else:
                raw.pop(alias_key, None)

        if "subpartitions" in raw:
            subparts = raw.pop("subpartitions")
            if "partition_names_csv" not in raw:
                raw["partition_names_csv"] = ",".join(subparts) if isinstance(subparts, list) else str(subparts)
            if "offload_by_subpartition" not in raw:
                raw["offload_by_subpartition"] = True

        if "older_than_days" in raw and isinstance(raw["older_than_days"], int):
            raw["older_than_days"] = str(raw["older_than_days"])

        raw.pop("quiet", None)
        raw.pop("verbose", None)
        return raw

    def to_operation_options(self) -> OffloadOperationOptions:
        """Convert OffloadOptions into an OffloadOperationOptions instance hydrated with canonical defaults."""
        return OffloadOperationOptions.from_mapping(self.to_params_dict())


class CommandScheduled(FrozenBaseStruct, frozen=True):
    """Response returned when a command is queued/scheduled."""

    execution_id: str
    status: str = "QUEUED"


class ErrorMessage(FrozenBaseStruct, frozen=True):
    """Standard error response schema."""

    detail: str
    status_code: int = 400


def _to_mapping(item: Any) -> Mapping[str, Any]:
    """Convert a dict, struct, or object with to_dict() into a mapping."""
    if isinstance(item, Mapping):
        return item
    if isinstance(item, msgspec.Struct):
        return msgspec.structs.asdict(item)
    if hasattr(item, "to_dict") and callable(item.to_dict):
        return item.to_dict()
    return dict(item)


def _normalize_exec_id(raw_id: Any) -> str:
    """Convert raw bytes or UUID execution_id values into canonical string form."""
    if isinstance(raw_id, bytes):
        return ExecutionId.from_bytes(raw_id).as_str()
    return str(raw_id)
