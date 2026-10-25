# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""MSSQLColumn: MSSQL implementation of ColumnMetadataInterface."""

from collections.abc import Sequence
from typing import Any

from goe.offload.column_metadata import ColumnMetadataInterface

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


class MSSQLColumn(ColumnMetadataInterface):
    """Hold metadata details for a single Microsoft SQL Server table column."""

    def __init__(
        self,
        name: str,
        data_type: str,
        data_length: int | None = None,
        data_precision: int | None = None,
        data_scale: int | None = None,
        nullable: bool | str | None = None,
        data_default: Any = None,
        hidden: bool | str | None = None,
        char_length: int | None = None,
        safe_mapping: bool = True,
        partition_info: Any = None,
        char_semantics: str | None = None,
    ) -> None:
        """Initialize an MSSQLColumn with SQL Server type and length metadata."""
        super().__init__(
            name,
            data_type,
            data_length,
            data_precision,
            data_scale,
            nullable,
            data_default,
            safe_mapping=safe_mapping,
            partition_info=partition_info,
            char_length=char_length,
            char_semantics=char_semantics,
        )
        self.hidden = hidden

    @staticmethod
    def from_mssql(attribute_list: Sequence[Any]) -> "MSSQLColumn":
        """Construct an MSSQLColumn from a 10-element SQL Server catalog row."""
        (
            name,
            _,
            nullable,
            data_type,
            data_precision,
            data_scale,
            data_length,
            data_default,
            hidden,
            char_length,
        ) = attribute_list
        return MSSQLColumn(
            name,
            data_type,
            data_length,
            data_precision,
            data_scale,
            nullable,
            data_default,
            hidden,
            char_length,
        )

    def format_data_type(self) -> str:
        """Format the SQL Server data type with precision/scale or length when applicable."""
        if self.data_type in [MSSQL_TYPE_DECIMAL, MSSQL_TYPE_NUMERIC]:
            if self.data_precision and self.data_scale is not None:
                return f"{self.data_type}({self.data_precision},{self.data_scale})"
            if self.data_precision:
                return f"{self.data_type}({self.data_precision})"
            return self.data_type
        if self.data_type in [
            MSSQL_TYPE_CHAR,
            MSSQL_TYPE_VARCHAR,
            MSSQL_TYPE_NCHAR,
            MSSQL_TYPE_NVARCHAR,
        ]:
            return f"{self.data_type}({self.data_length})"
        return self.data_type

    def has_time_element(self) -> bool:
        """Return True if the column data type contains a time component."""
        return bool(
            self.data_type
            in [
                MSSQL_TYPE_DATETIME2,
                MSSQL_TYPE_DATETIME,
                MSSQL_TYPE_SMALLDATETIME,
                MSSQL_TYPE_TIME,
            ]
        )

    def is_binary(self) -> bool:
        """Return True if the column data type is binary."""
        return bool(self.data_type.lower() in [MSSQL_TYPE_BINARY, MSSQL_TYPE_VARBINARY, MSSQL_TYPE_IMAGE])

    def is_nan_capable(self) -> bool:
        """Return False as SQL Server types do not store IEEE NaN values."""
        return False

    def is_number_based(self) -> bool:
        """Return True if the column is numeric in class."""
        return bool(
            self.data_type.lower()
            in [
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
            ]
        )

    def is_date_based(self) -> bool:
        """Return True if the column is date or timestamp based."""
        return any(
            dt in self.data_type
            for dt in [
                MSSQL_TYPE_DATE,
                MSSQL_TYPE_DATETIME2,
                MSSQL_TYPE_DATETIME,
                MSSQL_TYPE_DATETIMEOFFSET,
                MSSQL_TYPE_SMALLDATETIME,
            ]
        )

    def is_interval(self) -> bool:
        """Return False as SQL Server has no interval type."""
        return False

    def is_string_based(self) -> bool:
        """Return True if the column is character string based."""
        return bool(
            self.data_type.lower()
            in [
                MSSQL_TYPE_CHAR,
                MSSQL_TYPE_VARCHAR,
                MSSQL_TYPE_NCHAR,
                MSSQL_TYPE_NVARCHAR,
            ]
        )

    def is_time_zone_based(self) -> bool:
        """Return True if the column contains time zone data."""
        return bool(self.data_type.lower() == MSSQL_TYPE_DATETIMEOFFSET)

    def is_hidden(self) -> Any:
        """Return the column hidden indicator."""
        return self.hidden

    def valid_for_offload_predicate(self) -> bool:
        """Return True if the column can be used in an offload predicate."""
        return bool(
            self.is_number_based() or (self.is_date_based() and not self.is_time_zone_based()) or self.is_string_based()
        )
