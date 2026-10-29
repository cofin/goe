# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for DuckDB 2.0 availability and static eligibility checks."""

from unittest.mock import MagicMock

import pytest

from goe.offload.oracle.oracle_column import ORACLE_TYPE_NUMBER, ORACLE_TYPE_RAW, ORACLE_TYPE_VARCHAR2
from goe.offload.transport.duckdb_availability import duckdb_unavailable_reason, is_duckdb_available
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_duckdb_availability_accepts_duckdb2_wallet_tns_and_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    """duckdb_unavailable_reason accepts DuckDB >= 2.0.0, Oracle Wallet, TNS aliases, RAW, and cloud schemes."""
    monkeypatch.setattr("goe.offload.transport.duckdb_availability.duckdb.__version__", "2.0.0")
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    config.use_oracle_wallet = True
    config.offload_transport_auth_using_oracle_wallet = True
    config.offload_transport_dsn = "PRODDB_TNS_ALIAS"

    table = MagicMock(size_in_bytes=10 * 1024**3)
    table.data_types_in_use.return_value = {ORACLE_TYPE_NUMBER, ORACLE_TYPE_VARCHAR2, ORACLE_TYPE_RAW}

    for scheme in ("gs", "s3", "s3a", "az", "abfs", "abfss", "wasb", "wasbs"):
        config.offload_fs_scheme = scheme
        assert duckdb_unavailable_reason(config, table) is None
        assert is_duckdb_available(MagicMock(), config, offload_source_table=table) is True


def test_duckdb_availability_rejects_pre_2_0_duckdb(monkeypatch: pytest.MonkeyPatch) -> None:
    """duckdb_unavailable_reason rejects runtime DuckDB versions older than 2.0.0."""
    monkeypatch.setattr("goe.offload.transport.duckdb_availability.duckdb.__version__", "1.5.5")
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    reason = duckdb_unavailable_reason(config)
    assert reason is not None
    assert "OFFLOAD_TRANSPORT_DUCKDB_VERSION" in reason
