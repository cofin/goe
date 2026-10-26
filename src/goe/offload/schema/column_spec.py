# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Immutable column specification, dialect vocabulary, traits, and column list helpers."""

import re
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Any

import msgspec

from goe.exceptions import GOEError
from goe.typing import FrozenBaseStruct

__all__ = [
    "ALL_CANONICAL_TYPES",
    "AVRO_TYPE_BOOLEAN",
    "AVRO_TYPE_BYTES",
    "AVRO_TYPE_DOUBLE",
    "AVRO_TYPE_FLOAT",
    "AVRO_TYPE_INT",
    "AVRO_TYPE_LONG",
    "AVRO_TYPE_STRING",
    "BIGQUERY_TYPE_BIGNUMERIC",
    "BIGQUERY_TYPE_BOOLEAN",
    "BIGQUERY_TYPE_BYTES",
    "BIGQUERY_TYPE_DATE",
    "BIGQUERY_TYPE_DATETIME",
    "BIGQUERY_TYPE_FLOAT",
    "BIGQUERY_TYPE_FLOAT64",
    "BIGQUERY_TYPE_INT64",
    "BIGQUERY_TYPE_INTEGER",
    "BIGQUERY_TYPE_NUMERIC",
    "BIGQUERY_TYPE_STRING",
    "BIGQUERY_TYPE_TIME",
    "BIGQUERY_TYPE_TIMESTAMP",
    "CANONICAL_CHAR_SEMANTICS_BYTE",
    "CANONICAL_CHAR_SEMANTICS_CHAR",
    "CANONICAL_CHAR_SEMANTICS_UNICODE",
    "CANONICAL_TYPE_BYTE_LENGTHS",
    "CANONICAL_TYPE_OPTION_NAMES",
    "DATE_CANONICAL_TYPES",
    "DIALECT_TRAITS",
    "GOE_TYPE_BINARY",
    "GOE_TYPE_BOOLEAN",
    "GOE_TYPE_DATE",
    "GOE_TYPE_DECIMAL",
    "GOE_TYPE_DOUBLE",
    "GOE_TYPE_FIXED_STRING",
    "GOE_TYPE_FLOAT",
    "GOE_TYPE_INTEGER_1",
    "GOE_TYPE_INTEGER_2",
    "GOE_TYPE_INTEGER_4",
    "GOE_TYPE_INTEGER_8",
    "GOE_TYPE_INTEGER_38",
    "GOE_TYPE_INTERVAL_DS",
    "GOE_TYPE_INTERVAL_YM",
    "GOE_TYPE_LARGE_BINARY",
    "GOE_TYPE_LARGE_STRING",
    "GOE_TYPE_TIME",
    "GOE_TYPE_TIMESTAMP",
    "GOE_TYPE_TIMESTAMP_TZ",
    "GOE_TYPE_VARIABLE_STRING",
    "HADOOP_TYPE_BIGINT",
    "HADOOP_TYPE_BINARY",
    "HADOOP_TYPE_BOOLEAN",
    "HADOOP_TYPE_CHAR",
    "HADOOP_TYPE_DATE",
    "HADOOP_TYPE_DECIMAL",
    "HADOOP_TYPE_DOUBLE",
    "HADOOP_TYPE_DOUBLE_PRECISION",
    "HADOOP_TYPE_FLOAT",
    "HADOOP_TYPE_INT",
    "HADOOP_TYPE_INTERVAL_DS",
    "HADOOP_TYPE_INTERVAL_YM",
    "HADOOP_TYPE_REAL",
    "HADOOP_TYPE_SMALLINT",
    "HADOOP_TYPE_STRING",
    "HADOOP_TYPE_TIMESTAMP",
    "HADOOP_TYPE_TINYINT",
    "HADOOP_TYPE_VARCHAR",
    "MSSQL_TYPE_BIGINT",
    "MSSQL_TYPE_BINARY",
    "MSSQL_TYPE_BIT",
    "MSSQL_TYPE_CHAR",
    "MSSQL_TYPE_DATE",
    "MSSQL_TYPE_DATETIME",
    "MSSQL_TYPE_DATETIME2",
    "MSSQL_TYPE_DATETIMEOFFSET",
    "MSSQL_TYPE_DECIMAL",
    "MSSQL_TYPE_FLOAT",
    "MSSQL_TYPE_IMAGE",
    "MSSQL_TYPE_INT",
    "MSSQL_TYPE_MONEY",
    "MSSQL_TYPE_NCHAR",
    "MSSQL_TYPE_NTEXT",
    "MSSQL_TYPE_NUMERIC",
    "MSSQL_TYPE_NVARCHAR",
    "MSSQL_TYPE_REAL",
    "MSSQL_TYPE_SMALLDATETIME",
    "MSSQL_TYPE_SMALLINT",
    "MSSQL_TYPE_SMALLMONEY",
    "MSSQL_TYPE_TEXT",
    "MSSQL_TYPE_TIME",
    "MSSQL_TYPE_TINYINT",
    "MSSQL_TYPE_UNIQUEIDENTIFIER",
    "MSSQL_TYPE_VARBINARY",
    "MSSQL_TYPE_VARCHAR",
    "NUMERIC_CANONICAL_TYPES",
    "ORACLE_INTERVAL_DS_RE",
    "ORACLE_INTERVAL_DS_SUB_PATTERN",
    "ORACLE_INTERVAL_YM_RE",
    "ORACLE_INTERVAL_YM_SUB_PATTERN",
    "ORACLE_TIMESTAMP_LOCAL_TZ_RE",
    "ORACLE_TIMESTAMP_LOCAL_TZ_SUB_PATTERN",
    "ORACLE_TIMESTAMP_RE",
    "ORACLE_TIMESTAMP_SUB_PATTERN",
    "ORACLE_TIMESTAMP_TZ_RE",
    "ORACLE_TIMESTAMP_TZ_SUB_PATTERN",
    "ORACLE_TYPE_BFILE",
    "ORACLE_TYPE_BINARY_DOUBLE",
    "ORACLE_TYPE_BINARY_FLOAT",
    "ORACLE_TYPE_BLOB",
    "ORACLE_TYPE_CHAR",
    "ORACLE_TYPE_CLOB",
    "ORACLE_TYPE_DATE",
    "ORACLE_TYPE_FLOAT",
    "ORACLE_TYPE_INTERVAL_DS",
    "ORACLE_TYPE_INTERVAL_YM",
    "ORACLE_TYPE_LONG",
    "ORACLE_TYPE_LONG_RAW",
    "ORACLE_TYPE_NCHAR",
    "ORACLE_TYPE_NCLOB",
    "ORACLE_TYPE_NUMBER",
    "ORACLE_TYPE_NVARCHAR2",
    "ORACLE_TYPE_RAW",
    "ORACLE_TYPE_TIMESTAMP",
    "ORACLE_TYPE_TIMESTAMP_LOCAL_TZ",
    "ORACLE_TYPE_TIMESTAMP_TZ",
    "ORACLE_TYPE_VARCHAR",
    "ORACLE_TYPE_VARCHAR2",
    "ORACLE_TYPE_XMLTYPE",
    "PARQUET_TYPE_BINARY",
    "PARQUET_TYPE_BOOLEAN",
    "PARQUET_TYPE_DOUBLE",
    "PARQUET_TYPE_FLOAT",
    "PARQUET_TYPE_INT32",
    "PARQUET_TYPE_INT64",
    "PARQUET_TYPE_STRING",
    "SNOWFLAKE_TYPE_BINARY",
    "SNOWFLAKE_TYPE_BOOLEAN",
    "SNOWFLAKE_TYPE_DATE",
    "SNOWFLAKE_TYPE_FLOAT",
    "SNOWFLAKE_TYPE_INTEGER",
    "SNOWFLAKE_TYPE_NUMBER",
    "SNOWFLAKE_TYPE_TEXT",
    "SNOWFLAKE_TYPE_TIME",
    "SNOWFLAKE_TYPE_TIMESTAMP_NTZ",
    "SNOWFLAKE_TYPE_TIMESTAMP_TZ",
    "STAGING_FILE_SIMPLIFIED_NAME_TOKEN",
    "STAGING_FILE_UNSUPPORTED_NAME_CHARACTERS",
    "STRING_CANONICAL_TYPES",
    "SYNAPSE_TYPE_BIGINT",
    "SYNAPSE_TYPE_BINARY",
    "SYNAPSE_TYPE_BIT",
    "SYNAPSE_TYPE_CHAR",
    "SYNAPSE_TYPE_DATE",
    "SYNAPSE_TYPE_DATETIME",
    "SYNAPSE_TYPE_DATETIME2",
    "SYNAPSE_TYPE_DATETIMEOFFSET",
    "SYNAPSE_TYPE_DECIMAL",
    "SYNAPSE_TYPE_FLOAT",
    "SYNAPSE_TYPE_INT",
    "SYNAPSE_TYPE_MAX_TOKEN",
    "SYNAPSE_TYPE_MONEY",
    "SYNAPSE_TYPE_NCHAR",
    "SYNAPSE_TYPE_NUMERIC",
    "SYNAPSE_TYPE_NVARCHAR",
    "SYNAPSE_TYPE_REAL",
    "SYNAPSE_TYPE_SMALLDATETIME",
    "SYNAPSE_TYPE_SMALLINT",
    "SYNAPSE_TYPE_SMALLMONEY",
    "SYNAPSE_TYPE_TIME",
    "SYNAPSE_TYPE_TINYINT",
    "SYNAPSE_TYPE_UNIQUEIDENTIFIER",
    "SYNAPSE_TYPE_VARBINARY",
    "SYNAPSE_TYPE_VARCHAR",
    "SYNTHETIC_PARTITION_COLUMN_NAME_RE",
    "SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE",
    "TEXT_LENGTH_UPPER_LIMIT",
    "ColumnDialect",
    "ColumnPartitionSpec",
    "ColumnSpec",
    "ColumnSpecError",
    "DialectTraits",
    "get_column_names",
    "get_partition_columns",
    "get_partition_source_column_names",
    "invalid_column_list_message",
    "is_safe_mapping",
    "is_synthetic_partition_column",
    "match_partition_column_by_source",
    "match_table_column",
    "match_table_column_position",
    "regex_real_column_from_part_column",
    "str_list_of_columns",
    "valid_column_list",
]

GOE_TYPE_FIXED_STRING = "FIXED_STRING"
GOE_TYPE_LARGE_STRING = "LARGE_STRING"
GOE_TYPE_VARIABLE_STRING = "VARIABLE_STRING"
GOE_TYPE_BINARY = "BINARY"
GOE_TYPE_LARGE_BINARY = "LARGE_BINARY"
GOE_TYPE_INTEGER_1 = "INTEGER_1"
GOE_TYPE_INTEGER_2 = "INTEGER_2"
GOE_TYPE_INTEGER_4 = "INTEGER_4"
GOE_TYPE_INTEGER_8 = "INTEGER_8"
GOE_TYPE_INTEGER_38 = "INTEGER_38"
GOE_TYPE_DECIMAL = "DECIMAL"
GOE_TYPE_FLOAT = "FLOAT"
GOE_TYPE_DOUBLE = "DOUBLE"
GOE_TYPE_DATE = "DATE"
GOE_TYPE_TIME = "TIME"
GOE_TYPE_TIMESTAMP = "TIMESTAMP"
GOE_TYPE_TIMESTAMP_TZ = "TIMESTAMP_TZ"
GOE_TYPE_INTERVAL_DS = "INTERVAL_DS"
GOE_TYPE_INTERVAL_YM = "INTERVAL_YM"
GOE_TYPE_BOOLEAN = "BOOLEAN"

ALL_CANONICAL_TYPES: tuple[str, ...] = (
    GOE_TYPE_FIXED_STRING,
    GOE_TYPE_LARGE_STRING,
    GOE_TYPE_VARIABLE_STRING,
    GOE_TYPE_BINARY,
    GOE_TYPE_LARGE_BINARY,
    GOE_TYPE_INTEGER_1,
    GOE_TYPE_INTEGER_2,
    GOE_TYPE_INTEGER_4,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_INTEGER_38,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_FLOAT,
    GOE_TYPE_DOUBLE,
    GOE_TYPE_DATE,
    GOE_TYPE_TIME,
    GOE_TYPE_TIMESTAMP,
    GOE_TYPE_TIMESTAMP_TZ,
    GOE_TYPE_INTERVAL_DS,
    GOE_TYPE_INTERVAL_YM,
    GOE_TYPE_BOOLEAN,
)

DATE_CANONICAL_TYPES: tuple[str, ...] = (
    GOE_TYPE_DATE,
    GOE_TYPE_TIMESTAMP,
    GOE_TYPE_TIMESTAMP_TZ,
)

NUMERIC_CANONICAL_TYPES: tuple[str, ...] = (
    GOE_TYPE_INTEGER_1,
    GOE_TYPE_INTEGER_2,
    GOE_TYPE_INTEGER_4,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_INTEGER_38,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_FLOAT,
    GOE_TYPE_DOUBLE,
)

STRING_CANONICAL_TYPES: tuple[str, ...] = (
    GOE_TYPE_FIXED_STRING,
    GOE_TYPE_LARGE_STRING,
    GOE_TYPE_VARIABLE_STRING,
)

CANONICAL_TYPE_OPTION_NAMES: dict[str, str] = {
    GOE_TYPE_BINARY: "--binary-columns",
    GOE_TYPE_DATE: "--date-columns",
    GOE_TYPE_DECIMAL: "--decimal-columns",
    GOE_TYPE_DOUBLE: "--double-columns",
    GOE_TYPE_INTEGER_1: "--integer-1-columns",
    GOE_TYPE_INTEGER_2: "--integer-2-columns",
    GOE_TYPE_INTEGER_4: "--integer-4-columns",
    GOE_TYPE_INTEGER_8: "--integer-8-columns",
    GOE_TYPE_INTEGER_38: "--integer-38-columns",
    GOE_TYPE_LARGE_STRING: "--large-string-columns",
    GOE_TYPE_LARGE_BINARY: "--large-binary-columns",
    GOE_TYPE_VARIABLE_STRING: "--variable-string-columns",
    GOE_TYPE_INTERVAL_DS: "--interval-ds-columns",
    GOE_TYPE_INTERVAL_YM: "--interval-ym-columns",
    GOE_TYPE_TIMESTAMP_TZ: "--timestamp-tz-columns",
}

CANONICAL_TYPE_BYTE_LENGTHS: dict[str, int] = {
    GOE_TYPE_INTEGER_1: 1,
    GOE_TYPE_INTEGER_2: 2,
    GOE_TYPE_INTEGER_4: 4,
    GOE_TYPE_INTEGER_8: 8,
    GOE_TYPE_FLOAT: 4,
    GOE_TYPE_DOUBLE: 8,
}

CANONICAL_CHAR_SEMANTICS_BYTE = "BYTE"
CANONICAL_CHAR_SEMANTICS_CHAR = "CHAR"
CANONICAL_CHAR_SEMANTICS_UNICODE = "UNICODE"

SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE = "GOE_PART_%s_%s"
SYNTHETIC_PARTITION_COLUMN_NAME_RE = re.compile(r"(^GOE_PART_)(Y|M|D|\d+|U\d+)_([A-Z0-9$#_]+$)", re.IGNORECASE)

STAGING_FILE_SIMPLIFIED_NAME_TOKEN = "_GOE_SPECIAL_CHAR_COLUMN"
STAGING_FILE_UNSUPPORTED_NAME_CHARACTERS: tuple[str, ...] = (" ", "-", "#")

ORACLE_TYPE_CHAR = "CHAR"
ORACLE_TYPE_NCHAR = "NCHAR"
ORACLE_TYPE_CLOB = "CLOB"
ORACLE_TYPE_NCLOB = "NCLOB"
ORACLE_TYPE_LONG = "LONG"
ORACLE_TYPE_VARCHAR = "VARCHAR"
ORACLE_TYPE_VARCHAR2 = "VARCHAR2"
ORACLE_TYPE_NVARCHAR2 = "NVARCHAR2"
ORACLE_TYPE_RAW = "RAW"
ORACLE_TYPE_BFILE = "BFILE"
ORACLE_TYPE_BLOB = "BLOB"
ORACLE_TYPE_LONG_RAW = "LONG RAW"
ORACLE_TYPE_NUMBER = "NUMBER"
ORACLE_TYPE_FLOAT = "FLOAT"
ORACLE_TYPE_BINARY_FLOAT = "BINARY_FLOAT"
ORACLE_TYPE_BINARY_DOUBLE = "BINARY_DOUBLE"
ORACLE_TYPE_DATE = "DATE"
ORACLE_TYPE_TIMESTAMP = "TIMESTAMP"
ORACLE_TYPE_TIMESTAMP_TZ = "TIMESTAMP WITH TIME ZONE"
ORACLE_TYPE_TIMESTAMP_LOCAL_TZ = "TIMESTAMP WITH LOCAL TIME ZONE"
ORACLE_TYPE_INTERVAL_DS = "INTERVAL DAY TO SECOND"
ORACLE_TYPE_INTERVAL_YM = "INTERVAL YEAR TO MONTH"
ORACLE_TYPE_XMLTYPE = "XMLTYPE"
ORACLE_TIMESTAMP_RE = re.compile(r"^TIMESTAMP\(([0-9])\)$", re.IGNORECASE)
ORACLE_TIMESTAMP_SUB_PATTERN = "TIMESTAMP(%s)"
ORACLE_TIMESTAMP_TZ_RE = re.compile(r"^TIMESTAMP\(([0-9])\) WITH TIME ZONE$", re.IGNORECASE)
ORACLE_TIMESTAMP_TZ_SUB_PATTERN = "TIMESTAMP(%s) WITH TIME ZONE"
ORACLE_TIMESTAMP_LOCAL_TZ_RE = re.compile(r"^TIMESTAMP\(([0-9])\) WITH LOCAL TIME ZONE$", re.IGNORECASE)
ORACLE_TIMESTAMP_LOCAL_TZ_SUB_PATTERN = "TIMESTAMP(%s) WITH LOCAL TIME ZONE"
ORACLE_INTERVAL_DS_RE = re.compile(r"^INTERVAL DAY(\([0-9]\))? TO SECOND(\([0-9]\))?$", re.IGNORECASE)
ORACLE_INTERVAL_DS_SUB_PATTERN = "INTERVAL DAY(%s) TO SECOND(%s)"
ORACLE_INTERVAL_YM_RE = re.compile(r"^INTERVAL YEAR(\([0-9]\))? TO MONTH(\([0-9]\))?$", re.IGNORECASE)
ORACLE_INTERVAL_YM_SUB_PATTERN = "INTERVAL YEAR(%s) TO MONTH"

MSSQL_TYPE_BIGINT = "bigint"
MSSQL_TYPE_BIT = "bit"
MSSQL_TYPE_DECIMAL = "decimal"
MSSQL_TYPE_INT = "int"
MSSQL_TYPE_MONEY = "money"
MSSQL_TYPE_NUMERIC = "numeric"
MSSQL_TYPE_SMALLINT = "smallint"
MSSQL_TYPE_SMALLMONEY = "smallmoney"
MSSQL_TYPE_TINYINT = "tinyint"
MSSQL_TYPE_FLOAT = "float"
MSSQL_TYPE_REAL = "real"
MSSQL_TYPE_DATE = "date"
MSSQL_TYPE_DATETIME2 = "datetime2"
MSSQL_TYPE_DATETIME = "datetime"
MSSQL_TYPE_DATETIMEOFFSET = "datetimeoffset"
MSSQL_TYPE_SMALLDATETIME = "smalldatetime"
MSSQL_TYPE_TIME = "time"
MSSQL_TYPE_CHAR = "char"
MSSQL_TYPE_VARCHAR = "varchar"
MSSQL_TYPE_NCHAR = "nchar"
MSSQL_TYPE_NVARCHAR = "nvarchar"
MSSQL_TYPE_UNIQUEIDENTIFIER = "uniqueidentifier"
MSSQL_TYPE_TEXT = "text"
MSSQL_TYPE_NTEXT = "ntext"
MSSQL_TYPE_BINARY = "binary"
MSSQL_TYPE_VARBINARY = "varbinary"
MSSQL_TYPE_IMAGE = "image"

BIGQUERY_TYPE_BIGNUMERIC = "BIGNUMERIC"
BIGQUERY_TYPE_BOOLEAN = "BOOLEAN"
BIGQUERY_TYPE_BYTES = "BYTES"
BIGQUERY_TYPE_DATE = "DATE"
BIGQUERY_TYPE_DATETIME = "DATETIME"
BIGQUERY_TYPE_FLOAT = "FLOAT"
BIGQUERY_TYPE_FLOAT64 = "FLOAT64"
BIGQUERY_TYPE_INT64 = "INT64"
BIGQUERY_TYPE_INTEGER = "INTEGER"
BIGQUERY_TYPE_NUMERIC = "NUMERIC"
BIGQUERY_TYPE_STRING = "STRING"
BIGQUERY_TYPE_TIME = "TIME"
BIGQUERY_TYPE_TIMESTAMP = "TIMESTAMP"

SNOWFLAKE_TYPE_BINARY = "BINARY"
SNOWFLAKE_TYPE_BOOLEAN = "BOOLEAN"
SNOWFLAKE_TYPE_DATE = "DATE"
SNOWFLAKE_TYPE_FLOAT = "FLOAT"
SNOWFLAKE_TYPE_INTEGER = "INTEGER"
SNOWFLAKE_TYPE_NUMBER = "NUMBER"
SNOWFLAKE_TYPE_TEXT = "TEXT"
SNOWFLAKE_TYPE_TIME = "TIME"
SNOWFLAKE_TYPE_TIMESTAMP_NTZ = "TIMESTAMP_NTZ"
SNOWFLAKE_TYPE_TIMESTAMP_TZ = "TIMESTAMP_TZ"
TEXT_LENGTH_UPPER_LIMIT = 16777216

SYNAPSE_TYPE_BIGINT = "bigint"
SYNAPSE_TYPE_BINARY = "binary"
SYNAPSE_TYPE_BIT = "bit"
SYNAPSE_TYPE_CHAR = "char"
SYNAPSE_TYPE_DATE = "date"
SYNAPSE_TYPE_DATETIME = "datetime"
SYNAPSE_TYPE_DATETIME2 = "datetime2"
SYNAPSE_TYPE_DATETIMEOFFSET = "datetimeoffset"
SYNAPSE_TYPE_DECIMAL = "decimal"
SYNAPSE_TYPE_FLOAT = "float"
SYNAPSE_TYPE_INT = "int"
SYNAPSE_TYPE_MONEY = "money"
SYNAPSE_TYPE_NCHAR = "nchar"
SYNAPSE_TYPE_NUMERIC = "numeric"
SYNAPSE_TYPE_NVARCHAR = "nvarchar"
SYNAPSE_TYPE_REAL = "real"
SYNAPSE_TYPE_SMALLDATETIME = "smalldatetime"
SYNAPSE_TYPE_SMALLINT = "smallint"
SYNAPSE_TYPE_SMALLMONEY = "smallmoney"
SYNAPSE_TYPE_TIME = "time"
SYNAPSE_TYPE_TINYINT = "tinyint"
SYNAPSE_TYPE_UNIQUEIDENTIFIER = "uniqueidentifier"
SYNAPSE_TYPE_VARBINARY = "varbinary"
SYNAPSE_TYPE_VARCHAR = "varchar"
SYNAPSE_TYPE_MAX_TOKEN = "max"

HADOOP_TYPE_BOOLEAN = "BOOLEAN"
HADOOP_TYPE_CHAR = "CHAR"
HADOOP_TYPE_STRING = "STRING"
HADOOP_TYPE_VARCHAR = "VARCHAR"
HADOOP_TYPE_BINARY = "BINARY"
HADOOP_TYPE_TINYINT = "TINYINT"
HADOOP_TYPE_SMALLINT = "SMALLINT"
HADOOP_TYPE_INT = "INT"
HADOOP_TYPE_BIGINT = "BIGINT"
HADOOP_TYPE_DATE = "DATE"
HADOOP_TYPE_DECIMAL = "DECIMAL"
HADOOP_TYPE_FLOAT = "FLOAT"
HADOOP_TYPE_DOUBLE = "DOUBLE"
HADOOP_TYPE_DOUBLE_PRECISION = "DOUBLE_PRECISION"
HADOOP_TYPE_REAL = "REAL"
HADOOP_TYPE_TIMESTAMP = "TIMESTAMP"
HADOOP_TYPE_INTERVAL_DS = "INTERVAL_DAY_TIME"
HADOOP_TYPE_INTERVAL_YM = "INTERVAL_YEAR_MONTH"

PARQUET_TYPE_BINARY = "BINARY"
PARQUET_TYPE_BOOLEAN = "BOOLEAN"
PARQUET_TYPE_DOUBLE = "DOUBLE"
PARQUET_TYPE_FLOAT = "FLOAT"
PARQUET_TYPE_INT32 = "INT32"
PARQUET_TYPE_INT64 = "INT64"
PARQUET_TYPE_STRING = "STRING"

AVRO_TYPE_BOOLEAN = "BOOLEAN"
AVRO_TYPE_BYTES = "BYTES"
AVRO_TYPE_DOUBLE = "DOUBLE"
AVRO_TYPE_FLOAT = "FLOAT"
AVRO_TYPE_INT = "INT"
AVRO_TYPE_LONG = "LONG"
AVRO_TYPE_STRING = "STRING"


class ColumnSpecError(GOEError):
    """Raised for an invalid column specification or a trait that does not apply to a dialect."""


class ColumnDialect(StrEnum):
    """Owner vocabulary of a column data type."""

    CANONICAL = "canonical"
    ORACLE = "oracle"
    MSSQL = "mssql"
    BIGQUERY = "bigquery"
    SNOWFLAKE = "snowflake"
    SYNAPSE = "synapse"
    HADOOP = "hadoop"
    PARQUET = "parquet"
    AVRO = "avro"


class DialectTraits(FrozenBaseStruct, frozen=True, kw_only=True):
    """Type-class membership and rule switches for one dialect."""

    number_types: frozenset[str]
    date_types: frozenset[str]
    string_types: frozenset[str]
    binary_types: frozenset[str]
    interval_types: frozenset[str] = frozenset()
    time_zone_types: frozenset[str] = frozenset()
    time_element_types: frozenset[str]
    nan_types: frozenset[str] = frozenset()
    lowercase_lookups: frozenset[str] = frozenset()
    date_substrings: tuple[str, ...] = ()
    predicate_supported: bool = True
    predicate_excludes_time_zone: bool = True
    predicate_excluded_types: frozenset[str] = frozenset()
    default_char_semantics: str | None = None
    not_applicable: frozenset[str] = frozenset()
    not_applicable_label: str = ""


DIALECT_TRAITS: dict[ColumnDialect, DialectTraits] = {
    ColumnDialect.CANONICAL: DialectTraits(
        number_types=frozenset(NUMERIC_CANONICAL_TYPES),
        date_types=frozenset(DATE_CANONICAL_TYPES),
        string_types=frozenset(STRING_CANONICAL_TYPES),
        binary_types=frozenset({GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY}),
        interval_types=frozenset({GOE_TYPE_INTERVAL_DS, GOE_TYPE_INTERVAL_YM}),
        time_zone_types=frozenset({GOE_TYPE_TIMESTAMP_TZ}),
        time_element_types=frozenset({GOE_TYPE_TIME, GOE_TYPE_TIMESTAMP, GOE_TYPE_TIMESTAMP_TZ}),
        predicate_supported=False,
        not_applicable=frozenset({"format_data_type", "is_nan_capable"}),
        not_applicable_label="CanonicalColumn",
    ),
    ColumnDialect.ORACLE: DialectTraits(
        number_types=frozenset(
            {
                ORACLE_TYPE_NUMBER,
                ORACLE_TYPE_FLOAT,
                ORACLE_TYPE_BINARY_DOUBLE,
                ORACLE_TYPE_BINARY_FLOAT,
            }
        ),
        date_types=frozenset(
            {
                ORACLE_TYPE_DATE,
                ORACLE_TYPE_TIMESTAMP,
                ORACLE_TYPE_TIMESTAMP_TZ,
                ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
            }
        ),
        string_types=frozenset(
            {
                ORACLE_TYPE_VARCHAR,
                ORACLE_TYPE_VARCHAR2,
                ORACLE_TYPE_NVARCHAR2,
                ORACLE_TYPE_CHAR,
                ORACLE_TYPE_NCHAR,
                ORACLE_TYPE_CLOB,
                ORACLE_TYPE_NCLOB,
            }
        ),
        binary_types=frozenset(
            {
                ORACLE_TYPE_BLOB,
                ORACLE_TYPE_RAW,
                ORACLE_TYPE_LONG,
                ORACLE_TYPE_LONG_RAW,
            }
        ),
        interval_types=frozenset({ORACLE_TYPE_INTERVAL_DS, ORACLE_TYPE_INTERVAL_YM}),
        time_zone_types=frozenset({ORACLE_TYPE_TIMESTAMP_TZ, ORACLE_TYPE_TIMESTAMP_LOCAL_TZ}),
        time_element_types=frozenset({ORACLE_TYPE_DATE, ORACLE_TYPE_TIMESTAMP, ORACLE_TYPE_TIMESTAMP_TZ}),
        nan_types=frozenset({ORACLE_TYPE_BINARY_DOUBLE, ORACLE_TYPE_BINARY_FLOAT}),
        predicate_supported=True,
        predicate_excludes_time_zone=True,
        predicate_excluded_types=frozenset({ORACLE_TYPE_CLOB, ORACLE_TYPE_NCLOB}),
    ),
    ColumnDialect.MSSQL: DialectTraits(
        number_types=frozenset(
            {
                MSSQL_TYPE_BIGINT,
                MSSQL_TYPE_BIT,
                MSSQL_TYPE_DECIMAL,
                MSSQL_TYPE_INT,
                MSSQL_TYPE_MONEY,
                MSSQL_TYPE_NUMERIC,
                MSSQL_TYPE_SMALLINT,
                MSSQL_TYPE_SMALLMONEY,
                MSSQL_TYPE_TINYINT,
                MSSQL_TYPE_FLOAT,
                MSSQL_TYPE_REAL,
            }
        ),
        date_types=frozenset(
            {
                MSSQL_TYPE_DATE,
                MSSQL_TYPE_DATETIME2,
                MSSQL_TYPE_DATETIME,
                MSSQL_TYPE_DATETIMEOFFSET,
                MSSQL_TYPE_SMALLDATETIME,
            }
        ),
        string_types=frozenset(
            {
                MSSQL_TYPE_CHAR,
                MSSQL_TYPE_VARCHAR,
                MSSQL_TYPE_NCHAR,
                MSSQL_TYPE_NVARCHAR,
            }
        ),
        binary_types=frozenset({MSSQL_TYPE_BINARY, MSSQL_TYPE_VARBINARY, MSSQL_TYPE_IMAGE}),
        time_zone_types=frozenset({MSSQL_TYPE_DATETIMEOFFSET}),
        time_element_types=frozenset(
            {
                MSSQL_TYPE_DATETIME2,
                MSSQL_TYPE_DATETIME,
                MSSQL_TYPE_SMALLDATETIME,
                MSSQL_TYPE_TIME,
            }
        ),
        lowercase_lookups=frozenset({"number", "binary", "string", "time_zone"}),
        date_substrings=(
            MSSQL_TYPE_DATE,
            MSSQL_TYPE_DATETIME2,
            MSSQL_TYPE_DATETIME,
            MSSQL_TYPE_DATETIMEOFFSET,
            MSSQL_TYPE_SMALLDATETIME,
        ),
        predicate_supported=True,
        predicate_excludes_time_zone=True,
    ),
    ColumnDialect.BIGQUERY: DialectTraits(
        number_types=frozenset(
            {
                BIGQUERY_TYPE_BIGNUMERIC,
                BIGQUERY_TYPE_FLOAT64,
                BIGQUERY_TYPE_INT64,
                BIGQUERY_TYPE_NUMERIC,
            }
        ),
        date_types=frozenset({BIGQUERY_TYPE_DATE, BIGQUERY_TYPE_DATETIME, BIGQUERY_TYPE_TIMESTAMP}),
        string_types=frozenset({BIGQUERY_TYPE_STRING}),
        binary_types=frozenset({BIGQUERY_TYPE_BYTES}),
        time_zone_types=frozenset({BIGQUERY_TYPE_TIMESTAMP}),
        time_element_types=frozenset({BIGQUERY_TYPE_DATETIME, BIGQUERY_TYPE_TIME, BIGQUERY_TYPE_TIMESTAMP}),
        nan_types=frozenset({BIGQUERY_TYPE_FLOAT64}),
        predicate_supported=True,
        predicate_excludes_time_zone=True,
        default_char_semantics=CANONICAL_CHAR_SEMANTICS_CHAR,
    ),
    ColumnDialect.SNOWFLAKE: DialectTraits(
        number_types=frozenset({SNOWFLAKE_TYPE_FLOAT, SNOWFLAKE_TYPE_NUMBER}),
        date_types=frozenset(
            {
                SNOWFLAKE_TYPE_DATE,
                SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
                SNOWFLAKE_TYPE_TIMESTAMP_TZ,
            }
        ),
        string_types=frozenset({SNOWFLAKE_TYPE_TEXT}),
        binary_types=frozenset({SNOWFLAKE_TYPE_BINARY}),
        time_zone_types=frozenset({SNOWFLAKE_TYPE_TIMESTAMP_TZ}),
        time_element_types=frozenset(
            {
                SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
                SNOWFLAKE_TYPE_TIMESTAMP_TZ,
                SNOWFLAKE_TYPE_TIME,
            }
        ),
        nan_types=frozenset({SNOWFLAKE_TYPE_FLOAT}),
        predicate_supported=True,
        predicate_excludes_time_zone=True,
        default_char_semantics=CANONICAL_CHAR_SEMANTICS_CHAR,
    ),
    ColumnDialect.SYNAPSE: DialectTraits(
        number_types=frozenset(
            {
                SYNAPSE_TYPE_BIT,
                SYNAPSE_TYPE_DECIMAL,
                SYNAPSE_TYPE_NUMERIC,
                SYNAPSE_TYPE_INT,
                SYNAPSE_TYPE_BIGINT,
                SYNAPSE_TYPE_SMALLINT,
                SYNAPSE_TYPE_TINYINT,
                SYNAPSE_TYPE_MONEY,
                SYNAPSE_TYPE_SMALLMONEY,
                SYNAPSE_TYPE_FLOAT,
                SYNAPSE_TYPE_REAL,
            }
        ),
        date_types=frozenset(
            {
                SYNAPSE_TYPE_DATE,
                SYNAPSE_TYPE_DATETIME,
                SYNAPSE_TYPE_DATETIME2,
                SYNAPSE_TYPE_DATETIMEOFFSET,
                SYNAPSE_TYPE_SMALLDATETIME,
            }
        ),
        string_types=frozenset(
            {
                SYNAPSE_TYPE_CHAR,
                SYNAPSE_TYPE_VARCHAR,
                SYNAPSE_TYPE_NCHAR,
                SYNAPSE_TYPE_NVARCHAR,
            }
        ),
        binary_types=frozenset({SYNAPSE_TYPE_BINARY, SYNAPSE_TYPE_VARBINARY}),
        time_zone_types=frozenset({SYNAPSE_TYPE_DATETIMEOFFSET}),
        time_element_types=frozenset(
            {
                SYNAPSE_TYPE_DATETIME,
                SYNAPSE_TYPE_DATETIME2,
                SYNAPSE_TYPE_DATETIMEOFFSET,
                SYNAPSE_TYPE_SMALLDATETIME,
                SYNAPSE_TYPE_TIME,
            }
        ),
        predicate_supported=True,
        predicate_excludes_time_zone=True,
    ),
    ColumnDialect.HADOOP: DialectTraits(
        number_types=frozenset(
            {
                HADOOP_TYPE_BIGINT,
                HADOOP_TYPE_DECIMAL,
                HADOOP_TYPE_DOUBLE,
                HADOOP_TYPE_FLOAT,
                HADOOP_TYPE_INT,
                HADOOP_TYPE_REAL,
                HADOOP_TYPE_SMALLINT,
                HADOOP_TYPE_TINYINT,
            }
        ),
        date_types=frozenset({HADOOP_TYPE_TIMESTAMP, HADOOP_TYPE_DATE}),
        string_types=frozenset({HADOOP_TYPE_CHAR, HADOOP_TYPE_VARCHAR, HADOOP_TYPE_STRING}),
        binary_types=frozenset({HADOOP_TYPE_BINARY}),
        time_element_types=frozenset({HADOOP_TYPE_TIMESTAMP}),
        nan_types=frozenset({HADOOP_TYPE_DOUBLE, HADOOP_TYPE_FLOAT}),
        predicate_supported=True,
        predicate_excludes_time_zone=False,
        default_char_semantics=CANONICAL_CHAR_SEMANTICS_BYTE,
    ),
    ColumnDialect.PARQUET: DialectTraits(
        number_types=frozenset(
            {
                PARQUET_TYPE_DOUBLE,
                PARQUET_TYPE_FLOAT,
                PARQUET_TYPE_INT32,
                PARQUET_TYPE_INT64,
            }
        ),
        date_types=frozenset(),
        string_types=frozenset({PARQUET_TYPE_STRING}),
        binary_types=frozenset({PARQUET_TYPE_BINARY}),
        time_element_types=frozenset(),
        predicate_supported=False,
        not_applicable=frozenset({"has_time_element", "is_nan_capable"}),
        not_applicable_label="StagingParquetColumn",
    ),
    ColumnDialect.AVRO: DialectTraits(
        number_types=frozenset(
            {
                AVRO_TYPE_DOUBLE,
                AVRO_TYPE_FLOAT,
                AVRO_TYPE_INT,
                AVRO_TYPE_LONG,
            }
        ),
        date_types=frozenset(),
        string_types=frozenset({AVRO_TYPE_STRING}),
        binary_types=frozenset({AVRO_TYPE_BYTES}),
        time_element_types=frozenset(),
        predicate_supported=False,
        not_applicable=frozenset({"has_time_element", "is_nan_capable"}),
        not_applicable_label="StagingAvroColumn",
    ),
}


class ColumnPartitionSpec(FrozenBaseStruct, frozen=True):
    """Partition attributes of one column (replaces ColumnPartitionInfo)."""

    position: int
    source_column_name: str | None = None
    granularity: str | int | None = None
    digits: int | None = None
    range_start: int | None = None
    range_end: int | None = None
    function: str | None = None

    def __post_init__(self) -> None:
        """Validate mandatory position attribute."""
        if self.position is None:
            raise ColumnSpecError("ColumnPartitionSpec.position cannot be None")

    def synthetic_name(
        self,
        full_column_list: Sequence["ColumnSpec"],
        source_column_name_override: str | None = None,
        position_override: int | None = None,
    ) -> str:
        """Return the GOE_PART_* synthetic column name."""
        assert full_column_list
        assert valid_column_list(full_column_list), invalid_column_list_message(full_column_list)
        assert self.source_column_name
        source_column = match_table_column(self.source_column_name, full_column_list)
        if self.function:
            position = position_override if position_override is not None else self.position
            synth_desc = "U" + str(position)
        elif source_column and source_column.is_number_based() and self.digits:
            assert self.granularity is not None
            synth_desc = ("{:0%sd}" % self.digits).format(int(self.granularity))
        else:
            synth_desc = str(self.granularity)
        return (
            SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE
            % (synth_desc, source_column_name_override or self.source_column_name)
        ).upper()


class ColumnSpec(FrozenBaseStruct, frozen=True):
    """Immutable description of one column in one dialect."""

    dialect: ColumnDialect
    name: str
    data_type: str
    data_length: int | None = None
    data_precision: int | None = None
    data_scale: int | None = None
    nullable: bool | None = None
    data_default: str | None = None
    safe_mapping: bool | None = True
    partition_info: ColumnPartitionSpec | None = None
    char_length: int | None = None
    char_semantics: str | None = None
    staging_file_column_name: str | None = None
    from_override: bool = False
    hidden: bool | None = None
    collation: str | None = None

    def __post_init__(self) -> None:
        """Validate and normalize column attributes across dialects."""
        if not isinstance(self.dialect, ColumnDialect):
            msgspec.structs.force_setattr(self, "dialect", ColumnDialect(self.dialect))
        if not self.name or not isinstance(self.name, str):
            raise ColumnSpecError(f"Invalid column name: {self.name!r}")
        if not self.data_type or not isinstance(self.data_type, str):
            raise ColumnSpecError(f"Invalid column data_type: {self.data_type!r}")

        for int_attr in ("data_length", "data_precision", "data_scale", "char_length"):
            val = getattr(self, int_attr)
            if val and (not isinstance(val, int) or isinstance(val, bool)):
                raise ColumnSpecError(f"{type(val)} is not int for {int_attr}")

        if self.partition_info is not None and not isinstance(self.partition_info, ColumnPartitionSpec):
            raise ColumnSpecError(f"Invalid partition_info: {self.partition_info!r}")

        for bool_attr in ("nullable", "safe_mapping", "hidden"):
            raw_bool = getattr(self, bool_attr)
            if raw_bool is not None:
                if isinstance(raw_bool, str):
                    upper_bool = raw_bool.upper()
                    if upper_bool in ("Y", "YES", "TRUE"):
                        msgspec.structs.force_setattr(self, bool_attr, True)
                    elif upper_bool in ("N", "NO", "FALSE"):
                        msgspec.structs.force_setattr(self, bool_attr, False)
                    else:
                        raise ColumnSpecError(f"Invalid boolean value: {raw_bool}")
                elif not isinstance(raw_bool, bool):
                    raise ColumnSpecError(f"Invalid boolean value: {raw_bool!r}")

        if self.char_semantics is not None:
            if not isinstance(self.char_semantics, str):
                raise ColumnSpecError(f"Invalid char_semantics: {self.char_semantics!r}")
            upper_semantics = self.char_semantics.upper()
            if upper_semantics not in (
                CANONICAL_CHAR_SEMANTICS_BYTE,
                CANONICAL_CHAR_SEMANTICS_CHAR,
                CANONICAL_CHAR_SEMANTICS_UNICODE,
            ):
                raise ColumnSpecError(f"Invalid char_semantics: {self.char_semantics}")
            if upper_semantics != self.char_semantics:
                msgspec.structs.force_setattr(self, "char_semantics", upper_semantics)

        traits = DIALECT_TRAITS[self.dialect]
        if self.char_semantics is None and traits.default_char_semantics is not None:
            msgspec.structs.force_setattr(self, "char_semantics", traits.default_char_semantics)

        if self.dialect is ColumnDialect.CANONICAL:
            if self.data_length is None and self.data_type in CANONICAL_TYPE_BYTE_LENGTHS:
                msgspec.structs.force_setattr(self, "data_length", CANONICAL_TYPE_BYTE_LENGTHS[self.data_type])
        elif self.dialect is ColumnDialect.ORACLE:
            if ORACLE_TIMESTAMP_RE.match(self.data_type):
                msgspec.structs.force_setattr(self, "data_type", ORACLE_TYPE_TIMESTAMP)
            elif ORACLE_TIMESTAMP_TZ_RE.match(self.data_type):
                msgspec.structs.force_setattr(self, "data_type", ORACLE_TYPE_TIMESTAMP_TZ)
            elif ORACLE_TIMESTAMP_LOCAL_TZ_RE.match(self.data_type):
                msgspec.structs.force_setattr(self, "data_type", ORACLE_TYPE_TIMESTAMP_LOCAL_TZ)
            elif ORACLE_INTERVAL_DS_RE.match(self.data_type):
                msgspec.structs.force_setattr(self, "data_type", ORACLE_TYPE_INTERVAL_DS)
            elif ORACLE_INTERVAL_YM_RE.match(self.data_type):
                msgspec.structs.force_setattr(self, "data_type", ORACLE_TYPE_INTERVAL_YM)
            if self.char_semantics is None and self.data_type in (
                ORACLE_TYPE_NCHAR,
                ORACLE_TYPE_NCLOB,
                ORACLE_TYPE_NVARCHAR2,
            ):
                msgspec.structs.force_setattr(self, "char_semantics", CANONICAL_CHAR_SEMANTICS_UNICODE)
        elif self.dialect is ColumnDialect.BIGQUERY:
            if self.data_length and self.char_length is None:
                msgspec.structs.force_setattr(self, "char_length", self.data_length)
            if self.data_type == BIGQUERY_TYPE_FLOAT:
                msgspec.structs.force_setattr(self, "data_type", BIGQUERY_TYPE_FLOAT64)
            elif self.data_type == BIGQUERY_TYPE_INTEGER:
                msgspec.structs.force_setattr(self, "data_type", BIGQUERY_TYPE_INT64)
        elif self.dialect is ColumnDialect.SNOWFLAKE:
            if self.data_length and self.char_length is None:
                msgspec.structs.force_setattr(self, "char_length", self.data_length)

    def format_data_type(self) -> str:
        """Format a SQL data type specification from the column attributes."""
        self._not_applicable("format_data_type")
        match self.dialect:
            case ColumnDialect.ORACLE:
                return self._format_oracle()
            case ColumnDialect.MSSQL:
                return self._format_mssql()
            case ColumnDialect.BIGQUERY:
                return self._format_bigquery()
            case ColumnDialect.SNOWFLAKE:
                return self._format_snowflake()
            case ColumnDialect.SYNAPSE:
                return self._format_synapse()
            case ColumnDialect.HADOOP:
                return self._format_hadoop()
            case ColumnDialect.PARQUET | ColumnDialect.AVRO:
                return self.data_type
            case _:
                raise ColumnSpecError(f"Unsupported dialect for format_data_type: {self.dialect}")

    def has_time_element(self) -> bool:
        """Return True if the column data type contains a time component."""
        self._not_applicable("has_time_element")
        return self._lookup_type("time_element") in self._traits.time_element_types

    def is_binary(self) -> bool:
        """Return True if the column holds binary data."""
        return self._lookup_type("binary") in self._traits.binary_types

    def is_nan_capable(self) -> bool:
        """Return True if the column is capable of holding IEEE NaN values."""
        self._not_applicable("is_nan_capable")
        return self._lookup_type("nan") in self._traits.nan_types

    def is_number_based(self) -> bool:
        """Return True if the column is numeric in class."""
        return self._lookup_type("number") in self._traits.number_types

    def is_date_based(self) -> bool:
        """Return True if the column is date or timestamp based."""
        traits = self._traits
        if traits.date_substrings:
            return any(token in self.data_type for token in traits.date_substrings)
        return self._lookup_type("date") in traits.date_types

    def is_interval(self) -> bool:
        """Return True if the column is of an interval type."""
        return self._lookup_type("interval") in self._traits.interval_types

    def is_string_based(self) -> bool:
        """Return True if the column is character string based."""
        return self._lookup_type("string") in self._traits.string_types

    def is_time_zone_based(self) -> bool:
        """Return True if the column contains time zone data."""
        key = self.data_type.upper() if self.dialect is ColumnDialect.ORACLE else self._lookup_type("time_zone")
        return key in self._traits.time_zone_types

    def valid_for_offload_predicate(self) -> bool:
        """Return True if the column can be used in an offload predicate."""
        traits = self._traits
        if not traits.predicate_supported:
            return False
        date_ok = self.is_date_based() and (not traits.predicate_excludes_time_zone or not self.is_time_zone_based())
        string_ok = self.is_string_based() and self.data_type not in traits.predicate_excluded_types
        return bool(self.is_number_based() or date_ok or string_ok)

    def is_nullable(self) -> bool | None:
        """Return the column nullability flag."""
        return self.nullable

    def is_unbound_string(self) -> bool:
        """Return True if the column is string-based and has no bounded user length."""
        if (
            self.dialect is ColumnDialect.SNOWFLAKE
            and self.data_type == SNOWFLAKE_TYPE_TEXT
            and self.data_length == TEXT_LENGTH_UPPER_LIMIT
        ):
            return True
        return bool(self.is_string_based() and self.data_length is None and self.char_length is None)

    def is_hidden(self) -> bool | None:
        """Return the column hidden indicator."""
        return self.hidden

    def replace(self, **changes: Any) -> "ColumnSpec":
        """Return a copy of the column specification with updated field values."""
        return msgspec.structs.replace(self, **changes)

    def with_simplified_staging_column_name(self, column_position: int) -> "ColumnSpec":
        """Return a copy with staging_file_column_name simplified when special characters are present."""
        if any(ch in self.name for ch in STAGING_FILE_UNSUPPORTED_NAME_CHARACTERS):
            staging_name = f"{STAGING_FILE_SIMPLIFIED_NAME_TOKEN}_{column_position}"
        else:
            staging_name = self.name
        return self.replace(staging_file_column_name=staging_name)

    @property
    def _traits(self) -> DialectTraits:
        return DIALECT_TRAITS[self.dialect]

    def _lookup_type(self, trait: str) -> str:
        if trait in self._traits.lowercase_lookups:
            return self.data_type.lower()
        return self.data_type

    def _not_applicable(self, method: str) -> None:
        traits = self._traits
        if method in traits.not_applicable:
            raise ColumnSpecError(f"{method}() is not applicable to a {traits.not_applicable_label}")

    def _format_oracle(self) -> str:
        if self.data_type in (ORACLE_TYPE_NUMBER, ORACLE_TYPE_FLOAT):
            if self.data_precision and self.data_scale is not None:
                return f"{self.data_type}({self.data_precision},{self.data_scale})"
            if self.data_precision:
                return f"{self.data_type}({self.data_precision})"
            if self.data_scale is not None:
                return f"{self.data_type}(*,{self.data_scale})"
            return self.data_type
        if self.data_type in (ORACLE_TYPE_CHAR, ORACLE_TYPE_VARCHAR2):
            if self.char_length:
                semantic = "CHAR" if self.char_semantics == CANONICAL_CHAR_SEMANTICS_CHAR else "BYTE"
                return f"{self.data_type}({self.char_length} {semantic})"
            return f"{self.data_type}({self.data_length} BYTE)"
        if self.data_type in (ORACLE_TYPE_NCHAR, ORACLE_TYPE_NVARCHAR2):
            return f"{self.data_type}({self.char_length})"
        if self.data_type == ORACLE_TYPE_TIMESTAMP:
            return ORACLE_TIMESTAMP_SUB_PATTERN % (6 if self.data_scale is None else self.data_scale)
        if self.data_type == ORACLE_TYPE_TIMESTAMP_TZ:
            return ORACLE_TIMESTAMP_TZ_SUB_PATTERN % (6 if self.data_scale is None else self.data_scale)
        if self.data_type == ORACLE_TYPE_TIMESTAMP_LOCAL_TZ:
            return ORACLE_TIMESTAMP_LOCAL_TZ_SUB_PATTERN % (6 if self.data_scale is None else self.data_scale)
        if self.data_type == ORACLE_TYPE_RAW and self.data_length:
            return f"{self.data_type}({self.data_length})"
        if self.data_type == ORACLE_TYPE_INTERVAL_DS:
            return ORACLE_INTERVAL_DS_SUB_PATTERN % (
                9 if self.data_precision is None else self.data_precision,
                9 if self.data_scale is None else self.data_scale,
            )
        if self.data_type == ORACLE_TYPE_INTERVAL_YM:
            return ORACLE_INTERVAL_YM_SUB_PATTERN % (9 if self.data_precision is None else self.data_precision)
        return self.data_type

    def _format_mssql(self) -> str:
        if self.data_type in (MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC):
            if self.data_precision and self.data_scale is not None:
                return f"{self.data_type}({self.data_precision},{self.data_scale})"
            if self.data_precision:
                return f"{self.data_type}({self.data_precision})"
            return self.data_type
        if self.data_type in (
            MSSQL_TYPE_CHAR,
            MSSQL_TYPE_VARCHAR,
            MSSQL_TYPE_NCHAR,
            MSSQL_TYPE_NVARCHAR,
        ):
            return f"{self.data_type}({self.data_length})"
        return self.data_type

    def _format_bigquery(self) -> str:
        if self.data_type in (BIGQUERY_TYPE_BIGNUMERIC, BIGQUERY_TYPE_NUMERIC):
            if self.data_precision and self.data_scale is not None:
                return f"{self.data_type}({self.data_precision},{self.data_scale})"
            if self.data_precision:
                return f"{self.data_type}({self.data_precision})"
            return self.data_type
        if self.data_type == BIGQUERY_TYPE_STRING:
            if self.char_length:
                return f"{self.data_type}({self.char_length})"
            return self.data_type
        if self.data_type == BIGQUERY_TYPE_BYTES:
            if self.data_length:
                return f"{self.data_type}({self.data_length})"
            return self.data_type
        return self.data_type

    def _format_snowflake(self) -> str:
        if self.data_type == SNOWFLAKE_TYPE_NUMBER:
            if self.data_precision and self.data_scale is not None:
                return f"{self.data_type}({self.data_precision},{self.data_scale})"
            if self.data_precision:
                return f"{self.data_type}({self.data_precision})"
            return self.data_type
        if self.data_type == SNOWFLAKE_TYPE_TEXT:
            if self.char_length:
                return f"{self.data_type}({self.char_length})"
            return self.data_type
        if self.data_type == SNOWFLAKE_TYPE_BINARY:
            if self.data_length:
                return f"{self.data_type}({self.data_length})"
            return self.data_type
        if (self.is_date_based() or self.data_type == SNOWFLAKE_TYPE_TIME) and self.data_scale is not None:
            return f"{self.data_type}({self.data_scale})"
        return self.data_type

    def _format_synapse(self) -> str:
        if self.data_type in (SYNAPSE_TYPE_DECIMAL, SYNAPSE_TYPE_NUMERIC):
            if self.data_precision and self.data_scale is not None:
                return f"{self.data_type}({self.data_precision},{self.data_scale})"
            if self.data_precision:
                return f"{self.data_type}({self.data_precision})"
            return self.data_type
        if self.data_type in (
            SYNAPSE_TYPE_CHAR,
            SYNAPSE_TYPE_VARCHAR,
            SYNAPSE_TYPE_BINARY,
            SYNAPSE_TYPE_VARBINARY,
            SYNAPSE_TYPE_NCHAR,
            SYNAPSE_TYPE_NVARCHAR,
        ):
            if (
                self.data_type in (SYNAPSE_TYPE_VARCHAR, SYNAPSE_TYPE_VARBINARY, SYNAPSE_TYPE_NVARCHAR)
                and not self.data_length
            ):
                return f"{self.data_type}({SYNAPSE_TYPE_MAX_TOKEN})"
            if self.char_length and self.char_semantics in (
                CANONICAL_CHAR_SEMANTICS_CHAR,
                CANONICAL_CHAR_SEMANTICS_UNICODE,
            ):
                return f"{self.data_type}({self.char_length})"
            if self.data_length:
                return f"{self.data_type}({self.data_length})"
            return self.data_type
        if (self.is_date_based() or self.data_type == SYNAPSE_TYPE_TIME) and self.data_scale is not None:
            return f"{self.data_type}({self.data_scale})"
        return self.data_type

    def _format_hadoop(self) -> str:
        if self.data_type == HADOOP_TYPE_DECIMAL:
            if self.data_precision and self.data_scale is not None:
                return f"{self.data_type}({self.data_precision},{self.data_scale})"
            if self.data_precision:
                return f"{self.data_type}({self.data_precision})"
            return self.data_type
        if self.data_type in (HADOOP_TYPE_VARCHAR, HADOOP_TYPE_CHAR):
            return f"{self.data_type}({self.data_length})"
        return self.data_type


def get_column_names(
    column_list: Sequence[ColumnSpec] | None,
    conv_fn: Callable[[str], str] | None = None,
) -> list[str]:
    """Return column names from a sequence of ColumnSpec objects, optionally transformed by conv_fn."""
    if conv_fn:
        return [conv_fn(col.name) for col in column_list or ()]
    return [col.name for col in column_list or ()]


def get_partition_columns(column_list: Sequence[ColumnSpec] | None) -> list[ColumnSpec]:
    """Return columns with partition_info sorted by partition_info.position."""
    if not column_list:
        return []
    part_cols = [col for col in column_list if col.partition_info is not None]
    return sorted(part_cols, key=lambda col: col.partition_info.position if col.partition_info else 0)


def get_partition_source_column_names(
    column_list: Sequence[ColumnSpec] | None,
    conv_fn: Callable[[str], str] | None = None,
) -> list[str | None]:
    """Return source column names from partition columns in position order."""
    columns = get_partition_columns(column_list)
    if conv_fn:
        return [
            conv_fn(col.partition_info.source_column_name)
            if col.partition_info and col.partition_info.source_column_name is not None
            else None
            for col in columns
        ]
    return [col.partition_info.source_column_name if col.partition_info else None for col in columns]


def is_safe_mapping(prior_safe_mapping: Any, new_safe_mapping: Any = None) -> bool:
    """Ensure an unsafe mapping is never overwritten by a safe one."""
    if new_safe_mapping is None:
        return bool(prior_safe_mapping)
    if not new_safe_mapping:
        return bool(new_safe_mapping)
    if new_safe_mapping and prior_safe_mapping is None:
        return bool(new_safe_mapping)
    return bool(prior_safe_mapping)


def match_partition_column_by_source(
    source_column_name: str,
    column_list: Sequence[ColumnSpec],
) -> ColumnSpec | None:
    """Find and return a partition column with a matching source_column_name (case-insensitive)."""
    assert source_column_name
    assert isinstance(column_list, (list, tuple))
    if column_list:
        assert isinstance(column_list[0], ColumnSpec)
    for col in column_list:
        if (
            col.partition_info
            and col.partition_info.source_column_name
            and col.partition_info.source_column_name.lower() == source_column_name.lower()
        ):
            return col
    return None


def match_table_column(search_name: str, column_list: Sequence[ColumnSpec]) -> ColumnSpec | None:
    """Find and return a column matching search_name (case-insensitive)."""
    assert search_name
    assert isinstance(column_list, (list, tuple))
    if column_list:
        assert isinstance(column_list[0], ColumnSpec)
    target = search_name.lower()
    for col in column_list:
        if col.name.lower() == target:
            return col
    return None


def match_table_column_position(search_name: str, column_list: Sequence[ColumnSpec]) -> int | None:
    """Find and return the 0-based position of a column matching search_name (case-insensitive)."""
    assert search_name
    assert isinstance(column_list, (list, tuple))
    if column_list:
        assert isinstance(column_list[0], ColumnSpec)
    target = search_name.lower()
    for idx, col in enumerate(column_list):
        if col.name.lower() == target:
            return idx
    return None


def valid_column_list(column_list: Any) -> bool:
    """Return True if column_list is a valid list or tuple of ColumnSpec instances."""
    return not invalid_column_list_message(column_list)


def invalid_column_list_message(column_list: Any) -> str | None:
    """Return an error message if column_list is not a valid list/tuple of ColumnSpec instances, else None."""
    if not isinstance(column_list, (list, tuple)):
        return f"Type {type(column_list)} is not list"
    if not column_list:
        return None
    if isinstance(column_list[0], ColumnSpec):
        return None
    return f"Type {type(column_list[0])} is not instance of column"


def is_synthetic_partition_column(column: ColumnSpec | str) -> bool:
    """Return True if column (or column name) matches the GOE synthetic partition naming pattern."""
    assert column
    column_name = column.name if isinstance(column, ColumnSpec) else column
    return bool(SYNTHETIC_PARTITION_COLUMN_NAME_RE.search(column_name))


def regex_real_column_from_part_column(synthetic_part_col: str) -> re.Match[str] | None:
    """Match a synthetic partition column name and extract its components."""
    assert synthetic_part_col
    return SYNTHETIC_PARTITION_COLUMN_NAME_RE.search(synthetic_part_col.upper())


def str_list_of_columns(column_list: Sequence[ColumnSpec] | None, with_cr: bool = True) -> str | list[str]:
    """Format a sequence of columns as strings, joined by newlines when with_cr is True."""
    if with_cr:
        return "\n".join(str(col) for col in column_list or ())
    return [str(col) for col in column_list or ()]
