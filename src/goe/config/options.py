# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Typed msgspec option models for GOE CLI and API entrypoints.

This module is an import leaf. It imports only the standard library, msgspec,
goe.lib.schemas and goe.config.orchestration_defaults so that goe.cli, goe.listener
and goe.goe can all import it without circular imports. Field sets mirror the
historical option builders and preserve the defaults expected by downstream consumers.
"""

import os
from collections.abc import Mapping
from typing import Any, Self

import msgspec

from goe.config import orchestration_defaults
from goe.lib.schemas import BaseStruct

__all__ = (
    "EXPECTED_OFFLOAD_ARGS",
    "LISTENER_OFFLOAD_CSV_ALIASES",
    "LISTENER_OFFLOAD_RENAME_ALIASES",
    "AggValidateOptions",
    "BaseOptionStruct",
    "CommonOptions",
    "ConnectOptions",
    "OffloadOperationOptions",
    "SchemaSyncOptions",
    "StatusReportOptions",
    "TableOperationOptions",
    "default_report_directory",
)

EXPECTED_OFFLOAD_ARGS: tuple[str, ...] = (
    "allow_decimal_scale_rounding",
    "allow_floating_point_conversions",
    "allow_nanosecond_timestamp_columns",
    "bucket_hash_col",
    "column_transformation_list",
    "compress_load_table",
    "compute_load_table_stats",
    "create_backend_db",
    "data_sample_parallelism",
    "data_sample_pct",
    "date_columns_csv",
    "ddl_file",
    "decimal_columns_csv_list",
    "decimal_columns_type_list",
    "decimal_padding_digits",
    "double_columns_csv",
    "equal_to_values",
    "error_before_step",
    "error_after_step",
    "execute",
    "force",
    "hive_column_stats",
    "impala_insert_hint",
    "integer_1_columns_csv",
    "integer_2_columns_csv",
    "integer_4_columns_csv",
    "integer_8_columns_csv",
    "integer_38_columns_csv",
    "ipa_predicate_type",
    "less_than_value",
    "max_offload_chunk_count",
    "max_offload_chunk_size",
    "not_null_columns_csv",
    "offload_by_subpartition",
    "offload_chunk_column",
    "offload_distribute_enabled",
    "offload_fs_container",
    "offload_fs_prefix",
    "offload_fs_scheme",
    "offload_partition_columns",
    "offload_partition_functions",
    "offload_partition_granularity",
    "offload_partition_lower_value",
    "offload_partition_upper_value",
    "offload_predicate",
    "offload_predicate_modify_hybrid_view",
    "offload_stats_method",
    "offload_transport_method",
    "offload_transport_consistent_read",
    "offload_transport_dsn",
    "offload_transport_fetch_size",
    "offload_transport_jvm_overrides",
    "offload_transport_queue_name",
    "offload_transport_parallelism",
    "offload_transport_small_table_threshold",
    "offload_transport_snapshot",
    "offload_transport_spark_properties",
    "offload_transport_validation_polling_interval",
    "offload_type",
    "older_than_date",
    "older_than_days",
    "operation_name",
    "owner_table",
    "partition_names_csv",
    "preserve_load_table",
    "purge_backend_table",
    "reset_backend_table",
    "reset_hybrid_view",
    "reuse_backend_table",
    "sort_columns_csv",
    "sqoop_additional_options",
    "sqoop_mapreduce_map_memory_mb",
    "sqoop_mapreduce_map_java_opts",
    "skip",
    "storage_compression",
    "storage_format",
    "synthetic_partition_digits",
    "suppress_stdout",
    "target_owner_name",
    "timestamp_tz_columns_csv",
    "unicode_string_columns_csv",
    "variable_string_columns_csv",
    "ver_check",
    "verify_parallelism",
    "verify_row_count",
)

LISTENER_OFFLOAD_RENAME_ALIASES: dict[str, str] = {
    "target_table_name": "target_owner_name",
    "bucket_hash_column": "bucket_hash_col",
    "offload_chunk_count": "max_offload_chunk_count",
    "allow_floating_point": "allow_floating_point_conversions",
    "compress_backend_table": "compress_load_table",
    "replace_hybrid_view": "reset_hybrid_view",
}

LISTENER_OFFLOAD_CSV_ALIASES: dict[str, str] = {
    "partitions": "partition_names_csv",
    "sort_columns": "sort_columns_csv",
    "partition_functions": "offload_partition_functions",
}


def default_report_directory() -> str:
    """Return the Offload Status Report default directory derived from OFFLOAD_HOME."""
    return "%s/log" % os.environ.get("OFFLOAD_HOME", ".")


class BaseOptionStruct(BaseStruct, kw_only=True):
    """Mutable typed option model shared by all GOE entrypoints."""

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> Self:
        """Build an instance from a mapping; unknown keys raise TypeError."""
        return cls(**dict(mapping))

    def to_dict(self) -> dict[str, Any]:
        """Return every field value in a new dictionary."""
        return msgspec.structs.asdict(self)


class CommonOptions(BaseOptionStruct, kw_only=True):
    """Common CLI and orchestration options shared across all GOE commands."""

    version: bool = msgspec.field(default_factory=orchestration_defaults.version_default)
    execute: bool = msgspec.field(default_factory=orchestration_defaults.execute_default)
    log_path: str = msgspec.field(default_factory=orchestration_defaults.log_path_default)
    log_level: str | None = msgspec.field(default_factory=orchestration_defaults.log_level_default)
    verbose: bool = msgspec.field(default_factory=orchestration_defaults.verbose_default)
    vverbose: bool = msgspec.field(default_factory=orchestration_defaults.vverbose_default)
    quiet: bool = msgspec.field(default_factory=orchestration_defaults.quiet_default)
    skip: str | list[str] = msgspec.field(default_factory=orchestration_defaults.skip_default)
    ver_check: bool = msgspec.field(default_factory=orchestration_defaults.ver_check_default)
    error_before_step: str | None = None
    error_after_step: str | None = None
    error_on_token: str | None = None
    ansi: bool = msgspec.field(default_factory=orchestration_defaults.ansi_default)
    suppress_stdout: bool = msgspec.field(default_factory=orchestration_defaults.suppress_stdout_default)
    otel_enabled: bool | None = None
    otel_service_name: str | None = None
    otel_exporter: str | None = None
    otel_endpoint: str | None = None
    otel_protocol: str | None = None
    otel_sample_rate: float | None = None
    otel_sqlcommenter: bool | None = None
    log_format: str | None = None
    log_json_sidecar: bool | None = None


class TableOperationOptions(CommonOptions, kw_only=True):
    """Table-scoped orchestration options plus derived owner and table fields."""

    owner_table: str | None = None
    target: str = msgspec.field(default_factory=orchestration_defaults.query_engine_default)
    target_owner_name: str | None = None
    force: bool = msgspec.field(default_factory=orchestration_defaults.force_default)
    create_backend_db: bool = msgspec.field(default_factory=orchestration_defaults.create_backend_db_default)
    reset_backend_table: bool = False
    reset_hybrid_view: bool = False
    reuse_backend_table: bool = False
    purge_backend_table: bool = msgspec.field(default_factory=orchestration_defaults.purge_backend_table_default)
    equal_to_values: list[str] | None = None
    less_than_value: str | int | None = None
    older_than_days: str | int | None = None
    older_than_date: str | None = None
    partition_names_csv: str | None = None
    max_offload_chunk_size: str | int = msgspec.field(
        default_factory=orchestration_defaults.max_offload_chunk_size_default
    )
    max_offload_chunk_count: str | int = msgspec.field(
        default_factory=orchestration_defaults.max_offload_chunk_count_default
    )
    bucket_hash_col: str | None = None
    not_null_propagation: str = msgspec.field(default_factory=orchestration_defaults.not_null_propagation_default)
    offload_partition_columns: str | None = None
    synthetic_partition_digits: int = msgspec.field(
        default_factory=orchestration_defaults.synthetic_partition_digits_default
    )
    offload_partition_functions: str | None = None
    offload_partition_granularity: str | None = None
    offload_partition_lower_value: str | int | None = None
    offload_partition_upper_value: str | int | None = None
    storage_format: str | None = msgspec.field(default_factory=orchestration_defaults.storage_format_default)
    storage_compression: str = msgspec.field(default_factory=orchestration_defaults.storage_compression_default)
    hive_column_stats: bool = msgspec.field(default_factory=orchestration_defaults.hive_column_stats_default)
    offload_stats_method: str = msgspec.field(default_factory=orchestration_defaults.offload_stats_method_default)
    preserve_load_table: bool = msgspec.field(default_factory=orchestration_defaults.preserve_load_table_default)
    offload_by_subpartition: bool = False
    offload_chunk_column: str | None = None
    impala_insert_hint: str | None = None
    decimal_padding_digits: int = msgspec.field(default_factory=orchestration_defaults.decimal_padding_digits_default)
    sort_columns_csv: str = msgspec.field(default_factory=orchestration_defaults.sort_columns_default)
    offload_distribute_enabled: bool = msgspec.field(
        default_factory=orchestration_defaults.offload_distribute_enabled_default
    )
    offload_predicate: Any = None
    offload_predicate_modify_hybrid_view: bool = msgspec.field(
        default_factory=orchestration_defaults.offload_predicate_modify_hybrid_view_default
    )
    dev_log: str | None = None
    dev_log_level: str = msgspec.field(default_factory=orchestration_defaults.dev_log_level_default)
    column_transformation_list: list[str] | None = None
    owner: str | None = None
    table_name: str | None = None
    base_owner_name: str | None = None
    target_owner: str | None = None
    target_name: str | None = None
    base_owner: str | None = None
    base_name: str | None = None


class OffloadOperationOptions(TableOperationOptions, kw_only=True):
    """Options for the offload operation."""

    allow_decimal_scale_rounding: bool = msgspec.field(
        default_factory=orchestration_defaults.allow_decimal_scale_rounding_default
    )
    allow_floating_point_conversions: bool = msgspec.field(
        default_factory=orchestration_defaults.allow_floating_point_conversions_default
    )
    allow_nanosecond_timestamp_columns: bool = msgspec.field(
        default_factory=orchestration_defaults.allow_nanosecond_timestamp_columns_default
    )
    compress_load_table: bool = msgspec.field(default_factory=orchestration_defaults.compress_load_table_default)
    compute_load_table_stats: bool = msgspec.field(
        default_factory=orchestration_defaults.compute_load_table_stats_default
    )
    data_sample_pct: str | int | float = msgspec.field(default_factory=orchestration_defaults.data_sample_pct_default)
    data_sample_parallelism: int | str = msgspec.field(
        default_factory=orchestration_defaults.data_sample_parallelism_default
    )
    ddl_file: str | None = None
    not_null_columns_csv: str | None = None
    ipa_predicate_type: str | None = None
    offload_fs_scheme: str = msgspec.field(default_factory=orchestration_defaults.offload_fs_scheme_default)
    offload_fs_prefix: str | None = None
    offload_fs_container: str | None = None
    offload_type: str | None = None
    integer_1_columns_csv: str | None = None
    integer_2_columns_csv: str | None = None
    integer_4_columns_csv: str | None = None
    integer_8_columns_csv: str | None = None
    integer_38_columns_csv: str | None = None
    decimal_columns_csv_list: list[str] | None = None
    decimal_columns_type_list: list[str] | None = None
    date_columns_csv: str | None = None
    unicode_string_columns_csv: str | None = None
    double_columns_csv: str | None = None
    variable_string_columns_csv: str | None = None
    timestamp_tz_columns_csv: str | None = None
    offload_transport_consistent_read: str | bool = msgspec.field(
        default_factory=orchestration_defaults.offload_transport_consistent_read_default
    )
    offload_transport_dsn: str | None = msgspec.field(
        default_factory=orchestration_defaults.offload_transport_dsn_default
    )
    offload_transport_fetch_size: str | int = msgspec.field(
        default_factory=orchestration_defaults.offload_transport_fetch_size_default
    )
    offload_transport_jvm_overrides: str | None = None
    offload_transport_method: str | None = None
    offload_transport_parallelism: str | int = msgspec.field(
        default_factory=orchestration_defaults.offload_transport_parallelism_default
    )
    offload_transport_queue_name: str | None = None
    offload_transport_small_table_threshold: str | int | float = msgspec.field(
        default_factory=orchestration_defaults.offload_transport_small_table_threshold_default
    )
    offload_transport_snapshot: str | int | None = None
    offload_transport_spark_properties: str | dict[str, Any] | None = msgspec.field(
        default_factory=orchestration_defaults.offload_transport_spark_properties_default
    )
    offload_transport_validation_polling_interval: str | int | float = msgspec.field(
        default_factory=orchestration_defaults.offload_transport_validation_polling_interval_default
    )
    sqoop_additional_options: str | None = msgspec.field(
        default_factory=orchestration_defaults.sqoop_additional_options_default
    )
    sqoop_mapreduce_map_memory_mb: str | int | None = None
    sqoop_mapreduce_map_java_opts: str | None = None
    verify_row_count: str | bool | None = msgspec.field(default_factory=orchestration_defaults.verify_row_count_default)
    verify_parallelism: int | str | None = msgspec.field(
        default_factory=orchestration_defaults.verify_parallelism_default
    )
    operation_name: str | None = None


class AggValidateOptions(TableOperationOptions, kw_only=True):
    """Options for aggregate validation (legacy get_agg_validate_options)."""

    as_of_scn: int | None = None
    selects: list[str | int] | str | int = msgspec.field(default_factory=lambda: list[str | int]([5]))
    filters: str | list[tuple[str, str, object]] | None = None
    group_bys: str | list[str] | None = None
    aggregate_functions: tuple[str, ...] | list[str] | str = ("min", "max", "count")
    frontend_parallelism: int | str | None = msgspec.field(
        default_factory=orchestration_defaults.verify_parallelism_default
    )
    skip_boundary_check: bool | None = None


class ConnectOptions(CommonOptions, kw_only=True):
    """Options for goe connect (legacy get_connect_opts) plus derived host fields."""

    upgrade_environment_file: bool = False
    create_backend_db: bool | None = None
    original_offload_transport_spark_thrift_host: str | None = None
    original_hadoop_host: str | None = None


class StatusReportOptions(CommonOptions, kw_only=True):
    """Options for goe report (legacy get_offload_status_report_opts)."""

    schema: str | None = None
    table: str | None = None
    output_format: str = "text"
    demo_mode: bool = False
    output_level: str = "summary"
    report_name: str = "Offload_Status_Report"
    report_directory: str = msgspec.field(default_factory=default_report_directory)
    csv_delimiter: str = ","
    csv_enclosure: str = '"'


class SchemaSyncOptions(CommonOptions, kw_only=True):
    """Options for goe sync (legacy get_schema_sync_opts)."""

    include: str | None = None
    command_file: str | None = None
