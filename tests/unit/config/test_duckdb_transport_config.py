# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OFFLOAD_TRANSPORT_DUCKDB_* configuration defaults and validation."""

import pytest

from goe.config.config_validation_functions import OrchestrationConfigException
from goe.config.orchestration_config import OrchestrationConfig
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_duckdb_transport_defaults() -> None:
    """Defaults match the DuckDB 2.0 community oracle extension and 100G table limit."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    assert config.offload_transport_duckdb_version == "2.0.0"
    assert config.offload_transport_duckdb_extension_path is None
    assert config.offload_transport_duckdb_extension_dir is None
    assert config.offload_transport_duckdb_extension_repository == "community"
    assert config.offload_transport_duckdb_threads == 2
    assert config.offload_transport_duckdb_memory_limit == "2GB"
    assert config.offload_transport_duckdb_temp_directory == "/tmp/offload/run/duckdb"
    assert config.offload_transport_duckdb_max_bytes == 100 * 1024**3


def test_duckdb_transport_overrides() -> None:
    """Environment overrides are honoured and sizes are normalised to bytes."""
    env = {
        **FAKE_ORACLE_BQ_ENV,
        "OFFLOAD_TRANSPORT_DUCKDB_THREADS": "4",
        "OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES": "512M",
        "OFFLOAD_TRANSPORT_DUCKDB_EXTENSION_DIR": "/opt/goe/duckdb_extensions",
        "OFFLOAD_TRANSPORT_DUCKDB_TEMP_DIRECTORY": "/var/tmp/goe_duckdb",
    }
    config = build_mock_options(env)
    assert config.offload_transport_duckdb_threads == 4
    assert config.offload_transport_duckdb_max_bytes == 512 * 1024**2
    assert config.offload_transport_duckdb_extension_dir == "/opt/goe/duckdb_extensions"
    assert config.offload_transport_duckdb_temp_directory == "/var/tmp/goe_duckdb"


@pytest.mark.parametrize(
    ("name", "value"), [("OFFLOAD_TRANSPORT_DUCKDB_THREADS", "0"), ("OFFLOAD_TRANSPORT_DUCKDB_MAX_BYTES", "lots")]
)
def test_duckdb_transport_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    """Non-positive thread counts and malformed sizes are rejected."""
    for key, val in {**FAKE_ORACLE_BQ_ENV, name: value}.items():
        if val is not None:
            monkeypatch.setenv(key, str(val))
    with pytest.raises(OrchestrationConfigException, match=name):
        OrchestrationConfig.from_dict({"verbose": False})
