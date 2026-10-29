# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Declarative backend capability and limit specifications."""

from collections.abc import Mapping
from typing import Any

import msgspec

from goe.offload.offload_constants import (
    BIGQUERY_BACKEND_CAPABILITIES,
    CAPABILITY_BUCKET_HASH_COLUMN,
    CAPABILITY_CANONICAL_DATE,
    CAPABILITY_CANONICAL_TIME,
    CAPABILITY_CASE_SENSITIVE,
    CAPABILITY_COLUMN_STATS_SET,
    CAPABILITY_CREATE_DB,
    CAPABILITY_DROP_COLUMN,
    CAPABILITY_FS_SCHEME_ABFS,
    CAPABILITY_FS_SCHEME_ADL,
    CAPABILITY_FS_SCHEME_GS,
    CAPABILITY_FS_SCHEME_HDFS,
    CAPABILITY_FS_SCHEME_INHERIT,
    CAPABILITY_FS_SCHEME_S3A,
    CAPABILITY_FS_SCHEME_WASB,
    CAPABILITY_GOE_COLUMN_TRANSFORMATIONS,
    CAPABILITY_GOE_PARTITION_FUNCTIONS,
    CAPABILITY_LOAD_DB_TRANSPORT,
    CAPABILITY_NAN,
    CAPABILITY_NANOSECONDS,
    CAPABILITY_NOT_NULL_COLUMN,
    CAPABILITY_PARAMETERIZED_QUERIES,
    CAPABILITY_PARTITION_BY_COLUMN,
    CAPABILITY_PARTITION_BY_STRING,
    CAPABILITY_QUERY_SAMPLE_CLAUSE,
    CAPABILITY_RANGER,
    CAPABILITY_SCHEMA_EVOLUTION,
    CAPABILITY_SENTRY,
    CAPABILITY_SORTED_TABLE,
    CAPABILITY_SORTED_TABLE_MODIFY,
    CAPABILITY_SQL_MICROSECOND_PREDICATE,
    CAPABILITY_SYNTHETIC_PARTITIONING,
    CAPABILITY_TABLE_STATS_COMPUTE,
    CAPABILITY_TABLE_STATS_GET,
    CAPABILITY_TABLE_STATS_SET,
    DBTYPE_BIGQUERY,
    DBTYPE_HIVE,
    DBTYPE_IMPALA,
    DBTYPE_SNOWFLAKE,
    DBTYPE_SPARK,
    DBTYPE_SYNAPSE,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
    HIVE_BACKEND_CAPABILITIES,
    IMPALA_BACKEND_CAPABILITIES,
    PART_COL_GRANULARITY_DAY,
    PART_COL_GRANULARITY_MONTH,
    PART_COL_GRANULARITY_YEAR,
    SNOWFLAKE_BACKEND_CAPABILITIES,
    SPARK_BACKEND_CAPABILITIES,
    SYNAPSE_BACKEND_CAPABILITIES,
)
from goe.typing import FrozenBaseStruct

__all__ = [
    "CAPABILITY_FIELD_MAP",
    "BackendCapabilities",
]

CAPABILITY_FIELD_MAP: dict[str, str] = {
    CAPABILITY_BUCKET_HASH_COLUMN: "bucket_hash_column",
    CAPABILITY_CANONICAL_DATE: "canonical_date",
    CAPABILITY_CANONICAL_TIME: "canonical_time",
    CAPABILITY_CASE_SENSITIVE: "case_sensitive",
    CAPABILITY_COLUMN_STATS_SET: "column_stats_set",
    CAPABILITY_CREATE_DB: "create_db",
    CAPABILITY_DROP_COLUMN: "drop_column",
    CAPABILITY_FS_SCHEME_ABFS: "fs_scheme_abfs",
    CAPABILITY_FS_SCHEME_ADL: "fs_scheme_adl",
    CAPABILITY_FS_SCHEME_GS: "fs_scheme_gs",
    CAPABILITY_FS_SCHEME_HDFS: "fs_scheme_hdfs",
    CAPABILITY_FS_SCHEME_INHERIT: "fs_scheme_inherit",
    CAPABILITY_FS_SCHEME_S3A: "fs_scheme_s3a",
    CAPABILITY_FS_SCHEME_WASB: "fs_scheme_wasb",
    CAPABILITY_GOE_COLUMN_TRANSFORMATIONS: "goe_column_transformations",
    CAPABILITY_GOE_PARTITION_FUNCTIONS: "goe_partition_functions",
    CAPABILITY_LOAD_DB_TRANSPORT: "load_db_transport",
    CAPABILITY_NAN: "nan",
    CAPABILITY_NANOSECONDS: "nanoseconds",
    CAPABILITY_NOT_NULL_COLUMN: "not_null_column",
    CAPABILITY_PARAMETERIZED_QUERIES: "parameterized_queries",
    CAPABILITY_PARTITION_BY_COLUMN: "partition_by_column",
    CAPABILITY_PARTITION_BY_STRING: "partition_by_string",
    CAPABILITY_QUERY_SAMPLE_CLAUSE: "query_sample_clause",
    CAPABILITY_RANGER: "ranger",
    CAPABILITY_SCHEMA_EVOLUTION: "schema_evolution",
    CAPABILITY_SENTRY: "sentry",
    CAPABILITY_SORTED_TABLE: "sorted_table",
    CAPABILITY_SORTED_TABLE_MODIFY: "sorted_table_modify",
    CAPABILITY_SQL_MICROSECOND_PREDICATE: "sql_microsecond_predicate",
    CAPABILITY_SYNTHETIC_PARTITIONING: "synthetic_partitioning",
    CAPABILITY_TABLE_STATS_COMPUTE: "table_stats_compute",
    CAPABILITY_TABLE_STATS_GET: "table_stats_get",
    CAPABILITY_TABLE_STATS_SET: "table_stats_set",
}


class BackendCapabilities(FrozenBaseStruct, frozen=True):
    """Immutable capability and limit descriptor for a backend data warehouse."""

    backend_type: str
    bucket_hash_column: bool = False
    canonical_date: bool = True
    canonical_time: bool = False
    case_sensitive: bool = False
    column_stats_set: bool = False
    create_db: bool = True
    drop_column: bool = True
    fs_scheme_abfs: bool = False
    fs_scheme_adl: bool = False
    fs_scheme_gs: bool = False
    fs_scheme_hdfs: bool = False
    fs_scheme_inherit: bool = False
    fs_scheme_s3a: bool = False
    fs_scheme_wasb: bool = False
    goe_column_transformations: bool = False
    goe_partition_functions: bool = False
    load_db_transport: bool = True
    nan: bool = False
    nanoseconds: bool = False
    not_null_column: bool = True
    parameterized_queries: bool = False
    partition_by_column: bool = True
    partition_by_string: bool = False
    query_sample_clause: bool = False
    ranger: bool = False
    schema_evolution: bool = True
    sentry: bool = False
    sorted_table: bool = False
    sorted_table_modify: bool = False
    sql_microsecond_predicate: bool = True
    synthetic_partitioning: bool = True
    table_stats_compute: bool = False
    table_stats_get: bool = False
    table_stats_set: bool = False
    default_sort_columns_to_primary_key: bool = False
    synthetic_partition_numbers_are_string: bool = False
    max_decimal_precision: int = 38
    max_decimal_scale: int = 38
    max_decimal_integral_magnitude: int = 38
    max_datetime_scale: int = 6
    max_partition_columns: int = 1
    max_sort_columns: int = 4
    max_table_name_length: int = 128
    max_db_name_length: int = 128
    max_column_name_length: int = 128
    valid_staging_formats: tuple[str, ...] = (FILE_STORAGE_FORMAT_AVRO, FILE_STORAGE_FORMAT_PARQUET)
    supported_date_partition_granularities: tuple[str, ...] = (
        PART_COL_GRANULARITY_YEAR,
        PART_COL_GRANULARITY_MONTH,
        PART_COL_GRANULARITY_DAY,
    )

    @property
    def sorted_table_modify_effective(self) -> bool:
        """Return True only when both sorted tables and sorted table modification are supported."""
        return bool(self.sorted_table and self.sorted_table_modify)

    def supports(self, capability_constant: str) -> bool:
        """Return True when the given legacy CAPABILITY_* constant is enabled."""
        field_name = CAPABILITY_FIELD_MAP.get(capability_constant)
        if field_name is None:
            raise KeyError(f"Unknown capability: {capability_constant}")
        return bool(getattr(self, field_name))

    def to_capability_dict(self) -> dict[str, bool]:
        """Return a legacy CAPABILITY_* dictionary matching offload_constants."""
        return {cap_key: bool(getattr(self, field_name)) for cap_key, field_name in CAPABILITY_FIELD_MAP.items()}

    def replace(self, **changes: Any) -> "BackendCapabilities":
        """Return a copy of these capabilities with updated fields."""
        return msgspec.structs.replace(self, **changes)

    @classmethod
    def from_capability_dict(
        cls,
        backend_type: str,
        cap_dict: Mapping[str, bool],
        **extra_limits: Any,
    ) -> "BackendCapabilities":
        """Build BackendCapabilities from a legacy CAPABILITY_* mapping and optional limit overrides."""
        kwargs: dict[str, Any] = {"backend_type": backend_type}
        for cap_key, field_name in CAPABILITY_FIELD_MAP.items():
            if cap_key in cap_dict:
                kwargs[field_name] = bool(cap_dict[cap_key])
        kwargs.update(extra_limits)
        return cls(**kwargs)

    @classmethod
    def for_bigquery(cls) -> "BackendCapabilities":
        """Return the canonical BigQuery capability and limit profile."""
        return cls.from_capability_dict(
            DBTYPE_BIGQUERY,
            BIGQUERY_BACKEND_CAPABILITIES,
            default_sort_columns_to_primary_key=False,
            synthetic_partition_numbers_are_string=False,
            max_decimal_precision=76,
            max_decimal_scale=38,
            max_decimal_integral_magnitude=38,
            max_datetime_scale=6,
            max_partition_columns=1,
            max_sort_columns=4,
            max_table_name_length=1024,
            max_db_name_length=1024,
            max_column_name_length=300,
            valid_staging_formats=(FILE_STORAGE_FORMAT_AVRO, FILE_STORAGE_FORMAT_PARQUET),
        )

    @classmethod
    def for_snowflake(cls) -> "BackendCapabilities":
        """Return the canonical Snowflake capability and limit profile."""
        return cls.from_capability_dict(
            DBTYPE_SNOWFLAKE,
            SNOWFLAKE_BACKEND_CAPABILITIES,
            default_sort_columns_to_primary_key=False,
            synthetic_partition_numbers_are_string=False,
            max_decimal_precision=38,
            max_decimal_scale=37,
            max_decimal_integral_magnitude=38,
            max_datetime_scale=9,
            max_partition_columns=0,
            max_sort_columns=4,
            max_table_name_length=255,
            max_db_name_length=255,
            max_column_name_length=255,
        )

    @classmethod
    def for_synapse(cls) -> "BackendCapabilities":
        """Return the canonical Azure Synapse capability and limit profile."""
        return cls.from_capability_dict(
            DBTYPE_SYNAPSE,
            SYNAPSE_BACKEND_CAPABILITIES,
            default_sort_columns_to_primary_key=False,
            synthetic_partition_numbers_are_string=False,
            max_decimal_precision=38,
            max_decimal_scale=38,
            max_decimal_integral_magnitude=38,
            max_datetime_scale=7,
            max_partition_columns=1,
            max_sort_columns=0,
            max_table_name_length=128,
            max_db_name_length=128,
            max_column_name_length=128,
            valid_staging_formats=(FILE_STORAGE_FORMAT_PARQUET,),
        )

    @classmethod
    def for_hive(cls) -> "BackendCapabilities":
        """Return the canonical Hive capability and limit profile."""
        return cls.from_capability_dict(
            DBTYPE_HIVE,
            HIVE_BACKEND_CAPABILITIES,
            default_sort_columns_to_primary_key=True,
            synthetic_partition_numbers_are_string=True,
            max_decimal_precision=38,
            max_decimal_scale=38,
            max_decimal_integral_magnitude=38,
            max_datetime_scale=9,
            max_partition_columns=100,
            max_sort_columns=100,
            max_table_name_length=128,
            max_db_name_length=128,
            max_column_name_length=128,
        )

    @classmethod
    def for_impala(cls) -> "BackendCapabilities":
        """Return the canonical Impala capability and limit profile."""
        return cls.from_capability_dict(
            DBTYPE_IMPALA,
            IMPALA_BACKEND_CAPABILITIES,
            default_sort_columns_to_primary_key=False,
            synthetic_partition_numbers_are_string=True,
            max_decimal_precision=38,
            max_decimal_scale=38,
            max_decimal_integral_magnitude=38,
            max_datetime_scale=9,
            max_partition_columns=100,
            max_sort_columns=100,
            max_table_name_length=128,
            max_db_name_length=128,
            max_column_name_length=128,
        )

    @classmethod
    def for_spark(cls) -> "BackendCapabilities":
        """Return the canonical Spark Thrift capability and limit profile."""
        return cls.from_capability_dict(
            DBTYPE_SPARK,
            SPARK_BACKEND_CAPABILITIES,
            default_sort_columns_to_primary_key=False,
            synthetic_partition_numbers_are_string=True,
            max_decimal_precision=38,
            max_decimal_scale=38,
            max_decimal_integral_magnitude=38,
            max_datetime_scale=6,
            max_partition_columns=100,
            max_sort_columns=100,
            max_table_name_length=128,
            max_db_name_length=128,
            max_column_name_length=128,
        )

    @classmethod
    def for_backend(
        cls,
        backend_type: str,
        capabilities_dict: Mapping[str, bool] | None = None,
    ) -> "BackendCapabilities":
        """Resolve BackendCapabilities for a backend type with optional dictionary overrides."""
        presets = {
            DBTYPE_BIGQUERY: cls.for_bigquery,
            DBTYPE_SNOWFLAKE: cls.for_snowflake,
            DBTYPE_SYNAPSE: cls.for_synapse,
            DBTYPE_HIVE: cls.for_hive,
            DBTYPE_IMPALA: cls.for_impala,
            DBTYPE_SPARK: cls.for_spark,
        }
        factory = presets.get(backend_type)
        base = factory() if factory is not None else cls(backend_type=backend_type)
        if not capabilities_dict:
            return base
        updates = {
            field_name: bool(capabilities_dict[cap_key])
            for cap_key, field_name in CAPABILITY_FIELD_MAP.items()
            if cap_key in capabilities_dict
        }
        return base.replace(**updates)
