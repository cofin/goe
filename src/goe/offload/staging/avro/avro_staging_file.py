# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadStagingAvroFile, OffloadStagingAvroImpalaFile: OffloadStagingFile implementations for Avro"""

import logging
from typing import ClassVar

from goe.offload.schema.column_spec import (
    AVRO_TYPE_BOOLEAN,
    AVRO_TYPE_DOUBLE,
    AVRO_TYPE_FLOAT,
    AVRO_TYPE_INT,
    AVRO_TYPE_LONG,
    GOE_TYPE_BINARY,
    GOE_TYPE_LARGE_BINARY,
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
from goe.serializers import decode_json

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OffloadStagingAvroFile(OffloadStagingFileInterface):
    """AVRO implementation"""

    type_mapping_target: ClassVar[MappingTarget] = MappingTarget.AVRO

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

        logger.info("OffloadStagingAvroFile setup: (%s, %s)" % (load_db_name, table_name))
        if dry_run:
            logger.info("* Dry run *")

    def from_canonical_column(self, column: ColumnSpec) -> ColumnSpec:
        """Translate an internal GOE column to an Avro column"""
        ctx = MappingContext(limits=TypeMappingLimits(), binary_as_base64=self._binary_data_as_base64)
        return TYPE_REGISTRY.from_canonical(column, self.type_mapping_target, ctx)

    def to_canonical_column(self, column: ColumnSpec, use_staging_file_name: bool = False) -> ColumnSpec:
        """Translate an Avro column to an internal GOE column"""
        ctx = MappingContext(
            limits=TypeMappingLimits(),
            binary_as_base64=self._binary_data_as_base64,
            use_staging_file_name=use_staging_file_name,
        )
        return TYPE_REGISTRY.staging_to_canonical(column, ctx)

    def get_file_schema_json(self, as_string=True):
        json_string = self._get_avro_schema_json_string()
        return json_string if as_string else decode_json(json_string)

    def get_java_primitive(self, staging_column):
        return self._get_avro_java_primitive(staging_column)

    def _get_avro_schema_json_string(self):
        col_schemas = []
        for col in self.get_staging_columns():
            avro_field_type = ('["%s","null"]' if col.nullable else '"%s"') % col.data_type.lower()
            col_schemas.append("""{"name":"%s","type":%s}""" % (col.staging_file_column_name, avro_field_type))

        avro_schema = """{
  "type" : "record",
  "name" : "%(table_name)s",
  "namespace" : "%(load_db)s",
  "fields" : [%(fields)s],
  "tableName" : "%(load_db)s.%(table_name)s"
}""" % {
            "load_db": self.load_db_name,
            "table_name": self.table_name,
            "fields": ", ".join(col_schemas),
        }

        return avro_schema

    def _get_avro_java_primitive(self, staging_column):
        """Let the calling program use implicit conversion"""
        canonical_column = match_table_column(staging_column.name, self._canonical_columns)
        if staging_column.data_type == AVRO_TYPE_BOOLEAN:
            return JAVA_PRIMITIVE_BOOLEAN
        if staging_column.data_type == AVRO_TYPE_DOUBLE:
            return JAVA_PRIMITIVE_DOUBLE
        if staging_column.data_type == AVRO_TYPE_FLOAT:
            return JAVA_PRIMITIVE_FLOAT
        if staging_column.data_type == AVRO_TYPE_INT:
            return JAVA_PRIMITIVE_INTEGER
        if staging_column.data_type == AVRO_TYPE_LONG:
            return JAVA_PRIMITIVE_LONG
        assert canonical_column is not None
        if canonical_column.data_type not in (GOE_TYPE_BINARY, GOE_TYPE_LARGE_BINARY):
            return JAVA_PRIMITIVE_STRING
        return None


class OffloadStagingAvroImpalaFile(OffloadStagingAvroFile):
    """AVRO implementation on Impala (inherits from Avro)"""

    type_mapping_target: ClassVar[MappingTarget] = MappingTarget.AVRO_IMPALA

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

        logger.info("OffloadStagingAvroImpalaFile setup: (%s, %s)" % (load_db_name, table_name))
        if dry_run:
            logger.info("* Dry run *")
