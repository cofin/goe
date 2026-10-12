# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""BigQuery-first configuration defaults and validation."""

import pytest

from goe.config.config_validation_functions import OrchestrationConfigException
from goe.config.orchestration_config import OrchestrationConfig
from goe.offload.offload_constants import (
    BIGQUERY_LOAD_TABLE_MODE_EXTERNAL,
    BIGQUERY_LOAD_TABLE_MODE_NATIVE,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
)
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_gcp_staging_format_defaults_to_parquet() -> None:
    """GCP backends stage Parquet unless OFFLOAD_STAGING_FORMAT is set."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    assert config.offload_staging_format == FILE_STORAGE_FORMAT_PARQUET


def test_explicit_avro_staging_format_is_preserved() -> None:
    """An explicit OFFLOAD_STAGING_FORMAT=AVRO keeps Avro staging."""
    config = build_mock_options({**FAKE_ORACLE_BQ_ENV, "OFFLOAD_STAGING_FORMAT": "avro"})
    assert config.offload_staging_format == FILE_STORAGE_FORMAT_AVRO


def test_bigquery_load_table_mode_defaults_to_native() -> None:
    """BIGQUERY_LOAD_TABLE_MODE defaults to NATIVE."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    assert config.bigquery_load_table_mode == BIGQUERY_LOAD_TABLE_MODE_NATIVE


def test_bigquery_load_table_mode_accepts_external_case_insensitively() -> None:
    """EXTERNAL is accepted in any case."""
    config = build_mock_options({**FAKE_ORACLE_BQ_ENV, "BIGQUERY_LOAD_TABLE_MODE": "external"})
    assert config.bigquery_load_table_mode == BIGQUERY_LOAD_TABLE_MODE_EXTERNAL


def test_bigquery_load_table_mode_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown modes raise OrchestrationConfigException."""
    for key, val in FAKE_ORACLE_BQ_ENV.items():
        if val is not None:
            monkeypatch.setenv(key, str(val))
    monkeypatch.setenv("BIGQUERY_LOAD_TABLE_MODE", "STREAMING")
    with pytest.raises(OrchestrationConfigException, match="BIGQUERY_LOAD_TABLE_MODE"):
        OrchestrationConfig.from_dict({"verbose": False})
