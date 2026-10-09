# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""'goe offload' subcommand for high-performance data offloading."""

from optparse import Values
from typing import TYPE_CHECKING, Any

import rich_click as click

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.cli.common import common_options, extract_common_options

if TYPE_CHECKING:
    from goe.goe import OFFLOAD_OP_NAME, get_options
    from goe.offload.offload import get_offload_options
    from goe.orchestration.cli_entry_points import offload_by_cli

_LAZY_IMPORTS: LazyImportMap = {
    "OFFLOAD_OP_NAME": ("goe.goe", "OFFLOAD_OP_NAME"),
    "get_offload_options": ("goe.offload.offload", "get_offload_options"),
    "get_options": ("goe.goe", "get_options"),
    "offload_by_cli": ("goe.orchestration.cli_entry_points", "offload_by_cli"),
}


@click.command(
    name="offload",
    help="Offload datasets from RDBMS sources to modern cloud data warehouses.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "-t",
    "--table",
    "owner_table",
    required=True,
    help="Required. Source schema and table name in OWNER.TABLE format.",
)
@click.option(
    "--target",
    "target",
    help="Backend target query engine.",
)
@click.option(
    "--target-name",
    "target_owner_name",
    help="Override target owner and/or table name in OWNER.TABLE format.",
)
@click.option(
    "-x",
    "--execute",
    "execute",
    is_flag=True,
    default=None,
    help="Perform operations, rather than dry-run preview.",
)
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    default=None,
    help="Force offload execution without interactive confirmation.",
)
@click.option(
    "--skip-steps",
    "skip",
    help="Comma-separated list of step IDs to skip.",
)
@click.option(
    "--ddl-file",
    "ddl_file",
    help="Path to write generated target DDL.",
)
@click.option(
    "--create-backend-db",
    "create_backend_db",
    is_flag=True,
    default=None,
    help="Create target backend database/dataset if missing.",
)
@click.option(
    "--reset-backend-table",
    "reset_backend_table",
    is_flag=True,
    default=None,
    help="Drop and recreate existing backend target table.",
)
@click.option(
    "--reuse-backend-table",
    "reuse_backend_table",
    is_flag=True,
    default=None,
    help="Append to existing backend target table.",
)
@click.option(
    "--reset-hybrid-view",
    "reset_hybrid_view",
    is_flag=True,
    default=None,
    help="Drop and recreate existing hybrid view.",
)
@click.option(
    "--purge",
    "purge_backend_table",
    is_flag=True,
    default=None,
    help="Purge staged data files from cloud storage when resetting backend table.",
)
@click.option(
    "--preserve-load-table",
    "preserve_load_table",
    is_flag=True,
    default=None,
    help="Do not drop staging load table on completion.",
)
@click.option(
    "--compute-load-table-stats",
    "compute_load_table_stats",
    is_flag=True,
    default=None,
    help="Compute statistics on the load table during each offload chunk.",
)
@click.option(
    "--compress-load-table",
    "compress_load_table",
    is_flag=True,
    default=None,
    help="Compress the contents of the load table during offload.",
)
@click.option(
    "--offload-type",
    "offload_type",
    help="Offload mode: FULL or INCREMENTAL.",
)
@click.option(
    "--older-than-date",
    "older_than_date",
    help="Incremental boundary: Offload partitions older than YYYY-MM-DD.",
)
@click.option(
    "--older-than-days",
    "older_than_days",
    help="Incremental boundary: Offload partitions older than N days.",
)
@click.option(
    "--less-than-value",
    "less_than_value",
    help="Incremental boundary: Offload partitions less than value.",
)
@click.option(
    "--equal-to-values",
    "equal_to_values",
    multiple=True,
    help="Incremental boundary: Offload partitions matching values (repeatable).",
)
@click.option(
    "--partition-names",
    "partition_names_csv",
    help="Explicit CSV list of source partition names to offload.",
)
@click.option(
    "--partition-columns",
    "offload_partition_columns",
    help="Override columns used by offload to partition backend data.",
)
@click.option(
    "--partition-granularity",
    "offload_partition_granularity",
    help="Partition granularity (Y, M, D, or integer bucket size).",
)
@click.option(
    "--partition-digits",
    "synthetic_partition_digits",
    type=int,
    help="Maximum digits allowed for a numeric partition value.",
)
@click.option(
    "--partition-functions",
    "offload_partition_functions",
    help="External UDF(s) used by offload to partition backend data.",
)
@click.option(
    "--partition-lower-value",
    "offload_partition_lower_value",
    help="Lower bound integer value for backend integer range partitioning.",
)
@click.option(
    "--partition-upper-value",
    "offload_partition_upper_value",
    help="Upper bound integer value for backend integer range partitioning.",
)
@click.option(
    "--offload-by-subpartition",
    "offload_by_subpartition",
    is_flag=True,
    default=None,
    help="Use subpartition keys and high values in place of top-level partitions.",
)
@click.option(
    "--max-offload-chunk-size",
    "max_offload_chunk_size",
    help="Restrict size of partitions offloaded per cycle (e.g. 100M, 1G).",
)
@click.option(
    "--max-offload-chunk-count",
    "max_offload_chunk_count",
    type=int,
    help="Restrict number of partitions offloaded per cycle (1-1000).",
)
@click.option(
    "--offload-chunk-column",
    "offload_chunk_column",
    help="Split load data by this column during insert from load table to final table.",
)
@click.option(
    "--offload-predicate",
    "offload_predicate",
    help="Predicate DSL expression used to select data to offload.",
)
@click.option(
    "--offload-predicate-type",
    "ipa_predicate_type",
    help="Override default INCREMENTAL_PREDICATE_TYPE for partitioned tables.",
)
@click.option(
    "--no-modify-hybrid-view",
    "no_modify_hybrid_view",
    is_flag=True,
    default=False,
    help="Prevent offload predicate from being added to hybrid view boundary conditions.",
)
@click.option(
    "--storage-format",
    "storage_format",
    help="Backend storage format (ORC or PARQUET).",
)
@click.option(
    "--storage-compression",
    "storage_compression",
    help="Backend storage compression (HIGH, MED, NONE, GZIP, ZLIB, SNAPPY).",
)
@click.option(
    "--not-null-columns",
    "not_null_columns_csv",
    help="CSV list of columns to offload with a NOT NULL constraint.",
)
@click.option(
    "--integer-1-columns",
    "integer_1_columns_csv",
    help="CSV list of numeric columns to offload as 1-byte integer.",
)
@click.option(
    "--integer-2-columns",
    "integer_2_columns_csv",
    help="CSV list of numeric columns to offload as 2-byte integer.",
)
@click.option(
    "--integer-4-columns",
    "integer_4_columns_csv",
    help="CSV list of numeric columns to offload as 4-byte integer.",
)
@click.option(
    "--integer-8-columns",
    "integer_8_columns_csv",
    help="CSV list of numeric columns to offload as 8-byte integer.",
)
@click.option(
    "--integer-38-columns",
    "integer_38_columns_csv",
    help="CSV list of numeric columns to offload as 38-digit integer.",
)
@click.option(
    "--decimal-columns",
    "decimal_columns_csv_list",
    multiple=True,
    help="CSV list of numeric columns to offload as DECIMAL(p,s) paired with --decimal-columns-type.",
)
@click.option(
    "--decimal-columns-type",
    "decimal_columns_type_list",
    multiple=True,
    help="Precision and scale (p,s) paired with --decimal-columns.",
)
@click.option(
    "--date-columns",
    "date_columns_csv",
    help="CSV list of date-based columns to offload as DATE.",
)
@click.option(
    "--unicode-string-columns",
    "unicode_string_columns_csv",
    help="CSV list of string columns to offload as Unicode string.",
)
@click.option(
    "--double-columns",
    "double_columns_csv",
    help="CSV list of numeric columns to offload as double-precision floating point.",
)
@click.option(
    "--variable-string-columns",
    "variable_string_columns_csv",
    help="CSV list of columns to offload as variable-length string.",
)
@click.option(
    "--timestamp-tz-columns",
    "timestamp_tz_columns_csv",
    help="CSV list of date-based columns to offload with time zone.",
)
@click.option(
    "--decimal-padding-digits",
    "decimal_padding_digits",
    type=int,
    help="Padding to apply to precision and scale of decimals during offload.",
)
@click.option(
    "--allow-decimal-scale-rounding",
    "allow_decimal_scale_rounding",
    is_flag=True,
    default=None,
    help="Allow rounding decimal places when loading data into backend.",
)
@click.option(
    "--allow-floating-point-conversions",
    "allow_floating_point_conversions",
    is_flag=True,
    default=None,
    help="Allow converting NaN/Inf values to NULL when loading data into backend.",
)
@click.option(
    "--allow-nanosecond-timestamp-columns",
    "allow_nanosecond_timestamp_columns",
    is_flag=True,
    default=None,
    help="Allow offloading timestamp columns with nanosecond precision.",
)
@click.option(
    "--data-sample-percent",
    "data_sample_pct",
    help="Sample RDBMS data percentage for columns without explicit precision/scale.",
)
@click.option(
    "--data-sample-parallelism",
    "data_sample_parallelism",
    type=int,
    help="Degree of parallelism when sampling RDBMS data.",
)
@click.option(
    "--offload-transport-method",
    "offload_transport_method",
    help="Transport engine: SPARK_DATAPROC, SPARK_SUBMIT, QUERY_IMPORT, SQOOP, or AUTO.",
)
@click.option(
    "--offload-transport-parallelism",
    "offload_transport_parallelism",
    type=int,
    help="Degree of parallel JDBC extraction tasks.",
)
@click.option(
    "--offload-transport-dsn",
    "offload_transport_dsn",
    help="Source RDBMS connection DSN override for transport tasks.",
)
@click.option(
    "--offload-transport-fetch-size",
    "offload_transport_fetch_size",
    type=int,
    help="Number of records to fetch in a single RDBMS batch during transport.",
)
@click.option(
    "--offload-transport-consistent-read",
    "offload_transport_consistent_read",
    help="Enable consistent point-in-time reads across parallel transport tasks.",
)
@click.option(
    "--offload-transport-snapshot",
    "offload_transport_snapshot",
    help="Override RDBMS snapshot (SCN) used for transport query consistency.",
)
@click.option(
    "--offload-transport-spark-properties",
    "offload_transport_spark_properties",
    help="JSON key/value overrides for Spark configuration properties.",
)
@click.option(
    "--offload-transport-queue-name",
    "offload_transport_queue_name",
    help="Queue name to be used for offload transport jobs.",
)
@click.option(
    "--offload-transport-jvm-overrides",
    "offload_transport_jvm_overrides",
    help="JVM overrides passed to transport submission.",
)
@click.option(
    "--offload-transport-small-table-threshold",
    "offload_transport_small_table_threshold",
    help="Threshold above which Query Import is not chosen for non-partitioned tables.",
)
@click.option(
    "--offload-fs-scheme",
    "offload_fs_scheme",
    help="Filesystem scheme for offloaded tables (gs, s3a, wasb, abfs, hdfs).",
)
@click.option(
    "--offload-fs-prefix",
    "offload_fs_prefix",
    help="Path prefix for offloaded table files.",
)
@click.option(
    "--offload-fs-container",
    "offload_fs_container",
    help="Cloud storage bucket/container name when offloading to cloud storage.",
)
@click.option(
    "--bucket-hash-column",
    "bucket_hash_col",
    help="Column to hash when bucketing/distributing backend table storage.",
)
@click.option(
    "--sort-columns",
    "sort_columns_csv",
    help="CSV list of sort/cluster columns when storing data in a backend table.",
)
@click.option(
    "--offload-distribute-enabled",
    "offload_distribute_enabled",
    is_flag=True,
    default=None,
    help="Distribute data by partition keys during final INSERT operation.",
)
@click.option(
    "--hive-column-stats",
    "hive_column_stats",
    is_flag=True,
    default=None,
    help="Compute column-level statistics alongside table/partition statistics.",
)
@click.option(
    "--offload-stats",
    "offload_stats_method",
    help="Backend table statistics management method (NATIVE, HISTORY, COPY, NONE).",
)
@click.option(
    "--offload-chunk-impala-insert-hint",
    "impala_insert_hint",
    help="Impala INSERT hint override (SHUFFLE, NOSHUFFLE, NONE).",
)
@click.option(
    "--not-null-propagation",
    "not_null_propagation",
    hidden=True,
    help="Control NOT NULL constraint propagation to backend table.",
)
@click.option(
    "--dev-log",
    "dev_log",
    default=None,
    hidden=True,
    help="Enable internal developer diagnostic logging (stdout or file).",
)
@click.option(
    "--dev-log-level",
    "dev_log_level",
    hidden=True,
    help="Developer diagnostic log level.",
)
@click.option(
    "--transform-column",
    "column_transformation_list",
    multiple=True,
    hidden=True,
    help="Column transformation expression (repeatable).",
)
@click.option(
    "--offload-transport-validation-polling-interval",
    "offload_transport_validation_polling_interval",
    hidden=True,
    help="Polling interval in seconds for transport validation thread.",
)
@click.option(
    "--sqoop-additional-options",
    "sqoop_additional_options",
    help="Additional flags passed directly to Sqoop invocation.",
)
@click.option(
    "--sqoop-mapreduce-map-memory-mb",
    "sqoop_mapreduce_map_memory_mb",
    type=int,
    help="MapReduce mapper memory limit in MB for Sqoop transport.",
)
@click.option(
    "--sqoop-mapreduce-map-java-opts",
    "sqoop_mapreduce_map_java_opts",
    help="MapReduce mapper JVM options for Sqoop transport.",
)
@click.option(
    "--verify",
    "verify",
    type=click.Choice(["minus", "aggregate"], case_sensitive=False),
    help="Row count/data verification method (minus or aggregate).",
)
@click.option(
    "--no-verify",
    "no_verify",
    is_flag=True,
    default=False,
    help="Skip post-offload row count verification.",
)
@click.option(
    "--verify-parallelism",
    "verify_parallelism",
    type=int,
    help="Degree of parallelism on RDBMS source during post-offload verification.",
)
@common_options
@click.pass_context
def offload(ctx: click.Context, **kwargs: Any) -> None:
    """Execute offload operation with provided options."""
    bind_lazy_imports(__name__, _LAZY_IMPORTS)
    common_opts = extract_common_options(ctx, kwargs)
    parser = get_options(operation_name=OFFLOAD_OP_NAME)
    get_offload_options(parser)
    defaults = parser.get_default_values()
    options_dict = defaults.__dict__.copy()
    options_dict.update(common_opts)

    no_modify_hybrid_view = kwargs.pop("no_modify_hybrid_view", False)
    if no_modify_hybrid_view:
        options_dict["offload_predicate_modify_hybrid_view"] = False

    no_verify = kwargs.pop("no_verify", False)
    verify_mode = kwargs.pop("verify", None)
    if no_verify:
        options_dict["verify_row_count"] = False
    elif verify_mode is not None:
        options_dict["verify_row_count"] = verify_mode.lower()

    for k, v in kwargs.items():
        if isinstance(v, tuple):
            if v:
                options_dict[k] = list(v)
        elif v is not None:
            options_dict[k] = v

    options = Values(options_dict)
    offload_by_cli(options)


def __getattr__(name: str) -> Any:
    """Lazily import offload orchestration dependencies on first attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
