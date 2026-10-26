# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Table-driven canonical-to-physical and physical-to-canonical column type registry."""

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.schema.column_spec import (
    ALL_CANONICAL_TYPES,
    AVRO_TYPE_BOOLEAN,
    AVRO_TYPE_BYTES,
    AVRO_TYPE_DOUBLE,
    AVRO_TYPE_FLOAT,
    AVRO_TYPE_INT,
    AVRO_TYPE_LONG,
    AVRO_TYPE_STRING,
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_BOOLEAN,
    BIGQUERY_TYPE_BYTES,
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_FLOAT64,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    BIGQUERY_TYPE_TIME,
    BIGQUERY_TYPE_TIMESTAMP,
    CANONICAL_CHAR_SEMANTICS_BYTE,
    CANONICAL_CHAR_SEMANTICS_CHAR,
    CANONICAL_CHAR_SEMANTICS_UNICODE,
    DATE_CANONICAL_TYPES,
    GOE_TYPE_BINARY,
    GOE_TYPE_BOOLEAN,
    GOE_TYPE_DATE,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_DOUBLE,
    GOE_TYPE_FIXED_STRING,
    GOE_TYPE_FLOAT,
    GOE_TYPE_INTEGER_1,
    GOE_TYPE_INTEGER_2,
    GOE_TYPE_INTEGER_4,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_INTEGER_38,
    GOE_TYPE_INTERVAL_DS,
    GOE_TYPE_INTERVAL_YM,
    GOE_TYPE_LARGE_BINARY,
    GOE_TYPE_LARGE_STRING,
    GOE_TYPE_TIME,
    GOE_TYPE_TIMESTAMP,
    GOE_TYPE_TIMESTAMP_TZ,
    GOE_TYPE_VARIABLE_STRING,
    HADOOP_TYPE_BIGINT,
    HADOOP_TYPE_BINARY,
    HADOOP_TYPE_BOOLEAN,
    HADOOP_TYPE_CHAR,
    HADOOP_TYPE_DATE,
    HADOOP_TYPE_DECIMAL,
    HADOOP_TYPE_DOUBLE,
    HADOOP_TYPE_DOUBLE_PRECISION,
    HADOOP_TYPE_FLOAT,
    HADOOP_TYPE_INT,
    HADOOP_TYPE_INTERVAL_DS,
    HADOOP_TYPE_INTERVAL_YM,
    HADOOP_TYPE_REAL,
    HADOOP_TYPE_SMALLINT,
    HADOOP_TYPE_STRING,
    HADOOP_TYPE_TIMESTAMP,
    HADOOP_TYPE_TINYINT,
    HADOOP_TYPE_VARCHAR,
    MSSQL_TYPE_BIGINT,
    MSSQL_TYPE_BINARY,
    MSSQL_TYPE_BIT,
    MSSQL_TYPE_CHAR,
    MSSQL_TYPE_DATE,
    MSSQL_TYPE_DATETIME,
    MSSQL_TYPE_DATETIME2,
    MSSQL_TYPE_DATETIMEOFFSET,
    MSSQL_TYPE_DECIMAL,
    MSSQL_TYPE_FLOAT,
    MSSQL_TYPE_IMAGE,
    MSSQL_TYPE_INT,
    MSSQL_TYPE_MONEY,
    MSSQL_TYPE_NCHAR,
    MSSQL_TYPE_NTEXT,
    MSSQL_TYPE_NUMERIC,
    MSSQL_TYPE_NVARCHAR,
    MSSQL_TYPE_REAL,
    MSSQL_TYPE_SMALLDATETIME,
    MSSQL_TYPE_SMALLINT,
    MSSQL_TYPE_SMALLMONEY,
    MSSQL_TYPE_TEXT,
    MSSQL_TYPE_TIME,
    MSSQL_TYPE_TINYINT,
    MSSQL_TYPE_UNIQUEIDENTIFIER,
    MSSQL_TYPE_VARBINARY,
    MSSQL_TYPE_VARCHAR,
    NUMERIC_CANONICAL_TYPES,
    ORACLE_TYPE_BINARY_DOUBLE,
    ORACLE_TYPE_BINARY_FLOAT,
    ORACLE_TYPE_BLOB,
    ORACLE_TYPE_CHAR,
    ORACLE_TYPE_CLOB,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_FLOAT,
    ORACLE_TYPE_INTERVAL_DS,
    ORACLE_TYPE_INTERVAL_YM,
    ORACLE_TYPE_LONG,
    ORACLE_TYPE_LONG_RAW,
    ORACLE_TYPE_NCHAR,
    ORACLE_TYPE_NCLOB,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_NVARCHAR2,
    ORACLE_TYPE_RAW,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
    ORACLE_TYPE_TIMESTAMP_TZ,
    ORACLE_TYPE_VARCHAR,
    ORACLE_TYPE_VARCHAR2,
    ORACLE_TYPE_XMLTYPE,
    PARQUET_TYPE_BINARY,
    PARQUET_TYPE_BOOLEAN,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_FLOAT,
    PARQUET_TYPE_INT32,
    PARQUET_TYPE_INT64,
    PARQUET_TYPE_STRING,
    SNOWFLAKE_TYPE_BINARY,
    SNOWFLAKE_TYPE_BOOLEAN,
    SNOWFLAKE_TYPE_DATE,
    SNOWFLAKE_TYPE_FLOAT,
    SNOWFLAKE_TYPE_INTEGER,
    SNOWFLAKE_TYPE_NUMBER,
    SNOWFLAKE_TYPE_TEXT,
    SNOWFLAKE_TYPE_TIME,
    SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
    SNOWFLAKE_TYPE_TIMESTAMP_TZ,
    STRING_CANONICAL_TYPES,
    SYNAPSE_TYPE_BIGINT,
    SYNAPSE_TYPE_BINARY,
    SYNAPSE_TYPE_BIT,
    SYNAPSE_TYPE_CHAR,
    SYNAPSE_TYPE_DATE,
    SYNAPSE_TYPE_DATETIME,
    SYNAPSE_TYPE_DATETIME2,
    SYNAPSE_TYPE_DATETIMEOFFSET,
    SYNAPSE_TYPE_DECIMAL,
    SYNAPSE_TYPE_FLOAT,
    SYNAPSE_TYPE_INT,
    SYNAPSE_TYPE_MONEY,
    SYNAPSE_TYPE_NCHAR,
    SYNAPSE_TYPE_NUMERIC,
    SYNAPSE_TYPE_NVARCHAR,
    SYNAPSE_TYPE_REAL,
    SYNAPSE_TYPE_SMALLDATETIME,
    SYNAPSE_TYPE_SMALLINT,
    SYNAPSE_TYPE_SMALLMONEY,
    SYNAPSE_TYPE_TIME,
    SYNAPSE_TYPE_TINYINT,
    SYNAPSE_TYPE_UNIQUEIDENTIFIER,
    SYNAPSE_TYPE_VARBINARY,
    SYNAPSE_TYPE_VARCHAR,
    ColumnDialect,
    ColumnSpec,
    ColumnSpecError,
    is_safe_mapping,
)
from goe.typing import FrozenBaseStruct

__all__ = [
    "FROM_CANONICAL_RULES",
    "OVERRIDE_RULES",
    "TO_CANONICAL_RULES",
    "TYPE_REGISTRY",
    "CanonicalTypeRegistry",
    "ColumnGuard",
    "ColumnTransform",
    "MappingContext",
    "MappingRule",
    "MappingTarget",
    "OverrideRule",
    "TypeMappingLimits",
]


class MappingTarget(StrEnum):
    """Dialect and variant a canonical column is mapped to."""

    ORACLE = "oracle"
    MSSQL = "mssql"
    BIGQUERY = "bigquery"
    SNOWFLAKE = "snowflake"
    SYNAPSE = "synapse"
    HIVE = "hive"
    IMPALA = "impala"
    PARQUET = "parquet"
    AVRO = "avro"
    AVRO_IMPALA = "avro_impala"


class TypeMappingLimits(FrozenBaseStruct, frozen=True, kw_only=True):
    """Owner limits consulted by mapping rules."""

    max_datetime_scale: int | None = None
    max_decimal_precision: int | None = None
    max_decimal_scale: int | None = None
    max_decimal_integral_magnitude: int | None = None
    canonical_date_supported: bool = True
    canonical_time_supported: bool = True
    supported_data_types: frozenset[str] = frozenset()


class MappingContext(FrozenBaseStruct, frozen=True, kw_only=True):
    """Per-call inputs for a mapping rule."""

    limits: TypeMappingLimits
    decimal_padding_digits: int = 0
    binary_as_base64: bool = False
    use_staging_file_name: bool = False
    log: Callable[[str, int], None] | None = None


type ColumnGuard = Callable[[ColumnSpec, MappingContext], bool]
type ColumnTransform = Callable[[ColumnSpec, MappingContext], ColumnSpec]


class MappingRule(FrozenBaseStruct, frozen=True):
    """One ordered mapping rule: when the source type and guard match, apply the transform."""

    source_types: frozenset[str]
    transform: ColumnTransform
    guard: ColumnGuard | None = None


class OverrideRule(FrozenBaseStruct, frozen=True):
    """One ordered override rule: when the predicate matches, the allowed canonical types decide."""

    matches: ColumnGuard
    allowed: frozenset[str]


class _PrecisionGuards:
    """Shared precision, scale, and capability guards for rule tables."""

    @staticmethod
    def normalized_precision_scale(col: ColumnSpec) -> tuple[int | None, int | None]:
        """Return precision and scale adjusted for scale > precision or negative scale."""
        p, s = col.data_precision, col.data_scale
        if p is not None and s is not None:
            if s > p:
                p = s
            elif s < 0:
                s = 0
        return p, s

    @staticmethod
    def integral_range(low: int, high: int, *, require_unsafe: bool = False) -> ColumnGuard:
        """Return a guard matching scale 0 and normalized precision within [low, high]."""

        def guard(col: ColumnSpec, ctx: MappingContext) -> bool:
            p, s = _PrecisionGuards.normalized_precision_scale(col)
            if s != 0 or p is None:
                return False
            if require_unsafe and col.safe_mapping:
                return False
            return low <= p <= high

        return guard

    @staticmethod
    def scale_zero_with_precision(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when normalized scale is 0 and normalized precision is not None."""
        p, s = _PrecisionGuards.normalized_precision_scale(col)
        return s == 0 and p is not None

    @staticmethod
    def scale_zero(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when normalized scale is 0."""
        _, s = _PrecisionGuards.normalized_precision_scale(col)
        return s == 0

    @staticmethod
    def raw_scale_zero_precision_range(low: int, high: int) -> ColumnGuard:
        """Return a guard matching raw data_scale == 0 and raw data_precision in [low, high]."""

        def guard(col: ColumnSpec, ctx: MappingContext) -> bool:
            if col.data_scale != 0:
                return False
            assert col.data_precision is not None
            return low <= col.data_precision <= high

        return guard

    @staticmethod
    def raw_scale_zero(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when raw data_scale == 0."""
        return col.data_scale == 0

    @staticmethod
    def precision_at_most(limit: int) -> ColumnGuard:
        """Return a guard matching positive data_precision <= limit."""

        def guard(col: ColumnSpec, ctx: MappingContext) -> bool:
            return bool(col.data_precision and col.data_precision <= limit)

        return guard

    @staticmethod
    def integral_and_scale_at_most(max_integral: int, max_scale: int) -> ColumnGuard:
        """Return a guard matching positive integral magnitude <= max_integral and scale <= max_scale."""

        def guard(col: ColumnSpec, ctx: MappingContext) -> bool:
            if col.data_precision is None:
                return False
            integral_magnitude = col.data_precision - (col.data_scale or 0)
            return bool(
                integral_magnitude and integral_magnitude <= max_integral and (col.data_scale or 0) <= max_scale
            )

        return guard

    @staticmethod
    def canonical_date_not_supported(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when the target does not support a native canonical DATE."""
        return not ctx.limits.canonical_date_supported

    @staticmethod
    def is_safe(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when col.safe_mapping is truthy."""
        return bool(col.safe_mapping)

    @staticmethod
    def is_from_override(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when col.from_override is truthy."""
        return bool(col.from_override)

    @staticmethod
    def data_type_in(*types: str) -> ColumnGuard:
        """Return a guard matching column.data_type membership."""
        allowed = frozenset(types)

        def guard(col: ColumnSpec, ctx: MappingContext) -> bool:
            return col.data_type in allowed

        return guard

    @staticmethod
    def is_number(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when col.is_number_based()."""
        return col.is_number_based()

    @staticmethod
    def is_date_with_tz(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when col.is_date_based() and col.is_time_zone_based()."""
        return col.is_date_based() and col.is_time_zone_based()

    @staticmethod
    def is_date(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when col.is_date_based()."""
        return col.is_date_based()

    @staticmethod
    def is_string(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when col.is_string_based()."""
        return col.is_string_based()

    @staticmethod
    def unsupported_backend_type(col: ColumnSpec, ctx: MappingContext) -> bool:
        """Return True when supported_data_types is populated and excludes col.data_type."""
        return bool(ctx.limits.supported_data_types and col.data_type not in ctx.limits.supported_data_types)


class _OracleRules:
    """Oracle to-canonical and from-canonical transform helpers."""

    @staticmethod
    def make_canonical(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a canonical ColumnSpec from an Oracle ColumnSpec."""
        char_semantics = (
            CANONICAL_CHAR_SEMANTICS_UNICODE
            if col.data_type in (ORACLE_TYPE_NCHAR, ORACLE_TYPE_NVARCHAR2, ORACLE_TYPE_NCLOB)
            else col.char_semantics
        )
        return ColumnSpec(
            ColumnDialect.CANONICAL,
            col.name,
            data_type,
            data_length=data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            partition_info=None,
            char_length=col.char_length,
            char_semantics=char_semantics,
        )

    @staticmethod
    def make_oracle(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        char_length: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build an Oracle ColumnSpec from a canonical ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.ORACLE,
            col.name.upper(),
            data_type,
            data_length=data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            char_length=char_length,
            char_semantics=col.char_semantics,
        )

    @staticmethod
    def nchar_or_char(data_type: str, char_semantics: str | None) -> str:
        """Select national character Oracle types when semantics are UNICODE."""
        if char_semantics == CANONICAL_CHAR_SEMANTICS_UNICODE:
            if data_type == ORACLE_TYPE_CHAR:
                return ORACLE_TYPE_NCHAR
            if data_type == ORACLE_TYPE_CLOB:
                return ORACLE_TYPE_NCLOB
            if data_type == ORACLE_TYPE_VARCHAR2:
                return ORACLE_TYPE_NVARCHAR2
        return data_type

    @staticmethod
    def to_fixed_string(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle CHAR/NCHAR to GOE_TYPE_FIXED_STRING."""
        return _OracleRules.make_canonical(
            col,
            GOE_TYPE_FIXED_STRING,
            data_length=col.data_length,
            safe_mapping=True,
        )

    @staticmethod
    def to_large_string(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle CLOB/NCLOB/LONG to GOE_TYPE_LARGE_STRING."""
        return _OracleRules.make_canonical(col, GOE_TYPE_LARGE_STRING)

    @staticmethod
    def to_variable_string(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle VARCHAR2/NVARCHAR2 to GOE_TYPE_VARIABLE_STRING."""
        return _OracleRules.make_canonical(col, GOE_TYPE_VARIABLE_STRING, data_length=col.data_length)

    @staticmethod
    def to_binary(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle RAW to GOE_TYPE_BINARY."""
        return _OracleRules.make_canonical(col, GOE_TYPE_BINARY, data_length=col.data_length)

    @staticmethod
    def to_large_binary(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle BLOB/LONG RAW to GOE_TYPE_LARGE_BINARY."""
        return _OracleRules.make_canonical(col, GOE_TYPE_LARGE_BINARY)

    @staticmethod
    def float_to_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle FLOAT to unsafe GOE_TYPE_DECIMAL."""
        return _OracleRules.make_canonical(col, GOE_TYPE_DECIMAL, data_precision=None, safe_mapping=False)

    @staticmethod
    def number_to_integral(canonical_type: str, *, log_unsafe_switch: bool = False) -> ColumnTransform:
        """Return a transform mapping Oracle NUMBER(p, 0) to a canonical integer type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            p, _ = _PrecisionGuards.normalized_precision_scale(col)
            if log_unsafe_switch and ctx.log:
                ctx.log(f"Switching unsafe INT8({p}) mapping to INT38", VVERBOSE)
            return _OracleRules.make_canonical(col, canonical_type, data_precision=p, data_scale=0)

        return transform

    @staticmethod
    def number_to_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map non-integral Oracle NUMBER to GOE_TYPE_DECIMAL."""
        p, s = _PrecisionGuards.normalized_precision_scale(col)
        safe_mapping = False if p is None and s is None else None
        return _OracleRules.make_canonical(
            col,
            GOE_TYPE_DECIMAL,
            data_precision=p,
            data_scale=s,
            safe_mapping=safe_mapping,
        )

    @staticmethod
    def to_float(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle BINARY_FLOAT to GOE_TYPE_FLOAT."""
        return _OracleRules.make_canonical(col, GOE_TYPE_FLOAT)

    @staticmethod
    def to_double(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle BINARY_DOUBLE to GOE_TYPE_DOUBLE."""
        return _OracleRules.make_canonical(col, GOE_TYPE_DOUBLE)

    @staticmethod
    def date_to_timestamp(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle DATE to GOE_TYPE_TIMESTAMP."""
        return _OracleRules.make_canonical(col, GOE_TYPE_TIMESTAMP)

    @staticmethod
    def to_timestamp(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle TIMESTAMP to GOE_TYPE_TIMESTAMP."""
        return _OracleRules.make_canonical(col, GOE_TYPE_TIMESTAMP, data_scale=col.data_scale)

    @staticmethod
    def to_timestamp_tz(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle TIMESTAMP WITH [LOCAL] TIME ZONE to GOE_TYPE_TIMESTAMP_TZ."""
        return _OracleRules.make_canonical(col, GOE_TYPE_TIMESTAMP_TZ, data_scale=col.data_scale)

    @staticmethod
    def to_interval_ds(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle INTERVAL DAY TO SECOND to GOE_TYPE_INTERVAL_DS."""
        return _OracleRules.make_canonical(
            col,
            GOE_TYPE_INTERVAL_DS,
            data_precision=col.data_precision,
            data_scale=col.data_scale,
        )

    @staticmethod
    def to_interval_ym(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle INTERVAL YEAR TO MONTH to GOE_TYPE_INTERVAL_YM."""
        return _OracleRules.make_canonical(
            col,
            GOE_TYPE_INTERVAL_YM,
            data_precision=col.data_precision,
            data_scale=col.data_scale,
        )

    @staticmethod
    def xmltype_to_large_string(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Oracle XMLTYPE to GOE_TYPE_LARGE_STRING."""
        return _OracleRules.make_canonical(col, GOE_TYPE_LARGE_STRING, data_scale=col.data_scale)

    @staticmethod
    def from_bounded_string(base_oracle_type: str, default_max: int, unicode_max: int) -> ColumnTransform:
        """Return a transform mapping canonical fixed/variable strings to CHAR/VARCHAR2 or CLOB/NCLOB."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            max_length = unicode_max if col.char_semantics == CANONICAL_CHAR_SEMANTICS_UNICODE else default_max
            if col.data_length or col.char_length:
                data_length = col.data_length
                char_length = col.char_length or data_length
            else:
                data_length = char_length = max_length
            effective_len = (
                char_length
                if col.char_semantics in (CANONICAL_CHAR_SEMANTICS_CHAR, CANONICAL_CHAR_SEMANTICS_UNICODE)
                else data_length
            )
            if (effective_len or 0) > max_length:
                return _OracleRules.make_oracle(col, _OracleRules.nchar_or_char(ORACLE_TYPE_CLOB, col.char_semantics))
            return _OracleRules.make_oracle(
                col,
                _OracleRules.nchar_or_char(base_oracle_type, col.char_semantics),
                data_length=data_length,
                char_length=char_length,
            )

        return transform

    @staticmethod
    def from_large_string(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_LARGE_STRING to Oracle CLOB/NCLOB."""
        return _OracleRules.make_oracle(col, _OracleRules.nchar_or_char(ORACLE_TYPE_CLOB, col.char_semantics))

    @staticmethod
    def from_binary(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_BINARY to Oracle RAW or BLOB."""
        data_length = col.data_length or 2000
        if data_length > 2000:
            return _OracleRules.make_oracle(col, ORACLE_TYPE_BLOB)
        return _OracleRules.make_oracle(col, ORACLE_TYPE_RAW, data_length=data_length)

    @staticmethod
    def from_large_binary(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_LARGE_BINARY to Oracle BLOB."""
        return _OracleRules.make_oracle(col, ORACLE_TYPE_BLOB)

    @staticmethod
    def from_integer(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map canonical integer types to Oracle NUMBER(p, 0)."""
        data_length = col.data_length or 22
        return _OracleRules.make_oracle(
            col,
            ORACLE_TYPE_NUMBER,
            data_precision=col.data_precision,
            data_scale=0,
            data_length=data_length,
        )

    @staticmethod
    def from_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DECIMAL to Oracle NUMBER."""
        data_length = col.data_length or 22
        data_precision, data_scale = col.data_precision, col.data_scale
        if col.data_precision and col.data_precision > 38:
            data_precision, data_scale = None, None
        return _OracleRules.make_oracle(
            col,
            ORACLE_TYPE_NUMBER,
            data_precision=data_precision,
            data_scale=data_scale,
            data_length=data_length,
        )

    @staticmethod
    def from_float(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_FLOAT to Oracle BINARY_FLOAT."""
        return _OracleRules.make_oracle(col, ORACLE_TYPE_BINARY_FLOAT, data_length=4)

    @staticmethod
    def from_double(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DOUBLE to Oracle BINARY_DOUBLE."""
        return _OracleRules.make_oracle(col, ORACLE_TYPE_BINARY_DOUBLE, data_length=8)

    @staticmethod
    def from_date(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DATE to Oracle DATE."""
        return _OracleRules.make_oracle(col, ORACLE_TYPE_DATE, data_length=7)

    @staticmethod
    def from_time(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_TIME to Oracle VARCHAR2(18)."""
        return _OracleRules.make_oracle(col, ORACLE_TYPE_VARCHAR2, data_length=18)

    @staticmethod
    def from_timestamp(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_TIMESTAMP to Oracle DATE (scale 0) or TIMESTAMP."""
        data_scale = col.data_scale if col.data_scale is not None else ctx.limits.max_datetime_scale
        if data_scale == 0:
            return _OracleRules.make_oracle(col, ORACLE_TYPE_DATE, data_length=7)
        return _OracleRules.make_oracle(col, ORACLE_TYPE_TIMESTAMP, data_scale=data_scale, data_length=11)

    @staticmethod
    def from_timestamp_tz(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_TIMESTAMP_TZ to Oracle TIMESTAMP WITH TIME ZONE."""
        data_scale = col.data_scale if col.data_scale is not None else ctx.limits.max_datetime_scale
        return _OracleRules.make_oracle(col, ORACLE_TYPE_TIMESTAMP_TZ, data_scale=data_scale, data_length=13)

    @staticmethod
    def from_interval_ds(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_INTERVAL_DS to Oracle INTERVAL DAY TO SECOND."""
        return _OracleRules.make_oracle(
            col,
            ORACLE_TYPE_INTERVAL_DS,
            data_precision=col.data_precision,
            data_scale=col.data_scale,
        )

    @staticmethod
    def from_interval_ym(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_INTERVAL_YM to Oracle INTERVAL YEAR TO MONTH."""
        return _OracleRules.make_oracle(
            col,
            ORACLE_TYPE_INTERVAL_YM,
            data_precision=col.data_precision,
            data_scale=col.data_scale,
        )


class _MssqlRules:
    """MSSQL to-canonical transform helpers."""

    @staticmethod
    def make_canonical(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a canonical ColumnSpec from an MSSQL ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.CANONICAL,
            col.name,
            data_type,
            data_length=data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            partition_info=None,
        )

    @staticmethod
    def simple(canonical_type: str, *, with_length: bool = False, safe_mapping: bool | None = None) -> ColumnTransform:
        """Return a transform mapping an MSSQL type to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _MssqlRules.make_canonical(
                col,
                canonical_type,
                data_length=col.data_length if with_length else None,
                safe_mapping=safe_mapping,
            )

        return transform

    @staticmethod
    def decimal_to_integral(canonical_type: str) -> ColumnTransform:
        """Return a transform mapping MSSQL scale-0 decimal/numeric/money to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            p, _ = _PrecisionGuards.normalized_precision_scale(col)
            return _MssqlRules.make_canonical(col, canonical_type, data_precision=p, data_scale=0)

        return transform

    @staticmethod
    def decimal_to_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map non-integral MSSQL decimal/numeric/money to GOE_TYPE_DECIMAL."""
        p, s = _PrecisionGuards.normalized_precision_scale(col)
        safe_mapping = False if p is None and s is None else None
        return _MssqlRules.make_canonical(
            col,
            GOE_TYPE_DECIMAL,
            data_precision=p,
            data_scale=s,
            safe_mapping=safe_mapping,
        )


class _BigQueryRules:
    """BigQuery to-canonical and from-canonical transform helpers."""

    @staticmethod
    def make_canonical(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a canonical ColumnSpec from a BigQuery ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.CANONICAL,
            col.name,
            data_type,
            data_length=data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            char_length=data_length,
            char_semantics=CANONICAL_CHAR_SEMANTICS_CHAR,
        )

    @staticmethod
    def make_bigquery(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        char_length: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a BigQuery ColumnSpec from a canonical ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.BIGQUERY,
            col.name,
            data_type,
            data_length=data_length,
            char_length=char_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
        )

    @staticmethod
    def to_simple(canonical_type: str, *, with_length: bool = False, scale_zero: bool = False) -> ColumnTransform:
        """Return a transform mapping a BigQuery type to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _BigQueryRules.make_canonical(
                col,
                canonical_type,
                data_length=col.data_length if with_length else None,
                data_scale=0 if scale_zero else None,
            )

        return transform

    @staticmethod
    def numeric_to_canonical(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map BigQuery NUMERIC to GOE_TYPE_DECIMAL(38, 9)."""
        p = col.data_precision if col.data_precision is not None else 38
        s = col.data_scale if col.data_scale is not None else 9
        return _BigQueryRules.make_canonical(col, GOE_TYPE_DECIMAL, data_precision=p, data_scale=s)

    @staticmethod
    def bignumeric_to_canonical(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map BigQuery BIGNUMERIC to GOE_TYPE_DECIMAL(max_precision, max_scale)."""
        p = col.data_precision if col.data_precision is not None else ctx.limits.max_decimal_precision
        s = col.data_scale if col.data_scale is not None else ctx.limits.max_decimal_scale
        return _BigQueryRules.make_canonical(col, GOE_TYPE_DECIMAL, data_precision=p, data_scale=s)

    @staticmethod
    def datetime_to_canonical(canonical_type: str) -> ColumnTransform:
        """Return a transform mapping BigQuery DATETIME/TIMESTAMP with max_datetime_scale."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _BigQueryRules.make_canonical(col, canonical_type, data_scale=ctx.limits.max_datetime_scale)

        return transform

    @staticmethod
    def from_simple(bq_type: str, *, safe_mapping: bool | None = None) -> ColumnTransform:
        """Return a transform mapping a canonical type to bq_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _BigQueryRules.make_bigquery(col, bq_type, safe_mapping=safe_mapping)

        return transform

    @staticmethod
    def from_string(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map canonical string types to BigQuery STRING."""
        return _BigQueryRules.make_bigquery(
            col,
            BIGQUERY_TYPE_STRING,
            char_length=col.char_length or col.data_length,
            safe_mapping=True,
        )

    @staticmethod
    def from_binary(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map canonical binary types to BigQuery BYTES."""
        return _BigQueryRules.make_bigquery(
            col,
            BIGQUERY_TYPE_BYTES,
            data_length=col.data_length,
            safe_mapping=True,
        )

    @staticmethod
    def from_int38_numeric(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_INTEGER_38 with precision <= 29 to BigQuery NUMERIC(p, 0)."""
        return _BigQueryRules.make_bigquery(
            col,
            BIGQUERY_TYPE_NUMERIC,
            data_precision=col.data_precision,
            data_scale=0,
            safe_mapping=True,
        )

    @staticmethod
    def from_int38_bignumeric(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_INTEGER_38 with precision > 29 or None to BigQuery BIGNUMERIC(38, 0)."""
        return _BigQueryRules.make_bigquery(
            col,
            BIGQUERY_TYPE_BIGNUMERIC,
            data_precision=38,
            data_scale=0,
            safe_mapping=True,
        )

    @staticmethod
    def from_decimal_numeric(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DECIMAL fitting NUMERIC bounds to NUMERIC or unsafe BIGNUMERIC."""
        new_data_type = BIGQUERY_TYPE_NUMERIC
        new_precision = col.data_precision
        new_scale = col.data_scale
        if not col.safe_mapping:
            if ctx.log:
                ctx.log(f"Switching unsafe NUMERIC mapping to BIGNUMERIC: {col.name}", VVERBOSE)
            new_data_type = BIGQUERY_TYPE_BIGNUMERIC
            new_precision = None
            new_scale = None
        return _BigQueryRules.make_bigquery(
            col,
            new_data_type,
            data_precision=new_precision,
            data_scale=new_scale,
            safe_mapping=True,
        )

    @staticmethod
    def from_decimal_bignumeric(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DECIMAL exceeding NUMERIC bounds to BigQuery BIGNUMERIC."""
        new_precision = col.data_precision
        new_scale = col.data_scale
        if not col.safe_mapping:
            if ctx.log:
                ctx.log(
                    f"Removing precision/scale decorators for unsafe BIGNUMERIC mapping: {col.name}",
                    VVERBOSE,
                )
            new_precision = None
            new_scale = None
        return _BigQueryRules.make_bigquery(
            col,
            BIGQUERY_TYPE_BIGNUMERIC,
            data_precision=new_precision,
            data_scale=new_scale,
            safe_mapping=False,
        )

    @staticmethod
    def from_scaled_temporal(bq_type: str) -> ColumnTransform:
        """Return a transform mapping TIME/TIMESTAMP with scale-dependent safe_mapping."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            max_scale = ctx.limits.max_datetime_scale
            safe_mapping = bool(col.data_scale is None or (max_scale is not None and col.data_scale <= max_scale))
            return _BigQueryRules.make_bigquery(col, bq_type, safe_mapping=safe_mapping)

        return transform


class _SnowflakeRules:
    """Snowflake to-canonical and from-canonical transform helpers."""

    @staticmethod
    def make_canonical(
        col: ColumnSpec,
        data_type: str,
        *,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a canonical ColumnSpec from a Snowflake ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.CANONICAL,
            col.name,
            data_type,
            data_length=col.data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            char_length=col.char_length,
            char_semantics=CANONICAL_CHAR_SEMANTICS_CHAR,
        )

    @staticmethod
    def make_snowflake(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        char_length: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a Snowflake ColumnSpec from a canonical ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.SNOWFLAKE,
            col.name,
            data_type,
            data_length=data_length,
            char_length=char_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
        )

    @staticmethod
    def to_simple(canonical_type: str) -> ColumnTransform:
        """Return a transform mapping a Snowflake type to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SnowflakeRules.make_canonical(col, canonical_type)

        return transform

    @staticmethod
    def number_to_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map non-integral Snowflake NUMBER to GOE_TYPE_DECIMAL."""
        return _SnowflakeRules.make_canonical(
            col,
            GOE_TYPE_DECIMAL,
            data_precision=col.data_precision,
            data_scale=col.data_scale,
        )

    @staticmethod
    def timestamp_to_canonical(canonical_type: str) -> ColumnTransform:
        """Return a transform mapping Snowflake TIMESTAMP_NTZ/TIMESTAMP_TZ with max_datetime_scale."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SnowflakeRules.make_canonical(col, canonical_type, data_scale=ctx.limits.max_datetime_scale)

        return transform

    @staticmethod
    def from_simple(
        sf_type: str,
        *,
        data_precision: int | None = None,
        data_scale: int | None = None,
        with_length: bool = False,
        with_scale: bool = False,
        safe_mapping: bool | None = None,
    ) -> ColumnTransform:
        """Return a transform mapping a canonical type to sf_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SnowflakeRules.make_snowflake(
                col,
                sf_type,
                data_length=col.data_length if with_length else None,
                data_precision=data_precision,
                data_scale=col.data_scale if with_scale else data_scale,
                safe_mapping=safe_mapping,
            )

        return transform

    @staticmethod
    def from_string(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map canonical string types to Snowflake TEXT."""
        return _SnowflakeRules.make_snowflake(
            col,
            SNOWFLAKE_TYPE_TEXT,
            char_length=col.char_length or col.data_length,
            safe_mapping=True,
        )

    @staticmethod
    def from_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DECIMAL to Snowflake NUMBER."""
        if col.data_precision is None and col.data_scale is None:
            return _SnowflakeRules.default_numeric(col.name, ctx)
        data_precision = col.data_precision or ctx.limits.max_decimal_precision
        return _SnowflakeRules.make_snowflake(
            col,
            SNOWFLAKE_TYPE_NUMBER,
            data_precision=data_precision,
            data_scale=col.data_scale,
            safe_mapping=True,
        )

    @staticmethod
    def default_numeric(name: str, ctx: MappingContext, data_scale: int | None = 18) -> ColumnSpec:
        """Build the default Snowflake numeric ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.SNOWFLAKE,
            name,
            SNOWFLAKE_TYPE_NUMBER,
            data_precision=ctx.limits.max_decimal_precision,
            data_scale=18 if data_scale is None else data_scale,
            nullable=True,
            safe_mapping=False,
        )


class _SynapseRules:
    """Synapse to-canonical and from-canonical transform helpers."""

    @staticmethod
    def make_canonical(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
        char_length: int | None = None,
        char_semantics: str | None = None,
    ) -> ColumnSpec:
        """Build a canonical ColumnSpec from a Synapse ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.CANONICAL,
            col.name,
            data_type,
            data_length=data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            char_length=char_length,
            partition_info=None,
            char_semantics=char_semantics,
        )

    @staticmethod
    def make_synapse(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        char_length: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a Synapse ColumnSpec from a canonical ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.SYNAPSE,
            col.name,
            data_type,
            data_length=data_length,
            char_length=char_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            char_semantics=col.char_semantics,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
        )

    @staticmethod
    def nchar_or_char(data_type: str, char_semantics: str | None) -> str:
        """Select nchar/nvarchar when char_semantics is UNICODE."""
        if char_semantics == CANONICAL_CHAR_SEMANTICS_UNICODE:
            if data_type == SYNAPSE_TYPE_CHAR:
                return SYNAPSE_TYPE_NCHAR
            if data_type == SYNAPSE_TYPE_VARCHAR:
                return SYNAPSE_TYPE_NVARCHAR
        return data_type

    @staticmethod
    def to_string(
        canonical_type: str,
        char_semantics: str,
        *,
        safe_mapping: bool | None = None,
    ) -> ColumnTransform:
        """Return a transform mapping Synapse char/nchar/varchar/nvarchar to canonical string."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SynapseRules.make_canonical(
                col,
                canonical_type,
                data_length=col.data_length,
                char_length=col.char_length,
                char_semantics=char_semantics,
                safe_mapping=safe_mapping,
            )

        return transform

    @staticmethod
    def to_simple(
        canonical_type: str,
        *,
        with_length: bool = False,
        fixed_length: int | None = None,
        with_scale: bool = False,
        fixed_scale: int | None = None,
    ) -> ColumnTransform:
        """Return a transform mapping a Synapse type to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SynapseRules.make_canonical(
                col,
                canonical_type,
                data_length=col.data_length if with_length else fixed_length,
                data_scale=col.data_scale if with_scale else fixed_scale,
            )

        return transform

    @staticmethod
    def to_money(default_precision: int, default_scale: int) -> ColumnTransform:
        """Return a transform mapping Synapse money/smallmoney to GOE_TYPE_DECIMAL."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SynapseRules.make_canonical(
                col,
                GOE_TYPE_DECIMAL,
                data_precision=col.data_precision or default_precision,
                data_scale=col.data_scale or default_scale,
            )

        return transform

    @staticmethod
    def decimal_to_integral(canonical_type: str) -> ColumnTransform:
        """Return a transform mapping Synapse scale-0 decimal/numeric to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            p, _ = _PrecisionGuards.normalized_precision_scale(col)
            return _SynapseRules.make_canonical(col, canonical_type, data_precision=p, data_scale=0)

        return transform

    @staticmethod
    def decimal_to_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map non-integral Synapse decimal/numeric to GOE_TYPE_DECIMAL."""
        p, s = _PrecisionGuards.normalized_precision_scale(col)
        safe_mapping = False if p is None and s is None else None
        return _SynapseRules.make_canonical(
            col,
            GOE_TYPE_DECIMAL,
            data_precision=p,
            data_scale=s,
            safe_mapping=safe_mapping,
        )

    @staticmethod
    def from_string(base_synapse_type: str, *, keep_lengths: bool, safe_mapping: bool | None = None) -> ColumnTransform:
        """Return a transform mapping canonical strings to Synapse char/nchar/varchar/nvarchar."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SynapseRules.make_synapse(
                col,
                _SynapseRules.nchar_or_char(base_synapse_type, col.char_semantics),
                data_length=col.data_length if keep_lengths else None,
                char_length=col.char_length if keep_lengths else None,
                safe_mapping=safe_mapping,
            )

        return transform

    @staticmethod
    def from_simple(
        syn_type: str,
        *,
        with_length: bool = False,
        fixed_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnTransform:
        """Return a transform mapping a canonical type to syn_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _SynapseRules.make_synapse(
                col,
                syn_type,
                data_length=col.data_length if with_length else fixed_length,
                data_precision=data_precision,
                data_scale=data_scale,
                safe_mapping=safe_mapping,
            )

        return transform

    @staticmethod
    def from_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DECIMAL to Synapse numeric."""
        if col.data_precision is None and col.data_scale is None:
            return _SynapseRules.default_numeric(col.name, ctx)
        data_precision = col.data_precision or ctx.limits.max_decimal_precision
        return _SynapseRules.make_synapse(
            col,
            SYNAPSE_TYPE_NUMERIC,
            data_precision=data_precision,
            data_scale=col.data_scale,
            safe_mapping=True,
        )

    @staticmethod
    def from_scaled_temporal(syn_type: str) -> ColumnTransform:
        """Return a transform clamping canonical temporal scale to max_datetime_scale."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            max_scale = ctx.limits.max_datetime_scale
            assert max_scale is not None
            safe_mapping = bool(col.data_scale is None or col.data_scale <= max_scale)
            data_scale = col.data_scale if (col.data_scale or 0) < max_scale else max_scale
            return _SynapseRules.make_synapse(
                col,
                syn_type,
                data_scale=data_scale,
                safe_mapping=safe_mapping,
            )

        return transform

    @staticmethod
    def default_numeric(name: str, ctx: MappingContext, data_scale: int | None = 18) -> ColumnSpec:
        """Build the default Synapse numeric ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.SYNAPSE,
            name,
            SYNAPSE_TYPE_NUMERIC,
            data_precision=ctx.limits.max_decimal_precision,
            data_scale=18 if data_scale is None else data_scale,
            nullable=True,
            safe_mapping=False,
        )


class _HadoopRules:
    """Hadoop (Hive and Impala) to-canonical and from-canonical transform helpers."""

    @staticmethod
    def make_canonical(
        col: ColumnSpec,
        data_type: str,
        *,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a canonical ColumnSpec from a Hadoop ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.CANONICAL,
            col.name,
            data_type,
            data_length=col.data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            char_length=col.char_length,
        )

    @staticmethod
    def make_hadoop(
        col: ColumnSpec,
        data_type: str,
        *,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        safe_mapping: bool | None = None,
    ) -> ColumnSpec:
        """Build a Hadoop ColumnSpec from a canonical ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.HADOOP,
            col.name,
            data_type,
            data_length=data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
        )

    @staticmethod
    def to_simple(canonical_type: str) -> ColumnTransform:
        """Return a transform mapping a Hadoop type to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _HadoopRules.make_canonical(col, canonical_type)

        return transform

    @staticmethod
    def decimal_scale_zero_guard(low: int, high: int) -> ColumnGuard:
        """Return a guard for Hadoop DECIMAL(p, 0) with p in [low, high]."""

        def guard(col: ColumnSpec, ctx: MappingContext) -> bool:
            if col.data_scale != 0:
                return False
            return low <= (col.data_precision or 0) <= high

        return guard

    @staticmethod
    def decimal_scale_zero_overflow(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Hadoop DECIMAL(p, 0) outside [1, 38] to GOE_TYPE_INTEGER_38(p, 0)."""
        return _HadoopRules.make_canonical(
            col,
            GOE_TYPE_INTEGER_38,
            data_precision=col.data_precision,
            data_scale=0,
        )

    @staticmethod
    def decimal_to_canonical(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map non-scale-0 Hadoop DECIMAL to GOE_TYPE_DECIMAL."""
        return _HadoopRules.make_canonical(
            col,
            GOE_TYPE_DECIMAL,
            data_precision=col.data_precision,
            data_scale=col.data_scale,
        )

    @staticmethod
    def timestamp_to_canonical(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map Hadoop TIMESTAMP to GOE_TYPE_TIMESTAMP with max_datetime_scale fallback."""
        data_scale = col.data_scale if col.data_scale is not None else ctx.limits.max_datetime_scale
        return _HadoopRules.make_canonical(col, GOE_TYPE_TIMESTAMP, data_scale=data_scale)

    @staticmethod
    def from_simple(hadoop_type: str, *, safe_mapping: bool | None = None) -> ColumnTransform:
        """Return a transform mapping a canonical type to hadoop_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _HadoopRules.make_hadoop(col, hadoop_type, safe_mapping=safe_mapping)

        return transform

    @staticmethod
    def from_int38(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_INTEGER_38 to Hadoop DECIMAL(max_decimal_precision, 0)."""
        return _HadoopRules.make_hadoop(
            col,
            HADOOP_TYPE_DECIMAL,
            data_precision=ctx.limits.max_decimal_precision,
            data_scale=0,
            safe_mapping=True,
        )

    @staticmethod
    def from_decimal(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map GOE_TYPE_DECIMAL to Hadoop DECIMAL with UDF alignment and padding."""
        if col.data_precision is None and col.data_scale is None:
            return _HadoopRules.default_numeric(col.name, ctx)
        max_prec = ctx.limits.max_decimal_precision
        max_scale = ctx.limits.max_decimal_scale
        assert max_prec is not None and max_scale is not None

        new_precision = col.data_precision
        new_scale = col.data_scale
        if new_precision or new_scale:
            private_precision = new_precision or max_prec
            if private_precision < max_prec:
                raw_scale: Any = new_scale
                if new_precision:
                    new_precision += raw_scale % 2
                new_scale = raw_scale + (raw_scale % 2)

        padding = ctx.decimal_padding_digits
        if padding:
            if new_precision is None or new_scale is None:
                if ctx.log:
                    ctx.log(
                        f"No padding applied to {col.name} for precision/scale: {new_precision}/{new_scale}",
                        VVERBOSE,
                    )
            else:
                orig_p, orig_s = new_precision, new_scale
                if new_precision <= max_prec - padding:
                    new_scale += min(padding, max_prec - new_precision)
                    new_precision += min(padding, max_prec - new_precision)
                if new_precision < max_prec:
                    new_precision += min(padding, max_prec - new_precision)
                if (new_precision != orig_p or new_scale != orig_s) and ctx.log:
                    ctx.log(
                        f"Padded precision/scale for {col.name} in line with "
                        f"DECIMAL_PADDING_DIGITS={padding}: {orig_p},{orig_s} -> {new_precision},{new_scale}",
                        VVERBOSE,
                    )

        aligned_p = new_precision or max_prec
        new_precision = max(aligned_p, 18) if aligned_p < 19 else max(aligned_p, max_prec)

        if (
            (new_scale is not None and (new_scale < 0 or new_scale > max_scale))
            or (new_precision and new_precision > max_prec)
            or (new_precision and new_scale and new_scale > new_precision)
        ):
            raise ColumnSpecError(
                f"Unsupported precision/scale for {col.data_type} column {col.name}: {new_precision}/{new_scale}"
            )
        if (new_precision != col.data_precision or new_scale != col.data_scale) and ctx.log:
            ctx.log(
                f"UDF aligned/padded precision/scale for {col.name}: "
                f"{col.data_precision},{col.data_scale} -> {new_precision},{new_scale}",
                VERBOSE,
            )
        return _HadoopRules.make_hadoop(
            col,
            HADOOP_TYPE_DECIMAL,
            data_precision=new_precision,
            data_scale=new_scale,
            safe_mapping=False,
        )

    @staticmethod
    def default_numeric(name: str, ctx: MappingContext, data_scale: int | None = 18) -> ColumnSpec:
        """Build the default Hadoop numeric ColumnSpec."""
        return ColumnSpec(
            ColumnDialect.HADOOP,
            name,
            HADOOP_TYPE_DECIMAL,
            data_precision=ctx.limits.max_decimal_precision,
            data_scale=18 if data_scale is None else data_scale,
            nullable=True,
            safe_mapping=False,
        )


class _StagingRules:
    """Parquet and Avro staging to-canonical and from-canonical transform helpers."""

    @staticmethod
    def make_canonical(col: ColumnSpec, ctx: MappingContext, data_type: str) -> ColumnSpec:
        """Build a canonical ColumnSpec from a staging ColumnSpec."""
        name = (col.staging_file_column_name or col.name) if ctx.use_staging_file_name else col.name
        return ColumnSpec(
            ColumnDialect.CANONICAL,
            name,
            data_type,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, True),
            char_semantics=col.char_semantics,
        )

    @staticmethod
    def make_staging(
        dialect: ColumnDialect,
        col: ColumnSpec,
        data_type: str,
        *,
        safe_mapping: bool,
        keep_char_semantics: bool = True,
    ) -> ColumnSpec:
        """Build a staging ColumnSpec from a canonical ColumnSpec."""
        return ColumnSpec(
            dialect,
            col.name,
            data_type,
            nullable=col.nullable,
            data_default=col.data_default,
            safe_mapping=is_safe_mapping(col.safe_mapping, safe_mapping),
            char_semantics=col.char_semantics if keep_char_semantics else None,
        )

    @staticmethod
    def to_simple(canonical_type: str) -> ColumnTransform:
        """Return a transform mapping a staging type to canonical_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _StagingRules.make_canonical(col, ctx, canonical_type)

        return transform

    @staticmethod
    def binary_to_canonical(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
        """Map staging binary/bytes to GOE_TYPE_VARIABLE_STRING (base64) or GOE_TYPE_BINARY."""
        target_type = GOE_TYPE_VARIABLE_STRING if ctx.binary_as_base64 else GOE_TYPE_BINARY
        return _StagingRules.make_canonical(col, ctx, target_type)

    @staticmethod
    def from_simple(
        dialect: ColumnDialect,
        staging_type: str,
        *,
        safe_mapping: bool,
        keep_char_semantics: bool = True,
    ) -> ColumnTransform:
        """Return a transform mapping a canonical type to staging_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            return _StagingRules.make_staging(
                dialect,
                col,
                staging_type,
                safe_mapping=safe_mapping,
                keep_char_semantics=keep_char_semantics,
            )

        return transform

    @staticmethod
    def from_binary(dialect: ColumnDialect, binary_type: str, string_type: str) -> ColumnTransform:
        """Return a transform mapping canonical binary to string (base64) or binary_type."""

        def transform(col: ColumnSpec, ctx: MappingContext) -> ColumnSpec:
            target_type = string_type if ctx.binary_as_base64 else binary_type
            return _StagingRules.make_staging(dialect, col, target_type, safe_mapping=True)

        return transform


TO_CANONICAL_RULES: dict[ColumnDialect, tuple[MappingRule, ...]] = {
    ColumnDialect.ORACLE: (
        MappingRule(frozenset({ORACLE_TYPE_CHAR, ORACLE_TYPE_NCHAR}), _OracleRules.to_fixed_string),
        MappingRule(
            frozenset({ORACLE_TYPE_CLOB, ORACLE_TYPE_NCLOB, ORACLE_TYPE_LONG}),
            _OracleRules.to_large_string,
        ),
        MappingRule(frozenset({ORACLE_TYPE_VARCHAR2, ORACLE_TYPE_NVARCHAR2}), _OracleRules.to_variable_string),
        MappingRule(frozenset({ORACLE_TYPE_RAW}), _OracleRules.to_binary),
        MappingRule(frozenset({ORACLE_TYPE_BLOB, ORACLE_TYPE_LONG_RAW}), _OracleRules.to_large_binary),
        MappingRule(frozenset({ORACLE_TYPE_FLOAT}), _OracleRules.float_to_decimal),
        MappingRule(
            frozenset({ORACLE_TYPE_NUMBER}),
            _OracleRules.number_to_integral(GOE_TYPE_INTEGER_1),
            guard=_PrecisionGuards.integral_range(1, 2),
        ),
        MappingRule(
            frozenset({ORACLE_TYPE_NUMBER}),
            _OracleRules.number_to_integral(GOE_TYPE_INTEGER_2),
            guard=_PrecisionGuards.integral_range(3, 4),
        ),
        MappingRule(
            frozenset({ORACLE_TYPE_NUMBER}),
            _OracleRules.number_to_integral(GOE_TYPE_INTEGER_4),
            guard=_PrecisionGuards.integral_range(5, 9),
        ),
        MappingRule(
            frozenset({ORACLE_TYPE_NUMBER}),
            _OracleRules.number_to_integral(GOE_TYPE_INTEGER_38, log_unsafe_switch=True),
            guard=_PrecisionGuards.integral_range(17, 18, require_unsafe=True),
        ),
        MappingRule(
            frozenset({ORACLE_TYPE_NUMBER}),
            _OracleRules.number_to_integral(GOE_TYPE_INTEGER_8),
            guard=_PrecisionGuards.integral_range(10, 18),
        ),
        MappingRule(
            frozenset({ORACLE_TYPE_NUMBER}),
            _OracleRules.number_to_integral(GOE_TYPE_INTEGER_38),
            guard=_PrecisionGuards.integral_range(19, 38),
        ),
        MappingRule(frozenset({ORACLE_TYPE_NUMBER}), _OracleRules.number_to_decimal),
        MappingRule(frozenset({ORACLE_TYPE_BINARY_FLOAT}), _OracleRules.to_float),
        MappingRule(frozenset({ORACLE_TYPE_BINARY_DOUBLE}), _OracleRules.to_double),
        MappingRule(frozenset({ORACLE_TYPE_DATE}), _OracleRules.date_to_timestamp),
        MappingRule(frozenset({ORACLE_TYPE_TIMESTAMP}), _OracleRules.to_timestamp),
        MappingRule(
            frozenset({ORACLE_TYPE_TIMESTAMP_TZ, ORACLE_TYPE_TIMESTAMP_LOCAL_TZ}),
            _OracleRules.to_timestamp_tz,
        ),
        MappingRule(frozenset({ORACLE_TYPE_INTERVAL_DS}), _OracleRules.to_interval_ds),
        MappingRule(frozenset({ORACLE_TYPE_INTERVAL_YM}), _OracleRules.to_interval_ym),
        MappingRule(frozenset({ORACLE_TYPE_XMLTYPE}), _OracleRules.xmltype_to_large_string),
    ),
    ColumnDialect.MSSQL: (
        MappingRule(frozenset({MSSQL_TYPE_BIT}), _MssqlRules.simple(GOE_TYPE_BOOLEAN)),
        MappingRule(
            frozenset({MSSQL_TYPE_CHAR, MSSQL_TYPE_NCHAR}),
            _MssqlRules.simple(GOE_TYPE_FIXED_STRING, with_length=True, safe_mapping=True),
        ),
        MappingRule(frozenset({MSSQL_TYPE_TEXT, MSSQL_TYPE_NTEXT}), _MssqlRules.simple(GOE_TYPE_LARGE_STRING)),
        MappingRule(
            frozenset({MSSQL_TYPE_VARCHAR, MSSQL_TYPE_NVARCHAR, MSSQL_TYPE_UNIQUEIDENTIFIER}),
            _MssqlRules.simple(GOE_TYPE_VARIABLE_STRING, with_length=True),
        ),
        MappingRule(
            frozenset({MSSQL_TYPE_BINARY, MSSQL_TYPE_VARBINARY, MSSQL_TYPE_IMAGE}),
            _MssqlRules.simple(GOE_TYPE_BINARY, with_length=True),
        ),
        MappingRule(frozenset({MSSQL_TYPE_TINYINT, MSSQL_TYPE_SMALLINT}), _MssqlRules.simple(GOE_TYPE_INTEGER_2)),
        MappingRule(frozenset({MSSQL_TYPE_INT}), _MssqlRules.simple(GOE_TYPE_INTEGER_4)),
        MappingRule(frozenset({MSSQL_TYPE_BIGINT}), _MssqlRules.simple(GOE_TYPE_INTEGER_8)),
        MappingRule(frozenset({MSSQL_TYPE_FLOAT}), _MssqlRules.simple(GOE_TYPE_DOUBLE)),
        MappingRule(frozenset({MSSQL_TYPE_REAL}), _MssqlRules.simple(GOE_TYPE_FLOAT)),
        MappingRule(
            frozenset({MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC, MSSQL_TYPE_MONEY, MSSQL_TYPE_SMALLMONEY}),
            _MssqlRules.decimal_to_integral(GOE_TYPE_INTEGER_1),
            guard=_PrecisionGuards.integral_range(1, 2),
        ),
        MappingRule(
            frozenset({MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC, MSSQL_TYPE_MONEY, MSSQL_TYPE_SMALLMONEY}),
            _MssqlRules.decimal_to_integral(GOE_TYPE_INTEGER_2),
            guard=_PrecisionGuards.integral_range(3, 4),
        ),
        MappingRule(
            frozenset({MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC, MSSQL_TYPE_MONEY, MSSQL_TYPE_SMALLMONEY}),
            _MssqlRules.decimal_to_integral(GOE_TYPE_INTEGER_4),
            guard=_PrecisionGuards.integral_range(5, 9),
        ),
        MappingRule(
            frozenset({MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC, MSSQL_TYPE_MONEY, MSSQL_TYPE_SMALLMONEY}),
            _MssqlRules.decimal_to_integral(GOE_TYPE_INTEGER_8),
            guard=_PrecisionGuards.integral_range(10, 18),
        ),
        MappingRule(
            frozenset({MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC, MSSQL_TYPE_MONEY, MSSQL_TYPE_SMALLMONEY}),
            _MssqlRules.decimal_to_integral(GOE_TYPE_INTEGER_38),
            guard=_PrecisionGuards.integral_range(19, 38),
        ),
        MappingRule(
            frozenset({MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC, MSSQL_TYPE_MONEY, MSSQL_TYPE_SMALLMONEY}),
            _MssqlRules.decimal_to_integral(GOE_TYPE_DECIMAL),
            guard=_PrecisionGuards.scale_zero_with_precision,
        ),
        MappingRule(
            frozenset({MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC, MSSQL_TYPE_MONEY, MSSQL_TYPE_SMALLMONEY}),
            _MssqlRules.decimal_to_decimal,
        ),
        MappingRule(frozenset({MSSQL_TYPE_DATE}), _MssqlRules.simple(GOE_TYPE_DATE)),
        MappingRule(frozenset({MSSQL_TYPE_TIME}), _MssqlRules.simple(GOE_TYPE_TIME)),
        MappingRule(
            frozenset({MSSQL_TYPE_SMALLDATETIME, MSSQL_TYPE_DATETIME, MSSQL_TYPE_DATETIME2}),
            _MssqlRules.simple(GOE_TYPE_TIMESTAMP),
        ),
        MappingRule(frozenset({MSSQL_TYPE_DATETIMEOFFSET}), _MssqlRules.simple(GOE_TYPE_TIMESTAMP_TZ)),
    ),
    ColumnDialect.BIGQUERY: (
        MappingRule(frozenset({BIGQUERY_TYPE_BOOLEAN}), _BigQueryRules.to_simple(GOE_TYPE_BOOLEAN)),
        MappingRule(
            frozenset({BIGQUERY_TYPE_STRING}),
            _BigQueryRules.to_simple(GOE_TYPE_VARIABLE_STRING, with_length=True),
        ),
        MappingRule(frozenset({BIGQUERY_TYPE_BYTES}), _BigQueryRules.to_simple(GOE_TYPE_BINARY)),
        MappingRule(frozenset({BIGQUERY_TYPE_INT64}), _BigQueryRules.to_simple(GOE_TYPE_INTEGER_8)),
        MappingRule(frozenset({BIGQUERY_TYPE_NUMERIC}), _BigQueryRules.numeric_to_canonical),
        MappingRule(frozenset({BIGQUERY_TYPE_BIGNUMERIC}), _BigQueryRules.bignumeric_to_canonical),
        MappingRule(frozenset({BIGQUERY_TYPE_FLOAT64}), _BigQueryRules.to_simple(GOE_TYPE_DOUBLE)),
        MappingRule(frozenset({BIGQUERY_TYPE_DATE}), _BigQueryRules.to_simple(GOE_TYPE_DATE, scale_zero=True)),
        MappingRule(frozenset({BIGQUERY_TYPE_DATETIME}), _BigQueryRules.datetime_to_canonical(GOE_TYPE_TIMESTAMP)),
        MappingRule(frozenset({BIGQUERY_TYPE_TIME}), _BigQueryRules.to_simple(GOE_TYPE_TIME)),
        MappingRule(frozenset({BIGQUERY_TYPE_TIMESTAMP}), _BigQueryRules.datetime_to_canonical(GOE_TYPE_TIMESTAMP_TZ)),
    ),
    ColumnDialect.SNOWFLAKE: (
        MappingRule(frozenset({SNOWFLAKE_TYPE_BOOLEAN}), _SnowflakeRules.to_simple(GOE_TYPE_BOOLEAN)),
        MappingRule(frozenset({SNOWFLAKE_TYPE_BINARY}), _SnowflakeRules.to_simple(GOE_TYPE_BINARY)),
        MappingRule(frozenset({SNOWFLAKE_TYPE_DATE}), _SnowflakeRules.to_simple(GOE_TYPE_DATE)),
        MappingRule(frozenset({SNOWFLAKE_TYPE_FLOAT}), _SnowflakeRules.to_simple(GOE_TYPE_DOUBLE)),
        MappingRule(frozenset({SNOWFLAKE_TYPE_INTEGER}), _SnowflakeRules.to_simple(GOE_TYPE_INTEGER_38)),
        MappingRule(
            frozenset({SNOWFLAKE_TYPE_NUMBER}),
            _SnowflakeRules.to_simple(GOE_TYPE_INTEGER_1),
            guard=_PrecisionGuards.raw_scale_zero_precision_range(1, 2),
        ),
        MappingRule(
            frozenset({SNOWFLAKE_TYPE_NUMBER}),
            _SnowflakeRules.to_simple(GOE_TYPE_INTEGER_2),
            guard=_PrecisionGuards.raw_scale_zero_precision_range(3, 4),
        ),
        MappingRule(
            frozenset({SNOWFLAKE_TYPE_NUMBER}),
            _SnowflakeRules.to_simple(GOE_TYPE_INTEGER_4),
            guard=_PrecisionGuards.raw_scale_zero_precision_range(5, 9),
        ),
        MappingRule(
            frozenset({SNOWFLAKE_TYPE_NUMBER}),
            _SnowflakeRules.to_simple(GOE_TYPE_INTEGER_8),
            guard=_PrecisionGuards.raw_scale_zero_precision_range(10, 18),
        ),
        MappingRule(
            frozenset({SNOWFLAKE_TYPE_NUMBER}),
            _SnowflakeRules.to_simple(GOE_TYPE_INTEGER_38),
            guard=_PrecisionGuards.raw_scale_zero,
        ),
        MappingRule(frozenset({SNOWFLAKE_TYPE_NUMBER}), _SnowflakeRules.number_to_decimal),
        MappingRule(frozenset({SNOWFLAKE_TYPE_TEXT}), _SnowflakeRules.to_simple(GOE_TYPE_VARIABLE_STRING)),
        MappingRule(frozenset({SNOWFLAKE_TYPE_TIME}), _SnowflakeRules.to_simple(GOE_TYPE_TIME)),
        MappingRule(
            frozenset({SNOWFLAKE_TYPE_TIMESTAMP_NTZ}),
            _SnowflakeRules.timestamp_to_canonical(GOE_TYPE_TIMESTAMP),
        ),
        MappingRule(
            frozenset({SNOWFLAKE_TYPE_TIMESTAMP_TZ}),
            _SnowflakeRules.timestamp_to_canonical(GOE_TYPE_TIMESTAMP_TZ),
        ),
    ),
    ColumnDialect.SYNAPSE: (
        MappingRule(
            frozenset({SYNAPSE_TYPE_CHAR}),
            _SynapseRules.to_string(GOE_TYPE_FIXED_STRING, CANONICAL_CHAR_SEMANTICS_BYTE, safe_mapping=True),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_NCHAR}),
            _SynapseRules.to_string(GOE_TYPE_FIXED_STRING, CANONICAL_CHAR_SEMANTICS_CHAR, safe_mapping=True),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_VARCHAR}),
            _SynapseRules.to_string(GOE_TYPE_VARIABLE_STRING, CANONICAL_CHAR_SEMANTICS_BYTE),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_NVARCHAR}),
            _SynapseRules.to_string(GOE_TYPE_VARIABLE_STRING, CANONICAL_CHAR_SEMANTICS_CHAR),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_BINARY, SYNAPSE_TYPE_VARBINARY}),
            _SynapseRules.to_simple(GOE_TYPE_BINARY, with_length=True),
        ),
        MappingRule(frozenset({SYNAPSE_TYPE_TINYINT}), _SynapseRules.to_simple(GOE_TYPE_INTEGER_1)),
        MappingRule(frozenset({SYNAPSE_TYPE_SMALLINT}), _SynapseRules.to_simple(GOE_TYPE_INTEGER_2)),
        MappingRule(frozenset({SYNAPSE_TYPE_INT}), _SynapseRules.to_simple(GOE_TYPE_INTEGER_4)),
        MappingRule(frozenset({SYNAPSE_TYPE_BIGINT}), _SynapseRules.to_simple(GOE_TYPE_INTEGER_8)),
        MappingRule(frozenset({SYNAPSE_TYPE_FLOAT}), _SynapseRules.to_simple(GOE_TYPE_DOUBLE)),
        MappingRule(frozenset({SYNAPSE_TYPE_REAL}), _SynapseRules.to_simple(GOE_TYPE_FLOAT)),
        MappingRule(frozenset({SYNAPSE_TYPE_MONEY}), _SynapseRules.to_money(19, 4)),
        MappingRule(frozenset({SYNAPSE_TYPE_SMALLMONEY}), _SynapseRules.to_money(10, 4)),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC}),
            _SynapseRules.decimal_to_integral(GOE_TYPE_INTEGER_1),
            guard=_PrecisionGuards.integral_range(1, 2),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC}),
            _SynapseRules.decimal_to_integral(GOE_TYPE_INTEGER_2),
            guard=_PrecisionGuards.integral_range(3, 4),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC}),
            _SynapseRules.decimal_to_integral(GOE_TYPE_INTEGER_4),
            guard=_PrecisionGuards.integral_range(5, 9),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC}),
            _SynapseRules.decimal_to_integral(GOE_TYPE_INTEGER_8),
            guard=_PrecisionGuards.integral_range(10, 18),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC}),
            _SynapseRules.decimal_to_integral(GOE_TYPE_INTEGER_38),
            guard=_PrecisionGuards.integral_range(19, 38),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC}),
            _SynapseRules.decimal_to_integral(GOE_TYPE_DECIMAL),
            guard=_PrecisionGuards.scale_zero,
        ),
        MappingRule(frozenset({SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC}), _SynapseRules.decimal_to_decimal),
        MappingRule(frozenset({SYNAPSE_TYPE_DATE}), _SynapseRules.to_simple(GOE_TYPE_DATE)),
        MappingRule(frozenset({SYNAPSE_TYPE_TIME}), _SynapseRules.to_simple(GOE_TYPE_TIME, with_scale=True)),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DATETIME, SYNAPSE_TYPE_DATETIME2}),
            _SynapseRules.to_simple(GOE_TYPE_TIMESTAMP, with_scale=True),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_SMALLDATETIME}),
            _SynapseRules.to_simple(GOE_TYPE_TIMESTAMP, fixed_scale=0),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_DATETIMEOFFSET}),
            _SynapseRules.to_simple(GOE_TYPE_TIMESTAMP_TZ, with_scale=True),
        ),
        MappingRule(
            frozenset({SYNAPSE_TYPE_UNIQUEIDENTIFIER}),
            _SynapseRules.to_simple(GOE_TYPE_FIXED_STRING, fixed_length=36),
        ),
    ),
    ColumnDialect.HADOOP: (
        MappingRule(frozenset({HADOOP_TYPE_CHAR}), _HadoopRules.to_simple(GOE_TYPE_FIXED_STRING)),
        MappingRule(
            frozenset({HADOOP_TYPE_STRING, HADOOP_TYPE_VARCHAR}),
            _HadoopRules.to_simple(GOE_TYPE_VARIABLE_STRING),
        ),
        MappingRule(frozenset({HADOOP_TYPE_BINARY}), _HadoopRules.to_simple(GOE_TYPE_BINARY)),
        MappingRule(frozenset({HADOOP_TYPE_TINYINT}), _HadoopRules.to_simple(GOE_TYPE_INTEGER_1)),
        MappingRule(frozenset({HADOOP_TYPE_SMALLINT}), _HadoopRules.to_simple(GOE_TYPE_INTEGER_2)),
        MappingRule(frozenset({HADOOP_TYPE_INT}), _HadoopRules.to_simple(GOE_TYPE_INTEGER_4)),
        MappingRule(frozenset({HADOOP_TYPE_BIGINT}), _HadoopRules.to_simple(GOE_TYPE_INTEGER_8)),
        MappingRule(
            frozenset({HADOOP_TYPE_DECIMAL}),
            _HadoopRules.to_simple(GOE_TYPE_INTEGER_1),
            guard=_HadoopRules.decimal_scale_zero_guard(1, 2),
        ),
        MappingRule(
            frozenset({HADOOP_TYPE_DECIMAL}),
            _HadoopRules.to_simple(GOE_TYPE_INTEGER_2),
            guard=_HadoopRules.decimal_scale_zero_guard(3, 4),
        ),
        MappingRule(
            frozenset({HADOOP_TYPE_DECIMAL}),
            _HadoopRules.to_simple(GOE_TYPE_INTEGER_4),
            guard=_HadoopRules.decimal_scale_zero_guard(5, 9),
        ),
        MappingRule(
            frozenset({HADOOP_TYPE_DECIMAL}),
            _HadoopRules.to_simple(GOE_TYPE_INTEGER_8),
            guard=_HadoopRules.decimal_scale_zero_guard(10, 18),
        ),
        MappingRule(
            frozenset({HADOOP_TYPE_DECIMAL}),
            _HadoopRules.to_simple(GOE_TYPE_INTEGER_38),
            guard=_HadoopRules.decimal_scale_zero_guard(19, 38),
        ),
        MappingRule(
            frozenset({HADOOP_TYPE_DECIMAL}),
            _HadoopRules.decimal_scale_zero_overflow,
            guard=_PrecisionGuards.raw_scale_zero,
        ),
        MappingRule(frozenset({HADOOP_TYPE_DECIMAL}), _HadoopRules.decimal_to_canonical),
        MappingRule(frozenset({HADOOP_TYPE_FLOAT}), _HadoopRules.to_simple(GOE_TYPE_FLOAT)),
        MappingRule(
            frozenset({HADOOP_TYPE_DOUBLE, HADOOP_TYPE_DOUBLE_PRECISION, HADOOP_TYPE_REAL}),
            _HadoopRules.to_simple(GOE_TYPE_DOUBLE),
        ),
        MappingRule(frozenset({HADOOP_TYPE_DATE}), _HadoopRules.to_simple(GOE_TYPE_DATE)),
        MappingRule(frozenset({HADOOP_TYPE_TIMESTAMP}), _HadoopRules.timestamp_to_canonical),
        MappingRule(frozenset({HADOOP_TYPE_INTERVAL_DS}), _HadoopRules.to_simple(GOE_TYPE_INTERVAL_DS)),
        MappingRule(frozenset({HADOOP_TYPE_INTERVAL_YM}), _HadoopRules.to_simple(GOE_TYPE_INTERVAL_YM)),
        MappingRule(frozenset({HADOOP_TYPE_BOOLEAN}), _HadoopRules.to_simple(GOE_TYPE_BOOLEAN)),
    ),
    ColumnDialect.PARQUET: (
        MappingRule(frozenset({PARQUET_TYPE_BOOLEAN}), _StagingRules.to_simple(GOE_TYPE_BOOLEAN)),
        MappingRule(frozenset({PARQUET_TYPE_BINARY}), _StagingRules.binary_to_canonical),
        MappingRule(frozenset({PARQUET_TYPE_DOUBLE}), _StagingRules.to_simple(GOE_TYPE_DOUBLE)),
        MappingRule(frozenset({PARQUET_TYPE_FLOAT}), _StagingRules.to_simple(GOE_TYPE_FLOAT)),
        MappingRule(frozenset({PARQUET_TYPE_INT32}), _StagingRules.to_simple(GOE_TYPE_INTEGER_4)),
        MappingRule(frozenset({PARQUET_TYPE_INT64}), _StagingRules.to_simple(GOE_TYPE_INTEGER_8)),
        MappingRule(frozenset({PARQUET_TYPE_STRING}), _StagingRules.to_simple(GOE_TYPE_VARIABLE_STRING)),
    ),
    ColumnDialect.AVRO: (
        MappingRule(frozenset({AVRO_TYPE_BOOLEAN}), _StagingRules.to_simple(GOE_TYPE_BOOLEAN)),
        MappingRule(frozenset({AVRO_TYPE_BYTES}), _StagingRules.binary_to_canonical),
        MappingRule(frozenset({AVRO_TYPE_DOUBLE}), _StagingRules.to_simple(GOE_TYPE_DOUBLE)),
        MappingRule(frozenset({AVRO_TYPE_FLOAT}), _StagingRules.to_simple(GOE_TYPE_FLOAT)),
        MappingRule(frozenset({AVRO_TYPE_INT}), _StagingRules.to_simple(GOE_TYPE_INTEGER_4)),
        MappingRule(frozenset({AVRO_TYPE_LONG}), _StagingRules.to_simple(GOE_TYPE_INTEGER_8)),
        MappingRule(frozenset({AVRO_TYPE_STRING}), _StagingRules.to_simple(GOE_TYPE_VARIABLE_STRING)),
    ),
}

_HIVE_FROM_CANONICAL_RULES: tuple[MappingRule, ...] = (
    MappingRule(
        frozenset({GOE_TYPE_FIXED_STRING, GOE_TYPE_LARGE_STRING, GOE_TYPE_VARIABLE_STRING}),
        _HadoopRules.from_simple(HADOOP_TYPE_STRING, safe_mapping=True),
    ),
    MappingRule(
        frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        _HadoopRules.from_simple(HADOOP_TYPE_BINARY, safe_mapping=True),
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_1}),
        _HadoopRules.from_simple(HADOOP_TYPE_TINYINT, safe_mapping=True),
        guard=_PrecisionGuards.is_from_override,
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_2}),
        _HadoopRules.from_simple(HADOOP_TYPE_SMALLINT, safe_mapping=True),
        guard=_PrecisionGuards.is_from_override,
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_4}),
        _HadoopRules.from_simple(HADOOP_TYPE_INT, safe_mapping=True),
        guard=_PrecisionGuards.is_from_override,
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_1, GOE_TYPE_INTEGER_2, GOE_TYPE_INTEGER_4, GOE_TYPE_INTEGER_8}),
        _HadoopRules.from_simple(HADOOP_TYPE_BIGINT, safe_mapping=True),
    ),
    MappingRule(frozenset({GOE_TYPE_INTEGER_38}), _HadoopRules.from_int38),
    MappingRule(frozenset({GOE_TYPE_DECIMAL}), _HadoopRules.from_decimal),
    MappingRule(frozenset({GOE_TYPE_FLOAT}), _HadoopRules.from_simple(HADOOP_TYPE_FLOAT, safe_mapping=True)),
    MappingRule(frozenset({GOE_TYPE_DOUBLE}), _HadoopRules.from_simple(HADOOP_TYPE_DOUBLE, safe_mapping=True)),
    MappingRule(
        frozenset({GOE_TYPE_DATE}),
        _HadoopRules.from_simple(HADOOP_TYPE_TIMESTAMP),
        guard=_PrecisionGuards.canonical_date_not_supported,
    ),
    MappingRule(frozenset({GOE_TYPE_DATE}), _HadoopRules.from_simple(HADOOP_TYPE_DATE)),
    MappingRule(frozenset({GOE_TYPE_TIME}), _HadoopRules.from_simple(HADOOP_TYPE_STRING, safe_mapping=True)),
    MappingRule(
        frozenset({GOE_TYPE_TIMESTAMP, GOE_TYPE_TIMESTAMP_TZ}),
        _HadoopRules.from_simple(HADOOP_TYPE_TIMESTAMP, safe_mapping=False),
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTERVAL_DS, GOE_TYPE_INTERVAL_YM}),
        _HadoopRules.from_simple(HADOOP_TYPE_STRING, safe_mapping=False),
    ),
    MappingRule(frozenset({GOE_TYPE_BOOLEAN}), _HadoopRules.from_simple(HADOOP_TYPE_BOOLEAN, safe_mapping=True)),
)

_AVRO_FROM_CANONICAL_RULES: tuple[MappingRule, ...] = (
    MappingRule(
        frozenset({GOE_TYPE_FIXED_STRING, GOE_TYPE_LARGE_STRING, GOE_TYPE_VARIABLE_STRING}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_STRING, safe_mapping=True),
    ),
    MappingRule(
        frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        _StagingRules.from_binary(ColumnDialect.AVRO, AVRO_TYPE_BYTES, AVRO_TYPE_STRING),
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_1, GOE_TYPE_INTEGER_2, GOE_TYPE_INTEGER_4}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_INT, safe_mapping=True),
        guard=_PrecisionGuards.is_safe,
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_1, GOE_TYPE_INTEGER_2, GOE_TYPE_INTEGER_4}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_STRING, safe_mapping=False),
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_8}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_LONG, safe_mapping=True),
        guard=_PrecisionGuards.is_safe,
    ),
    MappingRule(
        frozenset({GOE_TYPE_INTEGER_8, GOE_TYPE_INTEGER_38, GOE_TYPE_DECIMAL}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_STRING, safe_mapping=False),
    ),
    MappingRule(
        frozenset({GOE_TYPE_FLOAT}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_FLOAT, safe_mapping=True),
        guard=_PrecisionGuards.is_safe,
    ),
    MappingRule(
        frozenset({GOE_TYPE_FLOAT}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_STRING, safe_mapping=False),
    ),
    MappingRule(
        frozenset({GOE_TYPE_DOUBLE}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_DOUBLE, safe_mapping=True),
        guard=_PrecisionGuards.is_safe,
    ),
    MappingRule(
        frozenset(
            {
                GOE_TYPE_DOUBLE,
                GOE_TYPE_DATE,
                GOE_TYPE_TIME,
                GOE_TYPE_TIMESTAMP,
                GOE_TYPE_TIMESTAMP_TZ,
                GOE_TYPE_INTERVAL_DS,
                GOE_TYPE_INTERVAL_YM,
            }
        ),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_STRING, safe_mapping=False),
    ),
    MappingRule(
        frozenset({GOE_TYPE_BOOLEAN}),
        _StagingRules.from_simple(ColumnDialect.AVRO, AVRO_TYPE_BOOLEAN, safe_mapping=True),
    ),
)

FROM_CANONICAL_RULES: dict[MappingTarget, tuple[MappingRule, ...]] = {
    MappingTarget.ORACLE: (
        MappingRule(
            frozenset({GOE_TYPE_FIXED_STRING}),
            _OracleRules.from_bounded_string(ORACLE_TYPE_CHAR, 2000, 1000),
        ),
        MappingRule(frozenset({GOE_TYPE_LARGE_STRING}), _OracleRules.from_large_string),
        MappingRule(
            frozenset({GOE_TYPE_VARIABLE_STRING}),
            _OracleRules.from_bounded_string(ORACLE_TYPE_VARCHAR2, 4000, 2000),
        ),
        MappingRule(frozenset({GOE_TYPE_BINARY}), _OracleRules.from_binary),
        MappingRule(frozenset({GOE_TYPE_LARGE_BINARY}), _OracleRules.from_large_binary),
        MappingRule(
            frozenset(
                {
                    GOE_TYPE_INTEGER_1,
                    GOE_TYPE_INTEGER_2,
                    GOE_TYPE_INTEGER_4,
                    GOE_TYPE_INTEGER_8,
                    GOE_TYPE_INTEGER_38,
                }
            ),
            _OracleRules.from_integer,
        ),
        MappingRule(frozenset({GOE_TYPE_DECIMAL}), _OracleRules.from_decimal),
        MappingRule(frozenset({GOE_TYPE_FLOAT}), _OracleRules.from_float),
        MappingRule(frozenset({GOE_TYPE_DOUBLE}), _OracleRules.from_double),
        MappingRule(frozenset({GOE_TYPE_DATE}), _OracleRules.from_date),
        MappingRule(frozenset({GOE_TYPE_TIME}), _OracleRules.from_time),
        MappingRule(frozenset({GOE_TYPE_TIMESTAMP}), _OracleRules.from_timestamp),
        MappingRule(frozenset({GOE_TYPE_TIMESTAMP_TZ}), _OracleRules.from_timestamp_tz),
        MappingRule(frozenset({GOE_TYPE_INTERVAL_DS}), _OracleRules.from_interval_ds),
        MappingRule(frozenset({GOE_TYPE_INTERVAL_YM}), _OracleRules.from_interval_ym),
    ),
    MappingTarget.MSSQL: (),
    MappingTarget.BIGQUERY: (
        MappingRule(
            frozenset({GOE_TYPE_BOOLEAN}),
            _BigQueryRules.from_simple(BIGQUERY_TYPE_BOOLEAN, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_FIXED_STRING, GOE_TYPE_LARGE_STRING, GOE_TYPE_VARIABLE_STRING}),
            _BigQueryRules.from_string,
        ),
        MappingRule(frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}), _BigQueryRules.from_binary),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_1, GOE_TYPE_INTEGER_2, GOE_TYPE_INTEGER_4, GOE_TYPE_INTEGER_8}),
            _BigQueryRules.from_simple(BIGQUERY_TYPE_INT64, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_38}),
            _BigQueryRules.from_int38_numeric,
            guard=_PrecisionGuards.precision_at_most(29),
        ),
        MappingRule(frozenset({GOE_TYPE_INTEGER_38}), _BigQueryRules.from_int38_bignumeric),
        MappingRule(
            frozenset({GOE_TYPE_DECIMAL}),
            _BigQueryRules.from_decimal_numeric,
            guard=_PrecisionGuards.integral_and_scale_at_most(29, 9),
        ),
        MappingRule(frozenset({GOE_TYPE_DECIMAL}), _BigQueryRules.from_decimal_bignumeric),
        MappingRule(
            frozenset({GOE_TYPE_FLOAT, GOE_TYPE_DOUBLE}),
            _BigQueryRules.from_simple(BIGQUERY_TYPE_FLOAT64, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_DATE}),
            _BigQueryRules.from_simple(BIGQUERY_TYPE_TIMESTAMP),
            guard=_PrecisionGuards.canonical_date_not_supported,
        ),
        MappingRule(frozenset({GOE_TYPE_DATE}), _BigQueryRules.from_simple(BIGQUERY_TYPE_DATE)),
        MappingRule(frozenset({GOE_TYPE_TIME}), _BigQueryRules.from_scaled_temporal(BIGQUERY_TYPE_TIME)),
        MappingRule(frozenset({GOE_TYPE_TIMESTAMP}), _BigQueryRules.from_scaled_temporal(BIGQUERY_TYPE_DATETIME)),
        MappingRule(
            frozenset({GOE_TYPE_TIMESTAMP_TZ}),
            _BigQueryRules.from_simple(BIGQUERY_TYPE_TIMESTAMP, safe_mapping=False),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTERVAL_DS, GOE_TYPE_INTERVAL_YM}),
            _BigQueryRules.from_simple(BIGQUERY_TYPE_STRING, safe_mapping=False),
        ),
    ),
    MappingTarget.SNOWFLAKE: (
        MappingRule(
            frozenset({GOE_TYPE_BOOLEAN}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_BOOLEAN, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_FIXED_STRING, GOE_TYPE_LARGE_STRING, GOE_TYPE_VARIABLE_STRING}),
            _SnowflakeRules.from_string,
        ),
        MappingRule(
            frozenset({GOE_TYPE_LARGE_BINARY, GOE_TYPE_BINARY}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_BINARY, with_length=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_DATE}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_DATE, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_FLOAT, GOE_TYPE_DOUBLE}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_FLOAT, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_1}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_NUMBER, data_precision=3, data_scale=0, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_2}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_NUMBER, data_precision=5, data_scale=0, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_4}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_NUMBER, data_precision=10, data_scale=0, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_8}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_NUMBER, data_precision=19, data_scale=0, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_38}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_NUMBER, data_precision=38, data_scale=0, safe_mapping=True),
        ),
        MappingRule(frozenset({GOE_TYPE_DECIMAL}), _SnowflakeRules.from_decimal),
        MappingRule(
            frozenset({GOE_TYPE_TIME}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_TIME, with_scale=True, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_TIMESTAMP}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_TIMESTAMP_NTZ, with_scale=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_TIMESTAMP_TZ}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_TIMESTAMP_TZ, with_scale=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTERVAL_DS, GOE_TYPE_INTERVAL_YM}),
            _SnowflakeRules.from_simple(SNOWFLAKE_TYPE_TEXT, safe_mapping=False),
        ),
    ),
    MappingTarget.SYNAPSE: (
        MappingRule(
            frozenset({GOE_TYPE_FIXED_STRING}),
            _SynapseRules.from_string(SYNAPSE_TYPE_CHAR, keep_lengths=True, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_LARGE_STRING}),
            _SynapseRules.from_string(SYNAPSE_TYPE_VARCHAR, keep_lengths=False),
        ),
        MappingRule(
            frozenset({GOE_TYPE_VARIABLE_STRING}),
            _SynapseRules.from_string(SYNAPSE_TYPE_VARCHAR, keep_lengths=True, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_BINARY}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_VARBINARY, with_length=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_LARGE_BINARY}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_VARBINARY),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_1, GOE_TYPE_INTEGER_2}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_SMALLINT, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_4}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_INT, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_8}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_BIGINT, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_38}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_NUMERIC, data_precision=38, data_scale=0, safe_mapping=True),
        ),
        MappingRule(frozenset({GOE_TYPE_DECIMAL}), _SynapseRules.from_decimal),
        MappingRule(
            frozenset({GOE_TYPE_DATE}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_DATE, safe_mapping=True),
        ),
        MappingRule(frozenset({GOE_TYPE_FLOAT}), _SynapseRules.from_simple(SYNAPSE_TYPE_REAL)),
        MappingRule(frozenset({GOE_TYPE_DOUBLE}), _SynapseRules.from_simple(SYNAPSE_TYPE_FLOAT)),
        MappingRule(frozenset({GOE_TYPE_TIME}), _SynapseRules.from_scaled_temporal(SYNAPSE_TYPE_TIME)),
        MappingRule(frozenset({GOE_TYPE_TIMESTAMP}), _SynapseRules.from_scaled_temporal(SYNAPSE_TYPE_DATETIME2)),
        MappingRule(
            frozenset({GOE_TYPE_TIMESTAMP_TZ}),
            _SynapseRules.from_scaled_temporal(SYNAPSE_TYPE_DATETIMEOFFSET),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTERVAL_DS, GOE_TYPE_INTERVAL_YM}),
            _SynapseRules.from_simple(SYNAPSE_TYPE_VARCHAR, fixed_length=100),
        ),
        MappingRule(frozenset({GOE_TYPE_BOOLEAN}), _SynapseRules.from_simple(SYNAPSE_TYPE_BIT)),
    ),
    MappingTarget.HIVE: _HIVE_FROM_CANONICAL_RULES,
    MappingTarget.IMPALA: (
        MappingRule(
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
            _HadoopRules.from_simple(HADOOP_TYPE_STRING),
        ),
        *_HIVE_FROM_CANONICAL_RULES,
    ),
    MappingTarget.PARQUET: (
        MappingRule(
            frozenset({GOE_TYPE_FIXED_STRING, GOE_TYPE_LARGE_STRING, GOE_TYPE_VARIABLE_STRING}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_STRING, safe_mapping=True),
        ),
        MappingRule(
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
            _StagingRules.from_binary(ColumnDialect.PARQUET, PARQUET_TYPE_BINARY, PARQUET_TYPE_STRING),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_1, GOE_TYPE_INTEGER_2, GOE_TYPE_INTEGER_4}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_INT32, safe_mapping=True),
            guard=_PrecisionGuards.is_safe,
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_1, GOE_TYPE_INTEGER_2, GOE_TYPE_INTEGER_4}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_STRING, safe_mapping=False),
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_8}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_INT64, safe_mapping=True),
            guard=_PrecisionGuards.is_safe,
        ),
        MappingRule(
            frozenset({GOE_TYPE_INTEGER_8, GOE_TYPE_INTEGER_38, GOE_TYPE_DECIMAL}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_STRING, safe_mapping=False),
        ),
        MappingRule(
            frozenset({GOE_TYPE_FLOAT}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_FLOAT, safe_mapping=True),
            guard=_PrecisionGuards.is_safe,
        ),
        MappingRule(
            frozenset({GOE_TYPE_FLOAT}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_STRING, safe_mapping=False),
        ),
        MappingRule(
            frozenset({GOE_TYPE_DOUBLE}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_DOUBLE, safe_mapping=True),
            guard=_PrecisionGuards.is_safe,
        ),
        MappingRule(
            frozenset(
                {
                    GOE_TYPE_DOUBLE,
                    GOE_TYPE_DATE,
                    GOE_TYPE_TIME,
                    GOE_TYPE_TIMESTAMP,
                    GOE_TYPE_TIMESTAMP_TZ,
                    GOE_TYPE_INTERVAL_DS,
                    GOE_TYPE_INTERVAL_YM,
                }
            ),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_STRING, safe_mapping=False),
        ),
        MappingRule(
            frozenset({GOE_TYPE_BOOLEAN}),
            _StagingRules.from_simple(ColumnDialect.PARQUET, PARQUET_TYPE_BOOLEAN, safe_mapping=True),
        ),
    ),
    MappingTarget.AVRO: _AVRO_FROM_CANONICAL_RULES,
    MappingTarget.AVRO_IMPALA: (
        MappingRule(
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
            _StagingRules.from_simple(
                ColumnDialect.AVRO,
                AVRO_TYPE_STRING,
                safe_mapping=True,
                keep_char_semantics=False,
            ),
        ),
        *_AVRO_FROM_CANONICAL_RULES,
    ),
}

_STRING_BINARY_INTERVAL_CANONICAL = frozenset(
    {
        *STRING_CANONICAL_TYPES,
        GOE_TYPE_BINARY,
        GOE_TYPE_LARGE_BINARY,
        GOE_TYPE_INTERVAL_DS,
        GOE_TYPE_INTERVAL_YM,
    }
)

OVERRIDE_RULES: dict[ColumnDialect, tuple[OverrideRule, ...]] = {
    ColumnDialect.ORACLE: (
        OverrideRule(
            _PrecisionGuards.data_type_in(ORACLE_TYPE_CHAR, ORACLE_TYPE_NCHAR), frozenset({GOE_TYPE_FIXED_STRING})
        ),
        OverrideRule(
            _PrecisionGuards.data_type_in(ORACLE_TYPE_CLOB, ORACLE_TYPE_NCLOB), frozenset({GOE_TYPE_LARGE_STRING})
        ),
        OverrideRule(
            _PrecisionGuards.data_type_in(ORACLE_TYPE_VARCHAR, ORACLE_TYPE_VARCHAR2, ORACLE_TYPE_NVARCHAR2),
            frozenset({GOE_TYPE_VARIABLE_STRING}),
        ),
        OverrideRule(_PrecisionGuards.data_type_in(ORACLE_TYPE_RAW), frozenset({GOE_TYPE_BINARY})),
        OverrideRule(_PrecisionGuards.data_type_in(ORACLE_TYPE_BLOB), frozenset({GOE_TYPE_LARGE_BINARY})),
        OverrideRule(
            _PrecisionGuards.data_type_in(ORACLE_TYPE_BINARY_FLOAT),
            frozenset({GOE_TYPE_FLOAT, GOE_TYPE_DOUBLE}),
        ),
        OverrideRule(_PrecisionGuards.data_type_in(ORACLE_TYPE_BINARY_DOUBLE), frozenset({GOE_TYPE_DOUBLE})),
        OverrideRule(_PrecisionGuards.is_number, frozenset(NUMERIC_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_date_with_tz, frozenset({GOE_TYPE_TIMESTAMP_TZ})),
        OverrideRule(_PrecisionGuards.is_date, frozenset({*DATE_CANONICAL_TYPES, *STRING_CANONICAL_TYPES})),
        OverrideRule(_PrecisionGuards.data_type_in(ORACLE_TYPE_INTERVAL_DS), frozenset({GOE_TYPE_INTERVAL_DS})),
        OverrideRule(_PrecisionGuards.data_type_in(ORACLE_TYPE_INTERVAL_YM), frozenset({GOE_TYPE_INTERVAL_YM})),
    ),
    ColumnDialect.MSSQL: (
        OverrideRule(_PrecisionGuards.data_type_in(MSSQL_TYPE_BIT), frozenset({GOE_TYPE_BOOLEAN})),
        OverrideRule(
            _PrecisionGuards.data_type_in(MSSQL_TYPE_CHAR, MSSQL_TYPE_NCHAR), frozenset({GOE_TYPE_FIXED_STRING})
        ),
        OverrideRule(
            _PrecisionGuards.data_type_in(MSSQL_TYPE_TEXT, MSSQL_TYPE_NTEXT), frozenset({GOE_TYPE_LARGE_STRING})
        ),
        OverrideRule(
            _PrecisionGuards.data_type_in(MSSQL_TYPE_VARCHAR, MSSQL_TYPE_NVARCHAR, MSSQL_TYPE_UNIQUEIDENTIFIER),
            frozenset({GOE_TYPE_VARIABLE_STRING}),
        ),
        OverrideRule(
            _PrecisionGuards.data_type_in(MSSQL_TYPE_BINARY, MSSQL_TYPE_VARBINARY, MSSQL_TYPE_IMAGE),
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        ),
        OverrideRule(_PrecisionGuards.data_type_in(MSSQL_TYPE_FLOAT), frozenset({GOE_TYPE_DOUBLE})),
        OverrideRule(_PrecisionGuards.data_type_in(MSSQL_TYPE_REAL), frozenset({GOE_TYPE_FLOAT})),
        OverrideRule(_PrecisionGuards.is_number, frozenset(NUMERIC_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_date_with_tz, frozenset({GOE_TYPE_TIMESTAMP_TZ})),
        OverrideRule(_PrecisionGuards.is_date, frozenset({GOE_TYPE_DATE, GOE_TYPE_TIMESTAMP, *STRING_CANONICAL_TYPES})),
        OverrideRule(_PrecisionGuards.data_type_in(MSSQL_TYPE_TIME), frozenset({GOE_TYPE_TIME})),
    ),
    ColumnDialect.BIGQUERY: (
        OverrideRule(
            _PrecisionGuards.data_type_in(BIGQUERY_TYPE_FLOAT64),
            frozenset({GOE_TYPE_DECIMAL, GOE_TYPE_DOUBLE}),
        ),
        OverrideRule(_PrecisionGuards.is_number, frozenset(NUMERIC_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_date, frozenset(DATE_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_string, _STRING_BINARY_INTERVAL_CANONICAL),
        OverrideRule(_PrecisionGuards.unsupported_backend_type, frozenset()),
        OverrideRule(_PrecisionGuards.data_type_in(BIGQUERY_TYPE_BOOLEAN), frozenset({GOE_TYPE_BOOLEAN})),
        OverrideRule(
            _PrecisionGuards.data_type_in(BIGQUERY_TYPE_BYTES),
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        ),
        OverrideRule(_PrecisionGuards.data_type_in(BIGQUERY_TYPE_TIME), frozenset({GOE_TYPE_TIME})),
    ),
    ColumnDialect.SNOWFLAKE: (
        OverrideRule(
            _PrecisionGuards.data_type_in(SNOWFLAKE_TYPE_FLOAT),
            frozenset({GOE_TYPE_DECIMAL, GOE_TYPE_DOUBLE}),
        ),
        OverrideRule(_PrecisionGuards.is_number, frozenset(NUMERIC_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_date, frozenset(DATE_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_string, _STRING_BINARY_INTERVAL_CANONICAL),
        OverrideRule(_PrecisionGuards.unsupported_backend_type, frozenset()),
        OverrideRule(
            _PrecisionGuards.data_type_in(SNOWFLAKE_TYPE_BINARY),
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        ),
        OverrideRule(_PrecisionGuards.data_type_in(SNOWFLAKE_TYPE_TIME), frozenset({GOE_TYPE_TIME})),
    ),
    ColumnDialect.SYNAPSE: (
        OverrideRule(
            _PrecisionGuards.data_type_in(SYNAPSE_TYPE_REAL, SYNAPSE_TYPE_FLOAT),
            frozenset({GOE_TYPE_DECIMAL, GOE_TYPE_DOUBLE, GOE_TYPE_FLOAT}),
        ),
        OverrideRule(_PrecisionGuards.is_number, frozenset(NUMERIC_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_date, frozenset(DATE_CANONICAL_TYPES)),
        OverrideRule(
            _PrecisionGuards.data_type_in(SYNAPSE_TYPE_CHAR, SYNAPSE_TYPE_NCHAR),
            frozenset({*STRING_CANONICAL_TYPES, GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        ),
        OverrideRule(_PrecisionGuards.is_string, _STRING_BINARY_INTERVAL_CANONICAL),
        OverrideRule(_PrecisionGuards.unsupported_backend_type, frozenset()),
        OverrideRule(
            _PrecisionGuards.data_type_in(SYNAPSE_TYPE_BINARY, SYNAPSE_TYPE_VARBINARY),
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        ),
        OverrideRule(_PrecisionGuards.data_type_in(SYNAPSE_TYPE_TIME), frozenset({GOE_TYPE_TIME})),
    ),
    ColumnDialect.HADOOP: (
        OverrideRule(
            _PrecisionGuards.data_type_in(HADOOP_TYPE_DOUBLE, HADOOP_TYPE_FLOAT),
            frozenset({GOE_TYPE_DECIMAL, GOE_TYPE_DOUBLE, GOE_TYPE_FLOAT}),
        ),
        OverrideRule(_PrecisionGuards.is_number, frozenset(NUMERIC_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.is_date, frozenset(DATE_CANONICAL_TYPES)),
        OverrideRule(_PrecisionGuards.data_type_in(HADOOP_TYPE_CHAR), frozenset({GOE_TYPE_FIXED_STRING})),
        OverrideRule(_PrecisionGuards.is_string, _STRING_BINARY_INTERVAL_CANONICAL),
        OverrideRule(_PrecisionGuards.unsupported_backend_type, frozenset()),
        OverrideRule(_PrecisionGuards.data_type_in(HADOOP_TYPE_BOOLEAN), frozenset({GOE_TYPE_BOOLEAN})),
        OverrideRule(
            _PrecisionGuards.data_type_in(HADOOP_TYPE_BINARY),
            frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        ),
    ),
}

_UNSUPPORTED_TO_CANONICAL_PREFIX: dict[ColumnDialect, str] = {
    ColumnDialect.ORACLE: "Unsupported Oracle data type",
    ColumnDialect.MSSQL: "Unsupported MSSQL data type",
    ColumnDialect.SYNAPSE: "Unsupported Synapse SQL data type",
    ColumnDialect.PARQUET: "Unsupported Parquet data type",
    ColumnDialect.AVRO: "Unsupported Avro data type",
}


class CanonicalTypeRegistry:
    """Table-driven canonical-to-physical and physical-to-canonical type mapping."""

    def __init__(
        self,
        to_canonical_rules: Mapping[ColumnDialect, tuple[MappingRule, ...]] = TO_CANONICAL_RULES,
        from_canonical_rules: Mapping[MappingTarget, tuple[MappingRule, ...]] = FROM_CANONICAL_RULES,
        override_rules: Mapping[ColumnDialect, tuple[OverrideRule, ...]] = OVERRIDE_RULES,
    ) -> None:
        self._to_canonical_rules = to_canonical_rules
        self._from_canonical_rules = from_canonical_rules
        self._override_rules = override_rules

    def to_canonical(self, column: ColumnSpec, context: MappingContext) -> ColumnSpec:
        """Translate a physical dialect column into a canonical ColumnSpec."""
        for rule in self._to_canonical_rules.get(column.dialect, ()):
            if column.data_type in rule.source_types and (rule.guard is None or rule.guard(column, context)):
                return rule.transform(column, context)
        prefix = _UNSUPPORTED_TO_CANONICAL_PREFIX.get(column.dialect, "Unsupported backend data type")
        raise ColumnSpecError(f"{prefix}: {column.data_type}")

    def staging_to_canonical(self, column: ColumnSpec, context: MappingContext) -> ColumnSpec:
        """Translate a Parquet or Avro staging column into a canonical ColumnSpec."""
        return self.to_canonical(column, context)

    def from_canonical(self, column: ColumnSpec, target: MappingTarget, context: MappingContext) -> ColumnSpec:
        """Translate a canonical ColumnSpec into the target physical or staging dialect."""
        if target is MappingTarget.MSSQL:
            raise ColumnSpecError("MSSQL from_canonical_column() not implemented.")
        for rule in self._from_canonical_rules.get(target, ()):
            if column.data_type in rule.source_types and (rule.guard is None or rule.guard(column, context)):
                return rule.transform(column, context)
        raise ColumnSpecError(f"Unsupported GOE data type: {column.data_type}")

    def valid_canonical_override(
        self,
        column: ColumnSpec,
        canonical_type: ColumnSpec | str,
        context: MappingContext,
    ) -> bool:
        """Return True if canonical_type is a valid user-specified canonical override for column."""
        target_type = canonical_type.data_type if isinstance(canonical_type, ColumnSpec) else canonical_type
        for rule in self._override_rules.get(column.dialect, ()):
            if rule.matches(column, context):
                return target_type in rule.allowed
        if target_type not in ALL_CANONICAL_TYPES and column.dialect is not ColumnDialect.MSSQL and context.log:
            context.log(f"Unknown canonical type in mapping: {target_type}", VVERBOSE)
        return False

    def default_numeric_column(
        self,
        name: str,
        target: MappingTarget,
        context: MappingContext,
        data_scale: int | None = None,
    ) -> ColumnSpec:
        """Return a default best-fit numeric ColumnSpec for generic numeric expressions."""
        match target:
            case MappingTarget.BIGQUERY:
                if data_scale == 0:
                    return ColumnSpec(
                        ColumnDialect.BIGQUERY,
                        name,
                        BIGQUERY_TYPE_INT64,
                        nullable=True,
                        safe_mapping=False,
                    )
                if data_scale and data_scale <= 9:
                    return ColumnSpec(
                        ColumnDialect.BIGQUERY,
                        name,
                        BIGQUERY_TYPE_NUMERIC,
                        data_precision=38,
                        data_scale=9,
                        nullable=True,
                        safe_mapping=False,
                    )
                return ColumnSpec(
                    ColumnDialect.BIGQUERY,
                    name,
                    BIGQUERY_TYPE_BIGNUMERIC,
                    data_precision=context.limits.max_decimal_precision,
                    data_scale=context.limits.max_decimal_scale,
                    nullable=True,
                    safe_mapping=False,
                )
            case MappingTarget.SNOWFLAKE:
                return _SnowflakeRules.default_numeric(name, context, data_scale=data_scale)
            case MappingTarget.SYNAPSE:
                return _SynapseRules.default_numeric(name, context, data_scale=data_scale)
            case MappingTarget.HIVE | MappingTarget.IMPALA:
                return _HadoopRules.default_numeric(name, context, data_scale=data_scale)
            case _:
                raise ColumnSpecError(f"Default numeric column is not supported for target: {target}")

    def synthetic_partition_column(
        self,
        canonical_column: ColumnSpec,
        synthetic_name: str,
        target: MappingTarget,
    ) -> ColumnSpec:
        """Return the backend ColumnSpec for a synthetic partition column."""
        match target:
            case MappingTarget.BIGQUERY:
                if canonical_column.is_date_based():
                    return ColumnSpec(
                        ColumnDialect.BIGQUERY,
                        synthetic_name,
                        BIGQUERY_TYPE_DATE,
                        partition_info=canonical_column.partition_info,
                    )
                if canonical_column.is_number_based():
                    return ColumnSpec(
                        ColumnDialect.BIGQUERY,
                        synthetic_name,
                        BIGQUERY_TYPE_INT64,
                        partition_info=canonical_column.partition_info,
                    )
                raise ColumnSpecError(
                    f"BigQuery synthetic partitioning not implemented for column type: {canonical_column.data_type}"
                )
            case MappingTarget.HIVE | MappingTarget.IMPALA:
                return ColumnSpec(
                    ColumnDialect.HADOOP,
                    synthetic_name,
                    HADOOP_TYPE_STRING,
                    partition_info=canonical_column.partition_info,
                )
            case _:
                raise ColumnSpecError(f"Synthetic partitioning is not supported for target: {target}")


TYPE_REGISTRY = CanonicalTypeRegistry()
