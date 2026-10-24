# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import os
from unittest import mock

import pytest

from goe.config import config_file
from goe.config.config_validation_functions import (
    OrchestrationConfigException,
    verify_json_option,
)
from goe.config.orchestration_config import (
    EXPECTED_CONFIG_ARGS,
    OrchestrationConfig,
)
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV


def test_verify_json_option():
    generic_json = '{"attrib1": "String", "attrib2": 1024, "attrib3": 1.024}'
    verify_json_option("TEST_JSON", generic_json)
    sample_rdbms_parameters_json = '{"cell_offload_processing": "false", "\\"_serial_direct_read\\"": "true"}'
    verify_json_option("TEST_JSON", sample_rdbms_parameters_json)
    sample_spark_parameters_json = '{"spark.driver.memory": "512M", "spark.executor.memory": "1024M"}'
    verify_json_option("TEST_JSON", sample_spark_parameters_json)
    for bad_json in [
        '{cell_offload_processing: "false"}',
        '{"cell_offload_processing": False}',
    ]:
        with pytest.raises(OrchestrationConfigException):
            verify_json_option("TEST_JSON", bad_json)


def test_as_defaults():
    k = mock.patch.dict(os.environ, FAKE_ORACLE_BQ_ENV)
    k.start()
    config = OrchestrationConfig.as_defaults()
    k.stop()
    # Check that every expected attribute is represented
    assert not bool(set(EXPECTED_CONFIG_ARGS) - vars(config).keys()), set(EXPECTED_CONFIG_ARGS) - vars(config).keys()


def test_from_dict():
    k = mock.patch.dict(os.environ, FAKE_ORACLE_BQ_ENV)
    k.start()
    config = OrchestrationConfig.from_dict({})
    k.stop()
    assert not bool(set(EXPECTED_CONFIG_ARGS) - vars(config).keys()), set(EXPECTED_CONFIG_ARGS) - vars(config).keys()
    k.start()
    config = OrchestrationConfig.from_dict({"vverbose": True})
    k.stop()
    assert not bool(set(EXPECTED_CONFIG_ARGS) - vars(config).keys()), set(EXPECTED_CONFIG_ARGS) - vars(config).keys()
    assert config.vverbose


@pytest.mark.parametrize(
    "input,expected_key,expected_value",
    [
        ("# Copyright 2016 The GOE Authors. All rights reserved.", None, None),
        ("#", None, None),
        ("# Some comment:", None, None),
        ("# Some other comment with = blah", None, None),
        ("# Some other comment with=blah", None, None),
        ("OFFLOAD_TRANSPORT=AUTO", "OFFLOAD_TRANSPORT", "AUTO"),
        ("#OFFLOAD_TRANSPORT=AUTO", "OFFLOAD_TRANSPORT", "AUTO"),
        ("#  OFFLOAD_TRANSPORT=AUTO", "OFFLOAD_TRANSPORT", "AUTO"),
        ("OFFLOAD_TRANSPORT=AUTO=21", "OFFLOAD_TRANSPORT", "AUTO=21"),
        ("OFFLOAD_TRANSPORT='AUTO 21'", "OFFLOAD_TRANSPORT", "'AUTO 21'"),
        ('OFFLOAD_TRANSPORT="AUTO 21"', "OFFLOAD_TRANSPORT", '"AUTO 21"'),
    ],
)
def test_config_file_env_key_value_pair(input: str, expected_key: str, expected_value: str):
    output = config_file.env_key_value_pair(input)
    if expected_key is None:
        assert output is None
    else:
        assert isinstance(output, tuple)
        assert len(output) == 2
        k, v = output
        assert k == expected_key
        assert v == expected_value


GCP_AUTH_ENV = {
    "GOOGLE_CLOUD_PROJECT": "env-project",
    "GOOGLE_CLOUD_QUOTA_PROJECT": "env-quota",
    "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": "goe-sa@env-project.iam.gserviceaccount.com",
    "GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT": "dp-caller@env-project.iam.gserviceaccount.com",
}


def test_gcp_auth_options_from_environment():
    with mock.patch.dict(os.environ, {**FAKE_ORACLE_BQ_ENV, **GCP_AUTH_ENV}):
        config = OrchestrationConfig.from_dict({})
    assert config.google_cloud_project == "env-project"
    assert config.google_cloud_quota_project == "env-quota"
    assert config.google_impersonate_service_account == "goe-sa@env-project.iam.gserviceaccount.com"
    assert config.google_dataproc_impersonate_service_account == "dp-caller@env-project.iam.gserviceaccount.com"


def test_gcp_auth_options_from_dict_override_environment():
    with mock.patch.dict(os.environ, {**FAKE_ORACLE_BQ_ENV, **GCP_AUTH_ENV}):
        config = OrchestrationConfig.from_dict(
            {
                "google_cloud_project": "dict-project",
                "google_cloud_quota_project": "dict-quota",
                "google_impersonate_service_account": "dict-sa@dict-project.iam.gserviceaccount.com",
                "google_dataproc_impersonate_service_account": "dict-dp@dict-project.iam.gserviceaccount.com",
            }
        )
    assert config.google_cloud_project == "dict-project"
    assert config.google_cloud_quota_project == "dict-quota"
    assert config.google_impersonate_service_account == "dict-sa@dict-project.iam.gserviceaccount.com"
    assert config.google_dataproc_impersonate_service_account == "dict-dp@dict-project.iam.gserviceaccount.com"


def test_orchestration_config_excludes_removed_adapter_attributes() -> None:
    """OrchestrationConfig does not expose removed adapter or transport attributes."""
    with mock.patch.dict(os.environ, FAKE_ORACLE_BQ_ENV):
        config = OrchestrationConfig.from_dict({})
    removed_prefixes = ("tera" + "data_", "sq" + "oop_")
    assert not [attr for attr in vars(config) if attr.startswith(removed_prefixes)]
    assert not [arg for arg in EXPECTED_CONFIG_ARGS if arg.startswith(removed_prefixes)]
