# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Native BigQuery load job behavior for staged files."""

from unittest.mock import MagicMock, patch

from google.cloud import bigquery

from goe.offload.bigquery.bigquery_load_job import build_staging_load_job_config
from goe.offload.factory.backend_table_factory import backend_table_factory
from goe.offload.offload_constants import DBTYPE_BIGQUERY, FILE_STORAGE_FORMAT_AVRO, FILE_STORAGE_FORMAT_PARQUET
from goe.offload.offload_messages import OffloadMessages
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options

KMS_KEY = "projects/kms-project/locations/US/keyRings/ring-name/cryptoKeys/key-name"


def test_parquet_load_job_config() -> None:
    """Parquet loads truncate the target, keep decimal precision, apply CMEK and labels."""
    job_config = build_staging_load_job_config(FILE_STORAGE_FORMAT_PARQUET, KMS_KEY, {"goe_version": "1"})
    assert job_config.source_format == bigquery.SourceFormat.PARQUET
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    assert set(job_config.decimal_target_types) == {"NUMERIC", "BIGNUMERIC", "STRING"}
    assert job_config.destination_encryption_configuration.kms_key_name == KMS_KEY
    assert job_config.labels == {"goe_version": "1"}
    assert job_config.schema is None


def test_avro_load_job_config_has_no_decimal_targets_or_cmek() -> None:
    """Avro loads keep defaults when no KMS key is configured."""
    job_config = build_staging_load_job_config(FILE_STORAGE_FORMAT_AVRO, None, {})
    assert job_config.source_format == bigquery.SourceFormat.AVRO
    assert job_config.decimal_target_types is None
    assert job_config.destination_encryption_configuration is None


def test_native_mode_runs_load_job() -> None:
    """NATIVE mode loads part* files into the load table instead of creating an external table."""
    table = _table(dry_run=False)
    client = table._db_api.bq_client()
    staging_file = MagicMock(file_format=FILE_STORAGE_FORMAT_PARQUET)
    with patch.object(table._db_api, "create_table") as create_table:
        cmds = table._create_load_table(staging_file)
    create_table.assert_not_called()
    uri, destination = client.load_table_from_uri.call_args.args[:2]
    assert uri.endswith("/part*")
    assert destination == f"{table._db_api.bq_dataset_id(table._load_db_name)}.{table._load_table_name}"
    client.load_table_from_uri.return_value.result.assert_called_once()
    assert cmds and "BigQuery load job" in cmds[0]


def test_native_mode_dry_run_only_logs() -> None:
    """Dry-run returns the load description without calling BigQuery."""
    table = _table(dry_run=True)
    cmds = table._create_load_table(MagicMock(file_format=FILE_STORAGE_FORMAT_PARQUET))
    table._db_api.bq_client().load_table_from_uri.assert_not_called()
    assert "WRITE_TRUNCATE" in cmds[0]


def test_external_mode_keeps_external_table() -> None:
    """EXTERNAL mode preserves the external staging table path."""
    table = _table(dry_run=False, mode="EXTERNAL")
    with patch.object(table._db_api, "create_table", return_value=["CREATE EXTERNAL TABLE"]) as create_table:
        table._create_load_table(MagicMock(file_format=FILE_STORAGE_FORMAT_AVRO))
    assert create_table.call_args.kwargs["external"] is True
    table._db_api.bq_client().load_table_from_uri.assert_not_called()


def _table(dry_run: bool, mode: str = "NATIVE"):
    """Build a non-connecting BigQuery table with a mocked BigQuery client."""
    config = build_mock_options({**FAKE_ORACLE_BQ_ENV, "BIGQUERY_LOAD_TABLE_MODE": mode})
    table = backend_table_factory(
        "sales", "orders", DBTYPE_BIGQUERY, config, OffloadMessages(), dry_run=dry_run, do_not_connect=True
    )
    table._db_api._client = MagicMock()
    return table
