# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Registration, eligibility and factory wiring for the opt-in DUCKDB transport."""

from unittest.mock import MagicMock, patch

import pytest

from goe.offload.offload_constants import OFFLOAD_TRANSPORT_DUCKDB
from goe.offload.oracle.oracle_column import ORACLE_TYPE_CLOB, ORACLE_TYPE_NUMBER, ORACLE_TYPE_VARCHAR2
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_GOE_METHODS,
    VALID_OFFLOAD_TRANSPORT_METHODS,
    VALID_OFFLOAD_TRANSPORTS,
)
from goe.offload.transport.duckdb_availability import is_duckdb_available
from goe.offload.transport.duckdb_constants import OFFLOAD_TRANSPORT_METHOD_DUCKDB
from goe.offload.transport.factory import (
    GCP_AUTO_TRANSPORT_METHODS,
    choose_offload_transport_method,
    offload_transport_factory,
    validate_offload_transport_method,
)
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_duckdb_is_registered_but_never_automatic() -> None:
    """DUCKDB is a valid method and rule set but not part of any AUTO candidate list."""
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB in VALID_OFFLOAD_TRANSPORT_METHODS
    assert OFFLOAD_TRANSPORT_DUCKDB in VALID_OFFLOAD_TRANSPORTS
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB not in OFFLOAD_TRANSPORT_GOE_METHODS
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB not in GCP_AUTO_TRANSPORT_METHODS


def test_eligible_offload_validates() -> None:
    """An eligible BigQuery/GCS/Parquet offload passes validate_offload_transport_method."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    validate_offload_transport_method(OFFLOAD_TRANSPORT_METHOD_DUCKDB, config, MagicMock(), _table(), MagicMock())


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("target", "snowflake", "BigQuery"),
        ("offload_fs_scheme", "s3a", "OFFLOAD_FS_SCHEME"),
        ("offload_staging_format", "AVRO", "PARQUET"),
        ("use_oracle_wallet", True, "user/password"),
        ("offload_transport_dsn", "PRODDB_TNS_ALIAS", "EZConnect"),
        ("offload_transport_duckdb_version", "1.4.3", "OFFLOAD_TRANSPORT_DUCKDB_VERSION"),
    ],
)
def test_config_rejections_are_logged(attribute: str, value: object, reason: str) -> None:
    """Each ineligible configuration returns False and logs why at VVERBOSE."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    setattr(config, attribute, value)
    messages = MagicMock()
    assert is_duckdb_available(MagicMock(), config, offload_source_table=_table(), messages=messages) is False
    assert reason in messages.log.call_args.args[0]


def test_table_rejections() -> None:
    """Oversized tables and LOB/LONG/RAW/XMLTYPE columns are ineligible."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    oversized = _table(size=config.offload_transport_duckdb_max_bytes + 1)
    assert is_duckdb_available(MagicMock(), config, offload_source_table=oversized) is False
    lob_table = _table(types={ORACLE_TYPE_NUMBER, ORACLE_TYPE_CLOB})
    messages = MagicMock()
    assert is_duckdb_available(MagicMock(), config, offload_source_table=lob_table, messages=messages) is False
    assert ORACLE_TYPE_CLOB in messages.log.call_args.args[0]


def test_offload_transport_duckdb_rule_set_selects_duckdb() -> None:
    """OFFLOAD_TRANSPORT=DUCKDB selects DUCKDB when eligible."""
    config = build_mock_options({**FAKE_ORACLE_BQ_ENV, "OFFLOAD_TRANSPORT": "DUCKDB"})
    operation = MagicMock(offload_transport_method=None)
    assert choose_offload_transport_method(operation, _table(), config, MagicMock()) == OFFLOAD_TRANSPORT_METHOD_DUCKDB


def test_auto_never_evaluates_duckdb() -> None:
    """AUTO selection on GCP never calls the DUCKDB availability gate."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    operation = MagicMock(offload_transport_method=None)
    with (
        patch("goe.offload.transport.factory.is_duckdb_available") as duckdb_gate,
        patch("goe.offload.transport.factory.is_query_import_available", return_value=True),
    ):
        choose_offload_transport_method(operation, _table(), config, MagicMock())
    duckdb_gate.assert_not_called()


def test_factory_builds_duckdb_transport() -> None:
    """offload_transport_factory constructs OffloadTransportDuckDB for the DUCKDB method."""
    args = [MagicMock() for _ in range(6)]
    with patch("goe.offload.transport.factory.OffloadTransportDuckDB") as transport_cls:
        assert offload_transport_factory(OFFLOAD_TRANSPORT_METHOD_DUCKDB, *args) is transport_cls.return_value
    transport_cls.assert_called_once_with(*args)


def _table(size: int = 1024, types: set[str] | None = None) -> MagicMock:
    """Return a source table stand-in."""
    table = MagicMock(size_in_bytes=size)
    table.data_types_in_use.return_value = types or {ORACLE_TYPE_NUMBER, ORACLE_TYPE_VARCHAR2}
    return table
