---
type: Research
title: "Option Inventory for Typed msgspec Option Models (baseline 46890a8)"
description: "Authoritative field inventory extracted from the legacy optparse builders, CLI command modules, listener schema, and option normalisers at baseline commit 46890a8."
created_at: 2026-10-10T18:50:00Z
updated_at: 2026-10-10T18:50:00Z
---

# Option Inventory for Typed msgspec Option Models

## How this inventory was produced

- Extracted at baseline commit `46890a8` by parsing every `add_option(...)` call in the legacy builders with `ast` and by instantiating each builder and reading `parser.get_default_values().__dict__` (with `GOE_NO_AUTOLOAD_ENV=1` and an empty environment).
- `optparse.OptionParser.remove_option()` does **not** delete the removed option's entry from `parser.defaults`. The legacy `optparse.Values` object handed to every entrypoint therefore carries the default of every option ever added, including removed ones. The struct field sets below reproduce that exact key set.
- Annotation rule: `store_true`/`store_false` → `bool` (or `bool | None` when no default is supplied); `append` → `list[str] | None`; `type=int` → `int` (or `int | None` when the default can be `None`); everything else → `str` or `str | None` by default value.
- msgspec does not validate field types in `__init__`; annotations exist for `mypy` (Chapter 2.3) and must admit every value assigned by the normalisers listed in "Derived attributes".

## Effective key-set sizes per legacy builder

| Legacy builder (baseline location) | Effective `Values` keys | Struct |
| :--- | :--- | :--- |
| `get_common_options` (`src/goe/goe.py:2685-2772`) | 14 | `CommonOptions` |
| `get_options` (`src/goe/goe.py:2827-3106`) | 54 (14 common + 40) | `TableOperationOptions` |
| `get_options` + `get_offload_options` (`src/goe/offload/offload.py:379-655`) | 96 (54 + 42) | `OffloadOperationOptions` |
| `get_connect_opts` (`src/goe/connect/connect.py:441-461`) | 16 (14 common + 2) | `ConnectOptions` |
| `get_offload_status_report_opts` (`src/goe/offload/offload_status_report.py:3602-3673`) | 23 (14 common + 9) | `StatusReportOptions` |
| `get_schema_sync_opts` (`src/goe/schema_sync/schema_sync.py:29-48`) | 16 (14 common + 2) | `SchemaSyncOptions` |
| `get_agg_validate_options` (`src/goe/scripts/agg_validate.py:179-227`) | 61 (54 from `get_options` + 7) | `AggValidateOptions` |

`get_oracle_options` (`src/goe/goe.py:2775-2824`) has zero callers and contributes no keys.

## Derived attributes set by normalisers (must be declared fields, default `None`)

| Attribute(s) | Assigned by (baseline) | Declared on |
| :--- | :--- | :--- |
| `owner`, `table_name`, `base_owner_name`, `target_owner`, `target_name`, `base_owner`, `base_name` | `normalise_owner_table_options` (`src/goe/goe.py:761-778`), called by `normalise_options` and `run_agg_validate` | `TableOperationOptions` |
| `operation_name` | `offload_by_cli` (`src/goe/orchestration/cli_entry_points.py:42`) | `OffloadOperationOptions` (it is also an `EXPECTED_OFFLOAD_ARGS` key) |
| `original_offload_transport_spark_thrift_host`, `original_hadoop_host` | `connect` (`src/goe/connect/connect.py:486-489`) | `ConnectOptions` |

Type changes applied in place by normalisers: `skip` (`str` → `list[str]`, `normalise_options` `src/goe/goe.py:985`), `include` (`None` → `"*.*"`, `normalise_schema_sync_options`), `filters`/`selects`/`group_bys`/`aggregate_functions`/`frontend_parallelism` (`post_process_args`, `src/goe/scripts/agg_validate.py:146-176`), `older_than_days`/`older_than_date`/`less_than_value` (`normalise_less_than_options`, `src/goe/offload/offload.py`). Annotations for these fields must be unions that admit both shapes.

## CLI-only derived flags (popped before struct construction, never struct fields)

Defined in `src/goe/cli/commands/offload.py` and applied in `offload()` at lines 528-537:

| Click dest | Effect |
| :--- | :--- |
| `no_modify_hybrid_view` | `offload_predicate_modify_hybrid_view = False` |
| `no_verify` | `verify_row_count = False` |
| `verify` | `verify_row_count = verify.lower()` |

## Listener REST schema (`src/goe/listener/schemas.py:160-302`)

`OffloadOptions(BaseStruct)` declares 96 fields: the 84 `EXPECTED_OFFLOAD_ARGS` keys except `operation_name`, 10 alias fields, and `quiet`/`verbose` (dropped by `to_params_dict`). Every field defaults to `None` except `owner_table` (required) and `execute` (`True`).

| Alias field | Canonical key | Rule (baseline line) |
| :--- | :--- | :--- |
| `target_table_name` | `target_owner_name` | rename (264-276) |
| `bucket_hash_column` | `bucket_hash_col` | rename |
| `offload_chunk_count` | `max_offload_chunk_count` | rename |
| `allow_floating_point` | `allow_floating_point_conversions` | rename |
| `compress_backend_table` | `compress_load_table` | rename |
| `replace_hybrid_view` | `reset_hybrid_view` | rename |
| `partitions` | `partition_names_csv` | CSV join (278-288) |
| `sort_columns` | `sort_columns_csv` | CSV join |
| `partition_functions` | `offload_partition_functions` | CSV join |
| `subpartitions` | `partition_names_csv` + `offload_by_subpartition=True` | special (290-295) |

## `EXPECTED_OFFLOAD_ARGS` (`src/goe/goe.py:154-240`)

85 unique keys, in this exact order: `allow_decimal_scale_rounding`, `allow_floating_point_conversions`, `allow_nanosecond_timestamp_columns`, `bucket_hash_col`, `column_transformation_list`, `compress_load_table`, `compute_load_table_stats`, `create_backend_db`, `data_sample_parallelism`, `data_sample_pct`, `date_columns_csv`, `ddl_file`, `decimal_columns_csv_list`, `decimal_columns_type_list`, `decimal_padding_digits`, `double_columns_csv`, `equal_to_values`, `error_before_step`, `error_after_step`, `execute`, `force`, `hive_column_stats`, `impala_insert_hint`, `integer_1_columns_csv`, `integer_2_columns_csv`, `integer_4_columns_csv`, `integer_8_columns_csv`, `integer_38_columns_csv`, `ipa_predicate_type`, `less_than_value`, `max_offload_chunk_count`, `max_offload_chunk_size`, `not_null_columns_csv`, `offload_by_subpartition`, `offload_chunk_column`, `offload_distribute_enabled`, `offload_fs_container`, `offload_fs_prefix`, `offload_fs_scheme`, `offload_partition_columns`, `offload_partition_functions`, `offload_partition_granularity`, `offload_partition_lower_value`, `offload_partition_upper_value`, `offload_predicate`, `offload_predicate_modify_hybrid_view`, `offload_stats_method`, `offload_transport_method`, `offload_transport_consistent_read`, `offload_transport_dsn`, `offload_transport_fetch_size`, `offload_transport_jvm_overrides`, `offload_transport_queue_name`, `offload_transport_parallelism`, `offload_transport_small_table_threshold`, `offload_transport_snapshot`, `offload_transport_spark_properties`, `offload_transport_validation_polling_interval`, `offload_type`, `older_than_date`, `older_than_days`, `operation_name`, `owner_table`, `partition_names_csv`, `preserve_load_table`, `purge_backend_table`, `reset_backend_table`, `reset_hybrid_view`, `reuse_backend_table`, `sort_columns_csv`, `sqoop_additional_options`, `sqoop_mapreduce_map_memory_mb`, `sqoop_mapreduce_map_java_opts`, `skip`, `storage_compression`, `storage_format`, `synthetic_partition_digits`, `suppress_stdout`, `target_owner_name`, `timestamp_tz_columns_csv`, `unicode_string_columns_csv`, `variable_string_columns_csv`, `ver_check`, `verify_parallelism`, `verify_row_count`.

The 96-key offload parser set equals `EXPECTED_OFFLOAD_ARGS - {operation_name}` (84) plus 12 non-operation keys: `ansi`, `dev_log`, `dev_log_level`, `error_on_token`, `log_level`, `log_path`, `not_null_propagation`, `quiet`, `target`, `verbose`, `version`, `vverbose`.

## Field tables (generated)

`offload_stats_method` uses `orchestration_defaults.offload_stats_method_default()` with no argument: the function only diverges for `PRESENT_OP_NAME` (`src/goe/config/orchestration_defaults.py:292-296`), which no struct uses.

### CommonOptions (get_common_options) (14 fields)

| Field | Flag | Annotation | Default source | optparse action | Source |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `version` | `--version` | `bool` | `orchestration_defaults.version_default()` | `store_true` | `goe.py:2688` |
| `execute` | `--execute` | `bool` | `orchestration_defaults.execute_default()` | `store_true` | `goe.py:2696` |
| `log_path` | `--log-path` | `str` | `orchestration_defaults.log_path_default()` | `store` | `goe.py:2705` |
| `log_level` | `--log-level` | `str \| None` | `orchestration_defaults.log_level_default()` | `store` | `goe.py:2711` |
| `verbose` | `-v` | `bool` | `orchestration_defaults.verbose_default()` | `store_true` | `goe.py:2717` |
| `vverbose` | `--vv` | `bool` | `orchestration_defaults.vverbose_default()` | `store_true` | `goe.py:2724` |
| `quiet` | `--quiet` | `bool` | `orchestration_defaults.quiet_default()` | `store_true` | `goe.py:2731` |
| `skip` | `--skip-steps` | `str \| list[str]` | `orchestration_defaults.skip_default()` | `store` | `goe.py:2738` |
| `ver_check` | `--no-version-check` | `bool` | `orchestration_defaults.ver_check_default()` | `store_false` | `goe.py:2745` |
| `error_before_step` | `--error-before-step` | `str \| None` | `None` | `store` | `goe.py:2753` |
| `error_after_step` | `--error-after-step` | `str \| None` | `None` | `store` | `goe.py:2755` |
| `error_on_token` | `--error-on-token` | `str \| None` | `None` | `store` | `goe.py:2757` |
| `ansi` | `--no-ansi` | `bool` | `orchestration_defaults.ansi_default()` | `store_false` | `goe.py:2759` |
| `suppress_stdout` | `--suppress-stdout` | `bool` | `orchestration_defaults.suppress_stdout_default()` | `store` | `goe.py:2765` |

### TableOperationOptions (40, from get_options) + OffloadOperationOptions (42, from get_offload_options) additions (82 fields; rows sourced from goe.py belong to TableOperationOptions, rows sourced from offload/offload.py belong to OffloadOperationOptions)

| Field | Flag | Annotation | Default source | optparse action | Source |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `owner_table` | `--table` | `str \| None` | `None` | `store` | `goe.py:2830` |
| `target` | `--target` | `str` | `orchestration_defaults.query_engine_default()` | `store` | `goe.py:2836` |
| `target_owner_name` | `--target-name` | `str \| None` | `None` | `store` | `goe.py:2842` |
| `force` | `--force` | `bool` | `orchestration_defaults.force_default()` | `store_true` | `goe.py:2847` |
| `create_backend_db` | `--create-backend-db` | `bool` | `orchestration_defaults.create_backend_db_default()` | `store_true` | `goe.py:2855` |
| `reset_backend_table` | `--reset-backend-table` | `bool` | `False` | `store_true` | `goe.py:2865` |
| `reset_hybrid_view` | `--reset-hybrid-view` | `bool` | `False` | `store_true` | `goe.py:2872` |
| `reuse_backend_table` | `--reuse-backend-table` | `bool` | `False` | `store_true` | `goe.py:2879` |
| `purge_backend_table` | `--purge` | `bool` | `orchestration_defaults.purge_backend_table_default()` | `store_true` | `goe.py:2886` |
| `equal_to_values` | `--equal-to-values` | `list[str] \| None` | `None` | `append` | `goe.py:2893` |
| `less_than_value` | `--less-than-value` | `str \| int \| None` | `None` | `store` | `goe.py:2899` |
| `older_than_days` | `--older-than-days` | `str \| int \| None` | `None` | `store` | `goe.py:2904` |
| `older_than_date` | `--older-than-date` | `str \| None` | `None` | `store` | `goe.py:2912` |
| `partition_names_csv` | `--partition-names` | `str \| None` | `None` | `store` | `goe.py:2917` |
| `max_offload_chunk_size` | `--max-offload-chunk-size` | `str \| int` | `orchestration_defaults.max_offload_chunk_size_default()` | `store` | `goe.py:2927` |
| `max_offload_chunk_count` | `--max-offload-chunk-count` | `str \| int` | `orchestration_defaults.max_offload_chunk_count_default()` | `store` | `goe.py:2933` |
| `bucket_hash_col` | `--bucket-hash-column` | `str \| None` | `None` | `store` | `goe.py:2939` |
| `not_null_propagation` | `--not-null-propagation` | `str` | `orchestration_defaults.not_null_propagation_default()` | `store` | `goe.py:2944` |
| `offload_partition_columns` | `--partition-columns` | `str \| None` | `None` | `store` | `goe.py:2951` |
| `synthetic_partition_digits` | `--partition-digits` | `int` | `orchestration_defaults.synthetic_partition_digits_default()` | `store` | `goe.py:2956` |
| `offload_partition_functions` | `--partition-functions` | `str \| None` | `None` | `store` | `goe.py:2962` |
| `offload_partition_granularity` | `--partition-granularity` | `str \| None` | `None` | `store` | `goe.py:2967` |
| `offload_partition_lower_value` | `--partition-lower-value` | `str \| int \| None` | `None` | `store` | `goe.py:2976` |
| `offload_partition_upper_value` | `--partition-upper-value` | `str \| int \| None` | `None` | `store` | `goe.py:2981` |
| `storage_format` | `--storage-format` | `str \| None` | `orchestration_defaults.storage_format_default()` | `store` | `goe.py:2987` |
| `storage_compression` | `--storage-compression` | `str` | `orchestration_defaults.storage_compression_default()` | `store` | `goe.py:2993` |
| `hive_column_stats` | `--hive-column-stats` | `bool` | `orchestration_defaults.hive_column_stats_default()` | `store_true` | `goe.py:2999` |
| `offload_stats_method` | `--offload-stats` | `str` | `orchestration_defaults.offload_stats_method_default(operation_name=operation_name)` | `store` | `goe.py:3006` |
| `preserve_load_table` | `--preserve-load-table` | `bool` | `orchestration_defaults.preserve_load_table_default()` | `store_true` | `goe.py:3018` |
| `offload_by_subpartition` | `--offload-by-subpartition` | `bool` | `False` | `store_true` | `goe.py:3027` |
| `offload_chunk_column` | `--offload-chunk-column` | `str \| None` | `None` | `store` | `goe.py:3034` |
| `impala_insert_hint` | `--offload-chunk-impala-insert-hint` | `str \| None` | `None` | `store` | `goe.py:3039` |
| `decimal_padding_digits` | `--decimal-padding-digits` | `int` | `orchestration_defaults.decimal_padding_digits_default()` | `store` | `goe.py:3045` |
| `sort_columns_csv` | `--sort-columns` | `str` | `orchestration_defaults.sort_columns_default()` | `store` | `goe.py:3052` |
| `offload_distribute_enabled` | `--offload-distribute-enabled` | `bool` | `orchestration_defaults.offload_distribute_enabled_default()` | `store_true` | `goe.py:3058` |
| `offload_predicate` | `--offload-predicate` | `Any` | `None` | `store` | `goe.py:3066` |
| `offload_predicate_modify_hybrid_view` | `--no-modify-hybrid-view` | `bool` | `orchestration_defaults.offload_predicate_modify_hybrid_view_default()` | `store_false` | `goe.py:3072` |
| `dev_log` | `--dev-log` | `str \| None` | `None` | `store` | `goe.py:3090` |
| `dev_log_level` | `--dev-log-level` | `str` | `orchestration_defaults.dev_log_level_default()` | `store` | `goe.py:3092` |
| `column_transformation_list` | `--transform-column` | `list[str] \| None` | `None` | `append` | `goe.py:3099` |
| `allow_decimal_scale_rounding` | `--allow-decimal-scale-rounding` | `bool` | `orchestration_defaults.allow_decimal_scale_rounding_default()` | `store_true` | `offload/offload.py:382` |
| `allow_floating_point_conversions` | `--allow-floating-point-conversions` | `bool` | `orchestration_defaults.allow_floating_point_conversions_default()` | `store_true` | `offload/offload.py:389` |
| `allow_nanosecond_timestamp_columns` | `--allow-nanosecond-timestamp-columns` | `bool` | `orchestration_defaults.allow_nanosecond_timestamp_columns_default()` | `store_true` | `offload/offload.py:396` |
| `compress_load_table` | `--compress-load-table` | `bool` | `orchestration_defaults.compress_load_table_default()` | `store_true` | `offload/offload.py:403` |
| `compute_load_table_stats` | `--compute-load-table-stats` | `bool` | `orchestration_defaults.compute_load_table_stats_default()` | `store_true` | `offload/offload.py:410` |
| `data_sample_pct` | `--data-sample-percent` | `str \| int \| float` | `orchestration_defaults.data_sample_pct_default()` | `store` | `offload/offload.py:417` |
| `data_sample_parallelism` | `--data-sample-parallelism` | `int \| str` | `orchestration_defaults.data_sample_parallelism_default()` | `store` | `offload/offload.py:423` |
| `ddl_file` | `--ddl-file` | `str \| None` | `None` | `store` | `offload/offload.py:430` |
| `not_null_columns_csv` | `--not-null-columns` | `str \| None` | `None` | `store` | `offload/offload.py:438` |
| `ipa_predicate_type` | `--offload-predicate-type` | `str \| None` | `None` | `store` | `offload/offload.py:443` |
| `offload_fs_scheme` | `--offload-fs-scheme` | `str` | `orchestration_defaults.offload_fs_scheme_default()` | `store` | `offload/offload.py:452` |
| `offload_fs_prefix` | `--offload-fs-prefix` | `str \| None` | `None` | `store` | `offload/offload.py:458` |
| `offload_fs_container` | `--offload-fs-container` | `str \| None` | `None` | `store` | `offload/offload.py:463` |
| `offload_type` | `--offload-type` | `str \| None` | `None` | `store` | `offload/offload.py:468` |
| `integer_1_columns_csv` | `--integer-1-columns` | `str \| None` | `None` | `store` | `offload/offload.py:477` |
| `integer_2_columns_csv` | `--integer-2-columns` | `str \| None` | `None` | `store` | `offload/offload.py:482` |
| `integer_4_columns_csv` | `--integer-4-columns` | `str \| None` | `None` | `store` | `offload/offload.py:487` |
| `integer_8_columns_csv` | `--integer-8-columns` | `str \| None` | `None` | `store` | `offload/offload.py:492` |
| `integer_38_columns_csv` | `--integer-38-columns` | `str \| None` | `None` | `store` | `offload/offload.py:497` |
| `decimal_columns_csv_list` | `--decimal-columns` | `list[str] \| None` | `None` | `append` | `offload/offload.py:503` |
| `decimal_columns_type_list` | `--decimal-columns-type` | `list[str] \| None` | `None` | `append` | `offload/offload.py:514` |
| `date_columns_csv` | `--date-columns` | `str \| None` | `None` | `store` | `offload/offload.py:523` |
| `unicode_string_columns_csv` | `--unicode-string-columns` | `str \| None` | `None` | `store` | `offload/offload.py:529` |
| `double_columns_csv` | `--double-columns` | `str \| None` | `None` | `store` | `offload/offload.py:534` |
| `variable_string_columns_csv` | `--variable-string-columns` | `str \| None` | `None` | `store` | `offload/offload.py:539` |
| `timestamp_tz_columns_csv` | `--timestamp-tz-columns` | `str \| None` | `None` | `store` | `offload/offload.py:544` |
| `offload_transport_consistent_read` | `--offload-transport-consistent-read` | `str \| bool` | `orchestration_defaults.offload_transport_consistent_read_default()` | `store` | `offload/offload.py:550` |
| `offload_transport_dsn` | `--offload-transport-dsn` | `str \| None` | `orchestration_defaults.offload_transport_dsn_default()` | `store` | `offload/offload.py:556` |
| `offload_transport_fetch_size` | `--offload-transport-fetch-size` | `str \| int` | `orchestration_defaults.offload_transport_fetch_size_default()` | `store` | `offload/offload.py:562` |
| `offload_transport_jvm_overrides` | `--offload-transport-jvm-overrides` | `str \| None` | `None` | `store` | `offload/offload.py:568` |
| `offload_transport_method` | `--offload-transport-method` | `str \| None` | `None` | `store` | `offload/offload.py:573` |
| `offload_transport_parallelism` | `--offload-transport-parallelism` | `str \| int` | `orchestration_defaults.offload_transport_parallelism_default()` | `store` | `offload/offload.py:579` |
| `offload_transport_queue_name` | `--offload-transport-queue-name` | `str \| None` | `None` | `store` | `offload/offload.py:585` |
| `offload_transport_small_table_threshold` | `--offload-transport-small-table-threshold` | `str \| int \| float` | `orchestration_defaults.offload_transport_small_table_threshold_default()` | `store` | `offload/offload.py:590` |
| `offload_transport_snapshot` | `--offload-transport-snapshot` | `str \| int \| None` | `None` | `store` | `offload/offload.py:599` |
| `offload_transport_spark_properties` | `--offload-transport-spark-properties` | `str \| dict[str, Any] \| None` | `orchestration_defaults.offload_transport_spark_properties_default()` | `store` | `offload/offload.py:607` |
| `offload_transport_validation_polling_interval` | `--offload-transport-validation-polling-interval` | `str \| int \| float` | `orchestration_defaults.offload_transport_validation_polling_interval_default()` | `store` | `offload/offload.py:613` |
| `sqoop_additional_options` | `--sqoop-additional-options` | `str \| None` | `orchestration_defaults.sqoop_additional_options_default()` | `store` | `offload/offload.py:625` |
| `sqoop_mapreduce_map_memory_mb` | `--sqoop-mapreduce-map-memory-mb` | `str \| int \| None` | `None` | `store` | `offload/offload.py:631` |
| `sqoop_mapreduce_map_java_opts` | `--sqoop-mapreduce-map-java-opts` | `str \| None` | `None` | `store` | `offload/offload.py:636` |
| `verify_row_count` | `--verify` / `--no-verify` | `str \| bool \| None` | `orchestration_defaults.verify_row_count_default()` | `store` / `store_false` | `offload/offload.py:642-648` |
| `verify_parallelism` | `--verify-parallelism` | `int \| str \| None` | `orchestration_defaults.verify_parallelism_default()` | `store` | `offload/offload.py:649` |

### ConnectOptions additions (get_connect_opts) (2 fields)

| Field | Flag | Annotation | Default source | optparse action | Source |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `upgrade_environment_file` | `--upgrade-environment-file` | `bool` | `False` | `store_true` | `connect/connect.py:446` |
| `create_backend_db` | `--create-backend-db` | `bool \| None` | `None` | `store_true` | `connect/connect.py:454` |

Options removed from this parser with `remove_option` (their defaults remain in the legacy `Values`, so the inherited struct fields stay): `['execute']`

### StatusReportOptions additions (get_offload_status_report_opts) (9 fields)

| Field | Flag | Annotation | Default source | optparse action | Source |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `schema` | `--schema` | `str \| None` | `None` | `store` | `offload/offload_status_report.py:3606` |
| `table` | `--table` | `str \| None` | `None` | `store` | `offload/offload_status_report.py:3612` |
| `output_format` | `--output-format` | `str` | `DEFAULT_OUTPUT_FORMAT` | `store` | `offload/offload_status_report.py:3618` |
| `demo_mode` | `--demo` | `bool` | `DEFAULT_DEMO_MODE` | `store_true` | `offload/offload_status_report.py:3626` |
| `output_level` | `--output-level` | `str` | `DEFAULT_OUTPUT_LEVEL` | `store` | `offload/offload_status_report.py:3634` |
| `report_name` | `--report-name` | `str` | `DEFAULT_REPORT_NAME` | `store` | `offload/offload_status_report.py:3641` |
| `report_directory` | `--report-directory` | `str` | `DEFAULT_REPORT_DIRECTORY` | `store` | `offload/offload_status_report.py:3648` |
| `csv_delimiter` | `--csv-delimiter` | `str` | `DEFAULT_CSV_DELIMITER` | `store` | `offload/offload_status_report.py:3654` |
| `csv_enclosure` | `--csv-enclosure` | `str` | `DEFAULT_CSV_ENCLOSURE` | `store` | `offload/offload_status_report.py:3661` |

Options removed from this parser with `remove_option` (their defaults remain in the legacy `Values`, so the inherited struct fields stay): `['execute', 'log_path', 'skip']`

### SchemaSyncOptions additions (get_schema_sync_opts) (2 fields)

| Field | Flag | Annotation | Default source | optparse action | Source |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `include` | `--include` | `str \| None` | `None` | `store` | `schema_sync/schema_sync.py:32` |
| `command_file` | `--command-file` | `str \| None` | `None` | `store` | `schema_sync/schema_sync.py:37` |

Options removed from this parser with `remove_option` (their defaults remain in the legacy `Values`, so the inherited struct fields stay): `['log_path', 'skip']`

### AggValidateOptions additions (7 own fields; the remaining 54 keys are inherited from TableOperationOptions)

| Field | Flag | Annotation | Default source | optparse action | Source |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `as_of_scn` | `--as-of-scn` | `int \| None` | `None` | `store` | `scripts/agg_validate.py:183` |
| `selects` | `--selects` | `list[str \| int] \| str \| int` | `[DEFAULT_SELECT_COLS]` | `store` | `scripts/agg_validate.py:189` |
| `filters` | `--filters` | `str \| list[tuple[str, str, object]] \| None` | `None` | `store` | `scripts/agg_validate.py:196` |
| `group_bys` | `--group-bys` | `str \| list[str] \| None` | `None` | `store` | `scripts/agg_validate.py:202` |
| `aggregate_functions` | `--aggregate-functions` | `tuple[str, ...] \| list[str] \| str` | `DEFAULT_AGGS` | `store` | `scripts/agg_validate.py:209` |
| `frontend_parallelism` | `--frontend-parallelism` | `int \| str \| None` | `orchestration_defaults.verify_parallelism_default()` | `store` | `scripts/agg_validate.py:216` |
| `skip_boundary_check` | `--skip-boundary-check` | `bool \| None` | `None` | `store_true` | `scripts/agg_validate.py:222` |

`get_options_from_list` (`src/goe/goe.py:3109-3127`) removes every `get_options` option whose dest is not in `GOE_OPTIONS + HS2_OPTIONS`, but all 54 defaults remain in the legacy `Values`; `AggValidateOptions(TableOperationOptions)` therefore inherits all of them.
