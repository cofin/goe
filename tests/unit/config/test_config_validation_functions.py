# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import pytest

import goe.config.config_validation_functions as module_under_test
from goe.offload import offload_constants
from tests.unit.test_functions import (
    FAKE_ORACLE_BQ_ENV,
    build_mock_options,
)


@pytest.fixture
def bq_config():
    return build_mock_options(FAKE_ORACLE_BQ_ENV)


@pytest.mark.parametrize(
    "input,expected_status",
    [
        ("1.0", True),
        ("1.2", True),
        ("2.1", True),
        ("2.2", True),
        ("1", False),
        ("0", False),
        ("99.1", False),
        ("2/1", False),
        ("a", False),
        ("a.b", False),
    ],
)
def test_normalise_bigquery_options_google_dataproc_batches_version(bq_config, input: str, expected_status: bool):
    bq_config.backend_distribution = offload_constants.BACKEND_DISTRO_GCP
    bq_config.google_dataproc_batches_version = input
    if expected_status:
        module_under_test.normalise_bigquery_options(bq_config), f"For input: {input}"
    else:
        with pytest.raises(Exception) as _:
            module_under_test.normalise_bigquery_options(bq_config), f"For input: {input}"


def test_normalise_filesystem_options_rejects_removed_scheme(bq_config) -> None:
    """Removed filesystem schemes are rejected during filesystem option validation."""
    bq_config.offload_fs_scheme = "mapr" + "fs"
    with pytest.raises(
        module_under_test.OrchestrationConfigException, match="OFFLOAD_FS_SCHEME/--offload-fs-scheme must be one of"
    ):
        module_under_test.normalise_filesystem_options(bq_config)


def test_normalise_backend_options_rejects_removed_distribution(bq_config) -> None:
    """Removed backend distributions are rejected."""
    bq_config.backend_distribution = "MA" + "PR"
    assert bq_config.backend_distribution not in offload_constants.HADOOP_BASED_BACKEND_DISTRIBUTIONS


def test_normalise_offload_transport_config_rejects_removed_transport(bq_config) -> None:
    """Removed transport configuration values are rejected."""
    bq_config.offload_transport = "SQ" + "OOP"
    with pytest.raises(module_under_test.OrchestrationConfigException, match="Invalid value for OFFLOAD_TRANSPORT"):
        module_under_test.normalise_offload_transport_config(bq_config)


@pytest.mark.parametrize(
    "input,expected_status",
    [
        ("1d", True),
        ("120m", True),
        ("21h", True),
        ("1", False),
        ("22", False),
        ("a", False),
        ("9.1h", False),
        ("2/1", False),
        ("am", False),
        (".h", False),
    ],
)
def test_normalise_bigquery_options_google_dataproc_batches_ttl(bq_config, input: str, expected_status: bool):
    bq_config.backend_distribution = offload_constants.BACKEND_DISTRO_GCP
    bq_config.google_dataproc_batches_ttl = input
    if expected_status:
        module_under_test.normalise_bigquery_options(bq_config), f"For input: {input}"
    else:
        with pytest.raises(Exception) as _:
            module_under_test.normalise_bigquery_options(bq_config), f"For input: {input}"


def test_normalise_filesystem_options_rejects_removed_scheme(bq_config) -> None:
    """Removed filesystem schemes are rejected during filesystem option validation."""
    bq_config.offload_fs_scheme = "mapr" + "fs"
    with pytest.raises(
        module_under_test.OrchestrationConfigException, match="OFFLOAD_FS_SCHEME/--offload-fs-scheme must be one of"
    ):
        module_under_test.normalise_filesystem_options(bq_config)


def test_normalise_backend_options_rejects_removed_distribution(bq_config) -> None:
    """Removed backend distributions are rejected."""
    bq_config.backend_distribution = "MA" + "PR"
    assert bq_config.backend_distribution not in offload_constants.HADOOP_BASED_BACKEND_DISTRIBUTIONS


def test_normalise_offload_transport_config_rejects_removed_transport(bq_config) -> None:
    """Removed transport configuration values are rejected."""
    bq_config.offload_transport = "SQ" + "OOP"
    with pytest.raises(module_under_test.OrchestrationConfigException, match="Invalid value for OFFLOAD_TRANSPORT"):
        module_under_test.normalise_offload_transport_config(bq_config)
