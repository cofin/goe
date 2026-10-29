#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadStagingParquetFile: OffloadStagingFile implementation for Parquet"""

import logging
from typing import ClassVar

from goe.offload.schema.column_spec import (
    GOE_TYPE_BINARY,
    GOE_TYPE_LARGE_BINARY,
    PARQUET_TYPE_BOOLEAN,
    PARQUET_TYPE_DOUBLE,
    PARQUET_TYPE_FLOAT,
    PARQUET_TYPE_INT32,
    PARQUET_TYPE_INT64,
    ColumnSpec,
    match_table_column,
)
from goe.offload.schema.type_registry import (
    TYPE_REGISTRY,
    MappingContext,
    MappingTarget,
    TypeMappingLimits,
)
from goe.offload.staging.staging_file import (
    JAVA_PRIMITIVE_BOOLEAN,
    JAVA_PRIMITIVE_DOUBLE,
    JAVA_PRIMITIVE_FLOAT,
    JAVA_PRIMITIVE_INTEGER,
    JAVA_PRIMITIVE_LONG,
    JAVA_PRIMITIVE_STRING,
    OffloadStagingFileInterface,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OffloadStagingParquetFile(OffloadStagingFileInterface):
    """Parquet implementation"""

    type_mapping_target: ClassVar[MappingTarget] = MappingTarget.PARQUET

    def __init__(
        self,
        load_db_name,
        table_name,
        staging_file_format,
        canonical_columns,
        binary_data_as_base64,
        messages,
        dry_run=False,
    ):
        """CONSTRUCTOR"""
        super().__init__(
            load_db_name,
            table_name,
            staging_file_format,
            canonical_columns,
            binary_data_as_base64,
            messages,
            dry_run=dry_run,
        )

        logger.info("OffloadStagingParquetFile setup: (%s, %s)" % (load_db_name, table_name))
        if dry_run:
            logger.info("* Dry run *")

    def from_canonical_column(self, column: ColumnSpec) -> ColumnSpec:
        """Translate an internal GOE column to a Parquet column"""
        ctx = MappingContext(limits=TypeMappingLimits(), binary_as_base64=self._binary_data_as_base64)
        return TYPE_REGISTRY.from_canonical(column, self.type_mapping_target, ctx)

    def to_canonical_column(self, column: ColumnSpec, use_staging_file_name: bool = False) -> ColumnSpec:
        """Translate a Parquet column to an internal GOE column"""
        ctx = MappingContext(
            limits=TypeMappingLimits(),
            binary_as_base64=self._binary_data_as_base64,
            use_staging_file_name=use_staging_file_name,
        )
        return TYPE_REGISTRY.staging_to_canonical(column, ctx)

    def get_java_primitive(self, staging_column):
        return self._get_parquet_java_primitive(staging_column)

    def get_file_schema_json(self, as_string=True):
        schema = [
            (_.staging_file_column_name, _.format_data_type(), bool(_.nullable)) for _ in self.get_staging_columns()
        ]
        return repr(schema) if as_string else schema

    def _get_parquet_java_primitive(self, staging_column):
        """Let the calling program use implicit conversion"""
        canonical_column = match_table_column(staging_column.name, self._canonical_columns)
        if staging_column.data_type == PARQUET_TYPE_BOOLEAN:
            return JAVA_PRIMITIVE_BOOLEAN
        if staging_column.data_type == PARQUET_TYPE_DOUBLE:
            return JAVA_PRIMITIVE_DOUBLE
        if staging_column.data_type == PARQUET_TYPE_FLOAT:
            return JAVA_PRIMITIVE_FLOAT
        if staging_column.data_type == PARQUET_TYPE_INT32:
            return JAVA_PRIMITIVE_INTEGER
        if staging_column.data_type == PARQUET_TYPE_INT64:
            return JAVA_PRIMITIVE_LONG
        assert canonical_column is not None
        if canonical_column.data_type not in (GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY):
            return JAVA_PRIMITIVE_STRING
        return None
