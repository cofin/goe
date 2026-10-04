# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Message schemas for the GOE Listener service."""

from typing import Any, Literal
from uuid import UUID

import msgspec
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
    offload_options: dict[str, Any] | str | None = None
    present_options: Any = None
    prepare_options: Any = None


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
    data_precision: int | None = None
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
    sqoop_additional_options: str | None = None
    sqoop_mapreduce_map_java_opts: str | None = None
    sqoop_mapreduce_map_memory_mb: int | None = None
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

        alias_map = {
            "target_table_name": "target_owner_name",
            "bucket_hash_column": "bucket_hash_col",
            "offload_chunk_count": "max_offload_chunk_count",
            "allow_floating_point": "allow_floating_point_conversions",
            "compress_backend_table": "compress_load_table",
            "replace_hybrid_view": "reset_hybrid_view",
        }
        for alias_key, canonical_key in alias_map.items():
            if alias_key in raw and canonical_key not in raw:
                raw[canonical_key] = raw.pop(alias_key)
            else:
                raw.pop(alias_key, None)

        csv_alias_map = {
            "partitions": "partition_names_csv",
            "sort_columns": "sort_columns_csv",
            "partition_functions": "offload_partition_functions",
        }
        for alias_key, canonical_key in csv_alias_map.items():
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


class CommandScheduled(BaseStruct):
    """Response returned when a command is queued/scheduled."""

    execution_id: str
    status: str = "QUEUED"


class ErrorMessage(BaseStruct):
    """Standard error response schema."""

    detail: str
    status_code: int = 400
