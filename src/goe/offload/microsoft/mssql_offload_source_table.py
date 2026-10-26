# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""MSSQLSourceTable: Library for logic/interaction with MSSQL source of an offload."""

import logging
from typing import Any

from goe.offload.column_metadata import (
    ALL_CANONICAL_TYPES,
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
    GOE_TYPE_LARGE_BINARY,
    GOE_TYPE_LARGE_STRING,
    GOE_TYPE_TIME,
    GOE_TYPE_TIMESTAMP,
    GOE_TYPE_TIMESTAMP_TZ,
    GOE_TYPE_VARIABLE_STRING,
    NUMERIC_CANONICAL_TYPES,
    STRING_CANONICAL_TYPES,
    CanonicalColumn,
    is_safe_mapping,
)
from goe.offload.frontend_api import QueryParameter
from goe.offload.microsoft.mssql_column import (
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
    MSSQLColumn,
)
from goe.offload.offload_source_table import OffloadSourceTableInterface
from goe.offload.predicate_offload import (
    get_predicate_dialect_engine,
    resolve_predicate_types,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class MSSQLSourceTable(OffloadSourceTableInterface):
    """Microsoft SQL Server source table details and methods."""

    def __init__(
        self,
        schema_name: str,
        table_name: str,
        connection_options: Any,
        messages: Any,
        dry_run: bool = False,
        do_not_connect: bool = False,
        db_api: Any = None,
    ) -> None:
        """Construct MSSQLSourceTable and hydrate metadata from FrontendCatalogCache when connected."""
        assert schema_name and table_name and connection_options
        assert hasattr(connection_options, "rdbms_app_user")
        assert hasattr(connection_options, "rdbms_app_pass")
        assert hasattr(connection_options, "rdbms_dsn")

        super().__init__(
            schema_name,
            table_name,
            connection_options,
            messages,
            dry_run=dry_run,
            do_not_connect=do_not_connect,
            db_api=db_api,
        )

        logger.info(
            "MSSQLSourceTable setup: (%s, %s, %s)",
            schema_name,
            table_name,
            connection_options.rdbms_app_user,
        )
        if dry_run:
            logger.info("* Dry run *")

        self._iot_type = None
        self._partitioned: str | None = None
        self._partition_type = None
        self._subpartition_type = None
        self._partitions = None
        self._dependencies = None
        self._parallelism = None

        if not do_not_connect:
            self._hydrate_from_snapshot()

    @property
    def partition_type(self) -> Any:
        return self._partition_type

    @property
    def offload_by_subpartition(self) -> bool:
        return False

    @property
    def offload_partition_level(self) -> int | None:
        return None

    @property
    def parallelism(self) -> Any:
        return self._parallelism

    def decode_partition_high_values(self, hv_csv: object, strict: bool = True) -> tuple[object, ...]:
        raise NotImplementedError("MSSQL decode_partition_high_values not implemented.")

    def enable_offload_by_subpartition(self, desired_state: bool = True) -> None:
        raise NotImplementedError("MSSQL enable_offload_by_subpartition() not implemented.")

    def get_hash_bucket_candidate(self) -> str | None:
        return self._hash_bucket_candidate

    def get_partitions(self, strict: bool = True, populate_hvs: bool = True) -> Any:
        """Fetch list of partitions for table on demand."""
        if not self._partitions and self.is_partitioned():
            raise NotImplementedError("MSSQL get_partitions not implemented.")
        return self._partitions

    def get_session_option(self, option_name: str) -> Any:
        raise NotImplementedError("MSSQL get_session_option not implemented.")

    def get_max_partition_size(self) -> int | None:
        """Return the size of the largest partition."""
        if self.is_partitioned():
            raise NotImplementedError("MSSQL get_max_partition_size not implemented.")
        return None

    def is_iot(self) -> bool:
        return self._iot_type == "IOT"

    def is_partitioned(self) -> bool:
        return self._partitioned == "YES"

    def is_subpartitioned(self) -> bool:
        return False

    @staticmethod
    def supported_data_types() -> set[str]:
        return {
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
            MSSQL_TYPE_DATE,
            MSSQL_TYPE_DATETIME2,
            MSSQL_TYPE_DATETIME,
            MSSQL_TYPE_DATETIMEOFFSET,
            MSSQL_TYPE_SMALLDATETIME,
            MSSQL_TYPE_TIME,
            MSSQL_TYPE_CHAR,
            MSSQL_TYPE_VARCHAR,
            MSSQL_TYPE_NCHAR,
            MSSQL_TYPE_NVARCHAR,
            MSSQL_TYPE_UNIQUEIDENTIFIER,
        }

    def check_nanosecond_offload_allowed(
        self,
        backend_max_datetime_scale: Any,
        allow_nanosecond_timestamp_columns: Any = None,
    ) -> bool:
        raise NotImplementedError("MSSQL check_nanosecond_offload_allowed() not implemented.")

    def supported_range_partition_data_type(self, rdbms_data_type: str) -> bool:
        raise NotImplementedError("MSSQL supported_range_partition_data_type() not implemented.")

    def supported_list_partition_data_type(self, rdbms_data_type: str) -> bool:
        raise NotImplementedError("MSSQL supported_list_partition_data_type() not implemented.")

    @staticmethod
    def hash_bucket_unsuitable_data_types() -> set[str]:
        return set()

    @staticmethod
    def nan_capable_data_types() -> set[str]:
        return set()

    @staticmethod
    def datetime_literal_to_python(rdbms_literal: Any, strict: bool = True) -> Any:
        raise NotImplementedError("MSSQL datetime_literal_to_python() not implemented.")

    @staticmethod
    def numeric_literal_to_python(rdbms_literal: Any) -> Any:
        raise NotImplementedError("MSSQL numeric_literal_to_python() not implemented.")

    def rdbms_literal_to_python(
        self,
        rdbms_column: Any,
        rdbms_literal: Any,
        partition_type: Any,
        strict: bool = True,
    ) -> Any:
        raise NotImplementedError("MSSQL rdbms_literal_to_python() not implemented.")

    def get_minimum_partition_key_data(self) -> list[Any]:
        """Return lowest point of data stored in source MSSQL table."""
        assert self.partition_columns
        return []

    def to_rdbms_literal_with_sql_conv_fn(self, py_val: Any, rdbms_data_type: str) -> tuple[Any, Any]:
        raise NotImplementedError("MSSQL to_rdbms_literal_with_sql_conv_fn() not implemented.")

    def get_suitable_sample_size(self, bytes_override: object = None) -> int:
        return 0

    def sample_rdbms_data_types(
        self,
        columns_to_sample: Any,
        data_sample_pct: Any,
        data_sample_parallelism: Any,
        backend_min_possible_date: Any,
        backend_max_decimal_integral_magnitude: Any,
        backend_max_decimal_scale: Any,
        allow_decimal_scale_rounding: Any,
    ) -> list[Any]:
        return []

    def supported_partition_data_types(self) -> list[str]:
        raise NotImplementedError("MSSQL supported_partition_data_types() not implemented.")

    def offload_by_subpartition_capable(self, valid_for_auto_enable: bool = False) -> bool:
        return False

    def partition_has_rows(self, partition_name: str) -> bool:
        raise NotImplementedError("MSSQL partition_has_rows() not implemented.")

    def predicate_has_rows(self, predicate: Any) -> bool:
        where_clause, query_params = self.predicate_to_where_clause_with_binds(predicate)
        self._debug(f"Converted predicate: {where_clause}")
        sql = f"SELECT TOP 1 1 FROM [{self.owner}].[{self.table_name}] WHERE ({where_clause})"
        row = self._db_api.execute_query_fetch_one(sql, query_params=query_params)
        return bool(row)

    def predicate_to_where_clause(self, predicate: Any, columns_override: Any = None) -> str | None:
        if not predicate:
            return None
        target_columns = list(columns_override or self.columns)
        resolved = resolve_predicate_types(predicate.ast, target_columns, include_synthetic=False)
        return get_predicate_dialect_engine("tsql").render_literal_sql(resolved, target_columns)

    def predicate_to_where_clause_with_binds(self, predicate: Any) -> tuple[str, list[QueryParameter]]:
        target_columns = list(self.columns)
        resolved = resolve_predicate_types(predicate.ast, target_columns, include_synthetic=False)
        rendered = get_predicate_dialect_engine("tsql").render_bind_sql(resolved, target_columns)
        query_params = [QueryParameter(param_name=k, param_value=v) for k, v in rendered.params.items()]
        return rendered.sql, query_params

    def valid_canonical_override(self, column: MSSQLColumn, canonical_override: CanonicalColumn | str) -> bool:
        """Return True when canonical_override is a supported target type for column."""
        assert isinstance(column, MSSQLColumn)
        if isinstance(canonical_override, CanonicalColumn):
            target_type = canonical_override.data_type
        else:
            target_type = canonical_override
        if column.data_type == MSSQL_TYPE_BIT:
            return bool(target_type == GOE_TYPE_BOOLEAN)
        if column.data_type in [MSSQL_TYPE_CHAR, MSSQL_TYPE_NCHAR]:
            return bool(target_type == GOE_TYPE_FIXED_STRING)
        if column.data_type in [MSSQL_TYPE_TEXT, MSSQL_TYPE_NTEXT]:
            return bool(target_type == GOE_TYPE_LARGE_STRING)
        if column.data_type in [
            MSSQL_TYPE_VARCHAR,
            MSSQL_TYPE_NVARCHAR,
            MSSQL_TYPE_UNIQUEIDENTIFIER,
        ]:
            return bool(target_type == GOE_TYPE_VARIABLE_STRING)
        if column.data_type in [
            MSSQL_TYPE_BINARY,
            MSSQL_TYPE_VARBINARY,
            MSSQL_TYPE_IMAGE,
        ]:
            return bool(target_type in [GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY])
        if column.data_type == MSSQL_TYPE_FLOAT:
            return bool(target_type == GOE_TYPE_DOUBLE)
        if column.data_type == MSSQL_TYPE_REAL:
            return bool(target_type == GOE_TYPE_FLOAT)
        if column.is_number_based():
            return target_type in NUMERIC_CANONICAL_TYPES
        if column.is_date_based() and column.is_time_zone_based():
            return bool(target_type == GOE_TYPE_TIMESTAMP_TZ)
        if column.is_date_based():
            return bool(target_type in [GOE_TYPE_DATE, GOE_TYPE_TIMESTAMP] or target_type in STRING_CANONICAL_TYPES)
        if column.data_type == MSSQL_TYPE_TIME:
            return bool(target_type == GOE_TYPE_TIME)
        if target_type not in ALL_CANONICAL_TYPES:
            return False
        return False

    def to_canonical_column(self, column: MSSQLColumn) -> CanonicalColumn:
        """Translate an MSSQL column to an internal GOE CanonicalColumn."""

        def new_column(
            col: MSSQLColumn,
            data_type: str,
            data_length: int | None = None,
            data_precision: int | None = None,
            data_scale: int | None = None,
            safe_mapping: bool | None = None,
        ) -> CanonicalColumn:
            """Construct a CanonicalColumn preserving source column nullability and defaults."""
            resolved_safe = is_safe_mapping(col.safe_mapping, safe_mapping)
            return CanonicalColumn(
                col.name,
                data_type,
                data_length=data_length,
                data_precision=data_precision,
                data_scale=data_scale,
                nullable=col.nullable,
                data_default=col.data_default,
                safe_mapping=resolved_safe,
                partition_info=None,
            )

        assert column
        assert isinstance(column, MSSQLColumn)

        if column.data_type == MSSQL_TYPE_BIT:
            return new_column(column, GOE_TYPE_BOOLEAN)
        if column.data_type in (MSSQL_TYPE_CHAR, MSSQL_TYPE_NCHAR):
            return new_column(
                column,
                GOE_TYPE_FIXED_STRING,
                data_length=column.data_length,
                safe_mapping=True,
            )
        if column.data_type in (MSSQL_TYPE_TEXT, MSSQL_TYPE_NTEXT):
            return new_column(column, GOE_TYPE_LARGE_STRING)
        if column.data_type in (
            MSSQL_TYPE_VARCHAR,
            MSSQL_TYPE_NVARCHAR,
            MSSQL_TYPE_UNIQUEIDENTIFIER,
        ):
            return new_column(column, GOE_TYPE_VARIABLE_STRING, data_length=column.data_length)
        if column.data_type in (
            MSSQL_TYPE_BINARY,
            MSSQL_TYPE_VARBINARY,
            MSSQL_TYPE_IMAGE,
        ):
            return new_column(column, GOE_TYPE_BINARY, data_length=column.data_length)
        if column.data_type in (MSSQL_TYPE_TINYINT, MSSQL_TYPE_SMALLINT):
            return new_column(column, GOE_TYPE_INTEGER_2)
        if column.data_type == MSSQL_TYPE_INT:
            return new_column(column, GOE_TYPE_INTEGER_4)
        if column.data_type == MSSQL_TYPE_BIGINT:
            return new_column(column, GOE_TYPE_INTEGER_8)
        if column.data_type == MSSQL_TYPE_FLOAT:
            return new_column(column, GOE_TYPE_DOUBLE)
        if column.data_type == MSSQL_TYPE_REAL:
            return new_column(column, GOE_TYPE_FLOAT)
        if column.data_type in (
            MSSQL_TYPE_DECIMAL,
            MSSQL_TYPE_NUMERIC,
            MSSQL_TYPE_MONEY,
            MSSQL_TYPE_SMALLMONEY,
        ):
            data_precision = column.data_precision
            data_scale = column.data_scale
            if data_precision is not None and data_scale is not None:
                if data_scale > data_precision:
                    data_precision = data_scale
                elif data_scale < 0:
                    data_scale = 0
            if data_scale == 0 and data_precision is not None:
                if 1 <= data_precision <= 2:
                    integral_type = GOE_TYPE_INTEGER_1
                elif 3 <= data_precision <= 4:
                    integral_type = GOE_TYPE_INTEGER_2
                elif 5 <= data_precision <= 9:
                    integral_type = GOE_TYPE_INTEGER_4
                elif 10 <= data_precision <= 18:
                    integral_type = GOE_TYPE_INTEGER_8
                elif 19 <= data_precision <= 38:
                    integral_type = GOE_TYPE_INTEGER_38
                else:
                    integral_type = GOE_TYPE_DECIMAL
                return new_column(column, integral_type, data_precision=data_precision, data_scale=0)
            safe_mapping = False if data_precision is None and data_scale is None else None
            return new_column(
                column,
                GOE_TYPE_DECIMAL,
                data_precision=data_precision,
                data_scale=data_scale,
                safe_mapping=safe_mapping,
            )
        if column.data_type == MSSQL_TYPE_DATE:
            return new_column(column, GOE_TYPE_DATE)
        if column.data_type == MSSQL_TYPE_TIME:
            return new_column(column, GOE_TYPE_TIME)
        if column.data_type in (
            MSSQL_TYPE_SMALLDATETIME,
            MSSQL_TYPE_DATETIME,
            MSSQL_TYPE_DATETIME2,
        ):
            return new_column(column, GOE_TYPE_TIMESTAMP)
        if column.data_type == MSSQL_TYPE_DATETIMEOFFSET:
            return new_column(column, GOE_TYPE_TIMESTAMP_TZ)
        raise NotImplementedError(f"Unsupported MSSQL data type: {column.data_type}")

    def from_canonical_column(self, column: CanonicalColumn) -> MSSQLColumn:
        raise NotImplementedError("MSSQL from_canonical_column() not implemented.")

    def gen_column(
        self,
        name: str,
        data_type: str,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        nullable: bool | str | None = None,
        data_default: Any = None,
        hidden: bool | None = None,
        char_semantics: str | None = None,
        char_length: int | None = None,
    ) -> MSSQLColumn:
        return MSSQLColumn(
            name,
            data_type,
            data_length=data_length,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=nullable,
            data_default=data_default,
            hidden=hidden,
            char_semantics=char_semantics,
            char_length=char_length,
        )

    def gen_default_numeric_column(self, column_name: str) -> MSSQLColumn:
        return self.gen_column(column_name, MSSQL_TYPE_NUMERIC)

    def gen_default_date_column(self, column_name: str) -> MSSQLColumn:
        return self.gen_column(column_name, MSSQL_TYPE_DATE)

    def transform_encrypt_data_type(self) -> str:
        return MSSQL_TYPE_VARCHAR

    def transform_null_cast(self, rdbms_column: MSSQLColumn) -> str:
        assert isinstance(rdbms_column, MSSQLColumn)
        return f"CAST(NULL AS {rdbms_column.format_data_type()})"

    def transform_tokenize_data_type(self) -> str:
        return MSSQL_TYPE_VARCHAR

    def transform_regexp_replace_expression(
        self,
        backend_column: Any,
        regexp_replace_pattern: str,
        regexp_replace_string: str,
    ) -> str:
        raise NotImplementedError("MSSQL transform_regexp_replace_expression() not implemented.")

    def transform_translate_expression(self, backend_column: Any, from_string: str, to_string: str) -> str:
        raise NotImplementedError("MSSQL transform_translate_expression() not implemented.")

    def _hydrate_from_snapshot(self) -> None:
        if hasattr(self._db_api, "get_table_snapshot"):
            snapshot = self._db_api.get_table_snapshot(self.owner, self.table_name)
            self._table_exists = snapshot.table_exists
            if snapshot.table_exists:
                self._table_is_view = False
            self._stats_num_rows = snapshot.num_rows
            self._partitioned = snapshot.partitioned
            self._columns_setter(list(snapshot.columns), skip_exists_check=True)
            self._primary_key_columns = list(snapshot.primary_key_columns)
            if self._table_exists:
                self._size_in_bytes = snapshot.size_bytes
                self._hash_bucket_candidate = snapshot.hash_bucket_candidate
                self._table_stats = None
            else:
                self._hash_bucket_candidate = None
                self._table_stats = None
            return

        self._get_table_details()
        self._columns_setter(self._get_column_details(), skip_exists_check=True)
        if self._table_exists:
            self._size_in_bytes = self._get_table_size()
            self._hash_bucket_candidate = self._get_hash_bucket_candidate()
            self._table_stats = None
        else:
            self._hash_bucket_candidate = None
            self._table_stats = None

    def _extra_data_type_supported_checks(self) -> bool:
        unsupported_cols = [
            tc.name for tc in (self._columns or []) if "varchar" in tc.data_type and tc.data_length == -1
        ]
        if unsupported_cols:
            for col_name in unsupported_cols:
                self._messages.log(f"MAX precision not supported for (n)varchar column: {col_name}")
            return False
        return True

    def _get_column_low_high_values(
        self,
        column_name: str,
        from_stats: bool = True,
        sample_perc: int = 1,
    ) -> tuple[Any, Any]:
        raise NotImplementedError("MSSQL _get_column_low_high_values not implemented.")

    def _get_table_details(self) -> None:
        logger.debug("_get_table_details: %s, %s", self.owner, self.table_name)
        snapshot = self._db_api.get_table_snapshot(self.owner, self.table_name)
        self._iot_type = None
        self._stats_num_rows = snapshot.num_rows
        self._partitioned = snapshot.partitioned
        self._partition_type = None
        self._table_exists = snapshot.table_exists

    def _get_columns_with_partition_info(self, part_col_names_override: Any = None) -> list[Any]:
        if not self.is_partitioned() and not part_col_names_override:
            return list(self._columns or [])
        raise NotImplementedError("MSSQL _get_columns_with_partition_info not implemented.")

    def _get_hash_bucket_candidate(self) -> str | None:
        """Return candidate hash bucket column from cached SQL Server catalog statistics."""
        snapshot = self._db_api.get_table_snapshot(self.owner, self.table_name)
        return snapshot.hash_bucket_candidate

    def _get_table_stats(self) -> Any:
        raise NotImplementedError("MSSQL table_stats not implemented.")

    def _is_compression_enabled(self) -> bool:
        raise NotImplementedError("MSSQL _is_compression_enabled not implemented.")

    def _sample_data_types_compression_factor(self) -> float:
        raise NotImplementedError("MSSQL _sample_data_types_compression_factor not implemented.")

    def _sample_data_types_data_sample_parallelism(self, data_sample_parallelism: Any) -> int:
        raise NotImplementedError("MSSQL _sample_data_types_compression_factor not implemented.")

    def _sample_data_types_data_sample_pct(self, data_sample_pct: Any) -> float:
        raise NotImplementedError("MSSQL _sample_data_types_data_sample_pct not implemented.")

    def _sample_data_types_date_as_string_column(self, column_name: str) -> MSSQLColumn:
        raise NotImplementedError("MSSQL _sample_data_types_date_as_string_column not implemented.")

    def _sample_data_types_decimal_column(
        self,
        column: MSSQLColumn,
        data_precision: int,
        data_scale: int,
    ) -> MSSQLColumn:
        return MSSQLColumn(
            column.name,
            MSSQL_TYPE_NUMERIC,
            data_precision=data_precision,
            data_scale=data_scale,
            nullable=column.nullable,
            safe_mapping=False,
        )

    def _sample_data_types_max_pct(self) -> float:
        raise NotImplementedError("MSSQL _sample_data_types_max_pct not implemented.")

    def _sample_data_types_min_pct(self) -> float:
        raise NotImplementedError("MSSQL _sample_data_types_min_pct not implemented.")

    def _sample_data_types_min_gb(self) -> int:
        return 1

    def _sample_perc_sql_clause(self, data_sample_pct: object) -> str:
        return ""
