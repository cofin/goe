# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for declarative GOESettings and domain config structs."""

from __future__ import annotations

import gc
from pathlib import Path
from unittest import mock

import pytest

from goe.config.settings import (
    BigQueryConfig,
    GOESettings,
    HadoopConfig,
    ListenerConfig,
    ObservabilityConfig,
    OracleConfig,
    SnowflakeConfig,
    SparkTransportConfig,
    SynapseConfig,
)
from goe.exceptions import ConfigurationError


def test_goe_settings_from_env_pure_construction() -> None:
    """GOESettings.from_env constructs all sub-configs purely without DB sockets or Oracle client init."""
    env = {
        "FRONTEND_DISTRIBUTION": "ORACLE",
        "BACKEND_DISTRIBUTION": "GCP",
        "QUERY_ENGINE": "BIGQUERY",
        "OFFLOAD_HOME": "/opt/goe",
        "OFFLOAD_LOGDIR": "/opt/goe/log",
        "OFFLOAD_FS_SCHEME": "gs",
        "OFFLOAD_FS_CONTAINER": "my-bucket",
        "OFFLOAD_FS_PREFIX": "staging/prefix",
        "OFFLOAD_TRANSPORT": "DUCKDB",
        "OFFLOAD_TRANSPORT_PARALLELISM": "8",
        "ORA_ADM_USER": "goe_adm",
        "ORA_ADM_PASS": "secret_adm",
        "ORA_APP_USER": "goe_app",
        "ORA_APP_PASS": "secret_app",
        "ORA_REPO_USER": "goe_repo",
        "ORA_CONN": "dbhost:1521/ORCL",
        "USE_ORACLE_WALLET": "true",
        "GOOGLE_CLOUD_PROJECT": "gcp-proj",
        "BIGQUERY_DATASET_LOCATION": "US",
        "GOOGLE_KMS_KEY_NAME": "projects/p/locations/l/keyRings/r/cryptoKeys/k",
        "GOOGLE_DATAPROC_PROJECT": "dp-proj",
        "GOOGLE_DATAPROC_REGION": "us-central1",
        "GOOGLE_DATAPROC_CLUSTER": "dp-cluster",
        "SNOWFLAKE_ACCOUNT": "acct1",
        "SNOWFLAKE_USER": "sf_user",
        "SNOWFLAKE_PASS": "sf_pass",
        "SNOWFLAKE_WAREHOUSE": "wh1",
        "SNOWFLAKE_ROLE": "role1",
        "SNOWFLAKE_DATABASE": "db1",
        "SYNAPSE_SERVER": "syn.sql.azuresynapse.net",
        "SYNAPSE_DATABASE": "syndb",
        "SYNAPSE_USER": "syn_user",
        "SYNAPSE_PASS": "syn_pass",
        "OFFLOAD_LISTENER_HOST": "127.0.0.1",
        "OFFLOAD_LISTENER_PORT": "8000",
        "OFFLOAD_LISTENER_HTTP_WORKERS": "4",
        "OFFLOAD_LISTENER_SHARED_TOKEN": "tok_secret",
        "OFFLOAD_LISTENER_HEARTBEAT_INTERVAL": "60",
        "GOE_OTEL_ENABLED": "true",
        "GOE_OTEL_SERVICE_NAME": "goe-test",
        "GOE_OTEL_PROTOCOL": "http/protobuf",
        "GOE_OTEL_ENDPOINT": "http://localhost:4318",
        "GOE_OTEL_SAMPLE_RATE": "0.5",
    }
    settings = GOESettings.from_env(environ=env)
    assert not gc.is_tracked(settings)
    assert isinstance(settings.oracle, OracleConfig)
    assert isinstance(settings.bigquery, BigQueryConfig)
    assert isinstance(settings.snowflake, SnowflakeConfig)
    assert isinstance(settings.synapse, SynapseConfig)
    assert isinstance(settings.hadoop, HadoopConfig)
    assert isinstance(settings.spark_transport, SparkTransportConfig)
    assert isinstance(settings.listener, ListenerConfig)
    assert isinstance(settings.observability, ObservabilityConfig)

    assert settings.db_type == "oracle"
    assert settings.target == "bigquery"
    assert settings.offload_fs_scheme == "gs"
    assert settings.offload_fs_container == "my-bucket"
    assert settings.offload_transport_method == "DUCKDB"
    assert settings.offload_transport_parallelism == 8
    assert settings.oracle.adm_user == "goe_adm"
    assert settings.oracle.dsn == "dbhost:1521/ORCL"
    assert settings.oracle.use_oracle_wallet is True
    assert settings.bigquery.project == "gcp-proj"
    assert settings.bigquery.dataset_location == "US"
    assert settings.listener.port == 8000
    assert settings.listener.heartbeat_interval_seconds == 60
    assert settings.observability.enabled is True
    assert settings.observability.exporter_protocol == "http/protobuf"
    assert settings.observability.sample_ratio == 0.5


def test_multi_host_csv_preserved_as_deterministic_tuple() -> None:
    """CSV host lists in HadoopConfig and SparkTransportConfig preserve all hosts in order without random.choice."""
    env = {
        "HIVE_SERVER_HOST": "hs2-a.example.com, hs2-b.example.com, hs2-c.example.com",
        "HDFS_CMD_HOST": "hdfs-1.example.com,hdfs-2.example.com",
        "OFFLOAD_TRANSPORT_CMD_HOST": "spark-1.example.com, spark-2.example.com",
        "OFFLOAD_TRANSPORT_RDBMS_SESSION_PARAMETERS": '{"cell_offload_processing": "false"}',
    }
    first = GOESettings.from_env(environ=env)
    second = GOESettings.from_env(environ=env)
    assert first.hadoop.hive_server_hosts == ("hs2-a.example.com", "hs2-b.example.com", "hs2-c.example.com")
    assert first.hadoop.hdfs_hosts == ("hdfs-1.example.com", "hdfs-2.example.com")
    assert first.spark_transport.cmd_hosts == ("spark-1.example.com", "spark-2.example.com")
    assert first.spark_transport.rdbms_session_parameters == {"cell_offload_processing": "false"}
    assert first == second


@pytest.mark.parametrize(
    "bad_env",
    [
        {"OFFLOAD_LISTENER_PORT": "0"},
        {"OFFLOAD_LISTENER_PORT": "70000"},
        {"OFFLOAD_TRANSPORT_PARALLELISM": "-2"},
        {"GOE_OTEL_SAMPLE_RATE": "1.5"},
        {"OFFLOAD_FS_SCHEME": "maprfs"},
    ],
)
def test_msgspec_meta_constraints_raise_configuration_error(bad_env: dict[str, str]) -> None:
    """Invalid ports, negative parallelism, out-of-range sample ratio, or unsupported schemes raise ConfigurationError."""
    with pytest.raises(ConfigurationError) as exc_info:
        GOESettings.from_env(environ=bad_env)
    assert exc_info.value.exit_code == 2


def test_config_file_discovery_precedence_and_autoload_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GOESettings.from_env honors env_file and GOE_NO_AUTOLOAD_ENV bypass."""
    env_file = tmp_path / "offload.env"
    env_file.write_text("OFFLOAD_LISTENER_PORT=8123\n", encoding="utf-8")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("GOE_NO_AUTOLOAD_ENV", "1")
    monkeypatch.delenv("OFFLOAD_LISTENER_PORT", raising=False)

    with mock.patch("goe.config.settings.load_env") as mock_load:
        settings = GOESettings.from_env()
        mock_load.assert_not_called()
    assert settings.listener.port == 8000

    monkeypatch.delenv("GOE_NO_AUTOLOAD_ENV", raising=False)
    settings_loaded = GOESettings.from_env(env_file=str(env_file))
    assert settings_loaded.listener.port == 8123
    monkeypatch.delenv("OFFLOAD_LISTENER_PORT", raising=False)


def test_with_dfs_override_and_redacted_dict() -> None:
    """with_dfs_override returns a new frozen instance and redacted_dict masks secrets."""
    base = GOESettings.from_env(
        environ={
            "ORA_ADM_PASS": "topsecret",
            "SNOWFLAKE_PASS": "sfsecret",
            "OFFLOAD_LISTENER_SHARED_TOKEN": "toksecret",
            "OFFLOAD_FS_SCHEME": "gs",
            "OFFLOAD_FS_CONTAINER": "bucket-a",
            "OFFLOAD_FS_PREFIX": "pref-a",
        }
    )
    overridden = base.with_dfs_override(scheme="s3a", container="bucket-b", prefix="pref-b")
    assert base.offload_fs_scheme == "gs"
    assert base.offload_fs_container == "bucket-a"
    assert overridden.offload_fs_scheme == "s3a"
    assert overridden.offload_fs_container == "bucket-b"
    assert overridden.offload_fs_prefix == "pref-b"

    redacted = base.redacted_dict()
    assert redacted["oracle"]["adm_pass"] == "***"
    assert redacted["snowflake"]["password"] == "***"
    assert redacted["listener"]["shared_secret"] == "***"
