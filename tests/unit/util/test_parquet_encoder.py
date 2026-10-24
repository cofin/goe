# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""TestParquetEncoder: Unit test library to test parquet_encoder module."""

import os.path
from unittest import TestCase, main
from unittest.mock import Mock

from pyarrow import parquet

from goe.offload.offload_constants import FILE_STORAGE_FORMAT_PARQUET
from goe.offload.offload_messages import OffloadMessages
from goe.offload.oracle.oracle_column import ORACLE_TYPE_VARCHAR2, OracleColumn
from goe.offload.registry import create_query_import_encoder
from goe.offload.staging.parquet.parquet_encoder import PARQUET_TYPE_STRING, ParquetEncoder
from goe.util.string_utils import get_temp_path
from tests.unit.util.test_avro_encoder import ROW_COUNT, FakeDb


class TestParquetEncoder(TestCase):
    def test_parquet_encoder(self):
        source_columns = [OracleColumn("COLUMN_NAME", ORACLE_TYPE_VARCHAR2, data_length=5)]
        parquet_schema = [(_.name, PARQUET_TYPE_STRING, _.nullable) for _ in source_columns]
        messages = OffloadMessages()
        staging_file = Mock(file_format=FILE_STORAGE_FORMAT_PARQUET)
        staging_file.get_file_schema_json.return_value = parquet_schema
        encoder = create_query_import_encoder(staging_file, messages)
        self.assertIsInstance(encoder, ParquetEncoder)
        extraction_cursor = FakeDb(ROW_COUNT)
        local_staging_path = get_temp_path(prefix="goe-unittest", suffix=".parquet")
        rows_imported = encoder.write_from_cursor(local_staging_path, extraction_cursor, source_columns)
        # Check output file exists
        self.assertTrue(os.path.exists(local_staging_path))
        # Check correct number of rows written
        self.assertEqual(rows_imported, ROW_COUNT)
        # Open the file to prove it is valid Parquet
        parquet_file = parquet.ParquetFile(local_staging_path)
        metadata = parquet_file.metadata.to_dict()
        self.assertEqual(metadata["row_groups"][0]["num_rows"], ROW_COUNT)


if __name__ == "__main__":
    main()
