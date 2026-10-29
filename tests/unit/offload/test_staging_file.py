# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import os
from unittest import TestCase

from goe.offload.offload_constants import (
    DBTYPE_BIGQUERY,
    DBTYPE_HIVE,
    DBTYPE_IMPALA,
    DBTYPE_ORACLE,
    DBTYPE_SNOWFLAKE,
    DBTYPE_SYNAPSE,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.offload_messages import OffloadMessages
from goe.offload.registry import create_staging_file
from goe.offload.schema.column_spec import (
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
    ColumnDialect,
    ColumnSpec,
)

STAGING_TYPES = {
    FILE_STORAGE_FORMAT_AVRO: ColumnSpec,
    FILE_STORAGE_FORMAT_PARQUET: ColumnSpec,
}


class FakeOpts:
    def __init__(self, db_type, target=None):
        self.db_type = db_type
        self.rdbms_dsn = "blah:blah;blah=blah"
        self.ora_adm_user = None
        self.ora_adm_pass = None
        self.rdbms_app_user = None
        self.rdbms_app_pass = None
        self.target = target or os.environ.get("QUERY_ENGINE", "").lower()
        self.backend_session_parameters = None
        self.use_oracle_wallet = None


class TestStagingFile(TestCase):
    def test_oracle_bigquery_avro(self):
        self._test_staging_file(DBTYPE_ORACLE, DBTYPE_BIGQUERY, FILE_STORAGE_FORMAT_AVRO)

    def test_oracle_bigquery_parquet(self):
        self._test_staging_file(DBTYPE_ORACLE, DBTYPE_BIGQUERY, FILE_STORAGE_FORMAT_PARQUET)

    def test_oracle_hive_avro(self):
        self._test_staging_file(DBTYPE_ORACLE, DBTYPE_HIVE, FILE_STORAGE_FORMAT_AVRO)

    def test_oracle_impala_avro(self):
        self._test_staging_file(DBTYPE_ORACLE, DBTYPE_IMPALA, FILE_STORAGE_FORMAT_AVRO)

    def test_oracle_snowflake_avro(self):
        self._test_staging_file(DBTYPE_ORACLE, DBTYPE_SNOWFLAKE, FILE_STORAGE_FORMAT_AVRO)

    def test_oracle_snowflake_parquet(self):
        self._test_staging_file(DBTYPE_ORACLE, DBTYPE_SNOWFLAKE, FILE_STORAGE_FORMAT_PARQUET)

    def test_oracle_synapse_parquet(self):
        self._test_staging_file(DBTYPE_ORACLE, DBTYPE_SYNAPSE, FILE_STORAGE_FORMAT_PARQUET)

    def _canonical_columns(self):
        return [
            ColumnSpec(ColumnDialect.CANONICAL, "COL_FIXED_STR", GOE_TYPE_FIXED_STRING, data_length=10),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_LARGE_STR", GOE_TYPE_LARGE_STRING),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_VARIABLE_STR", GOE_TYPE_VARIABLE_STRING),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_BINARY", GOE_TYPE_BINARY),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_LARGE_BINARY", GOE_TYPE_LARGE_BINARY),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_INT_1", GOE_TYPE_INTEGER_1),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_INT_2", GOE_TYPE_INTEGER_2),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_INT_4", GOE_TYPE_INTEGER_4),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_INT_8", GOE_TYPE_INTEGER_8),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_INT_38", GOE_TYPE_INTEGER_38),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_DEC_NO_P_S", GOE_TYPE_DECIMAL),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_DEC_10_2", GOE_TYPE_DECIMAL, data_precision=10, data_scale=2),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_FLOAT", GOE_TYPE_FLOAT),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_DOUBLE", GOE_TYPE_DOUBLE),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_DATE", GOE_TYPE_DATE),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_TIME", GOE_TYPE_TIME),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_TIMESTAMP", GOE_TYPE_TIMESTAMP),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_TIMESTAMP_TZ", GOE_TYPE_TIMESTAMP_TZ),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_INTERVAL_DS", GOE_TYPE_INTERVAL_DS),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_INTERVAL_YM", GOE_TYPE_INTERVAL_YM),
            ColumnSpec(ColumnDialect.CANONICAL, "COL_BOOLEAN", GOE_TYPE_BOOLEAN),
        ]

    def _test_staging_file_columns(self, staging_file):
        file_columns = staging_file.get_staging_columns()
        self.assertIsInstance(file_columns, list)
        self.assertIsInstance(
            file_columns[0],
            STAGING_TYPES[staging_file.file_format],
            f"{type(file_columns[0])} != {STAGING_TYPES[staging_file.file_format]}",
        )
        canonical_columns = staging_file.get_canonical_staging_columns()
        self.assertIsInstance(canonical_columns, list)
        self.assertIsInstance(canonical_columns[0], ColumnSpec)
        for col in file_columns:
            self.assertIsInstance(staging_file.get_java_primitive(col), (str, type(None)))

    def _test_staging_file(self, source_db_type, target_db_type, staging_format):
        messages = OffloadMessages()
        offload_options = FakeOpts(source_db_type, target=target_db_type)
        staging_file = create_staging_file(
            "no_db",
            "no_table",
            staging_format,
            self._canonical_columns(),
            offload_options,
            False,
            messages,
            dry_run=True,
        )
        self.assertIn(
            staging_file.file_format,
            [FILE_STORAGE_FORMAT_AVRO, FILE_STORAGE_FORMAT_PARQUET],
        )
        self.assertEqual(staging_file.file_format, staging_format)
        self._test_staging_file_columns(staging_file)
        self.assertIsInstance(staging_file.get_file_schema_json(as_string=True), str)
        self.assertIsInstance(
            staging_file.get_file_schema_json(as_string=False),
            dict if staging_file.file_format == FILE_STORAGE_FORMAT_AVRO else list,
        )
