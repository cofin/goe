# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for DUCKDB transport registration and AUTO selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    DBTYPE_BIGQUERY,
    DBTYPE_ORACLE,
    DBTYPE_SNOWFLAKE,
    FILE_STORAGE_FORMAT_PARQUET,
    OFFLOAD_TRANSPORT_AUTO,
    OFFLOAD_TRANSPORT_DUCKDB,
)
from goe.offload.registry import ADAPTER_REGISTRY, AdapterKind
from goe.offload.transport.constants import (
    DEFAULT_DUCKDB_MAX_BYTES,
    OFFLOAD_TRANSPORT_GCP_METHODS,
    OFFLOAD_TRANSPORT_GOE_METHODS,
    OFFLOAD_TRANSPORT_SPARK_METHODS,
    VALID_OFFLOAD_TRANSPORT_METHODS,
    VALID_OFFLOAD_TRANSPORTS,
)
from goe.offload.transport.duckdb_constants import (
    OFFLOAD_TRANSPORT_METHOD_DUCKDB,
)
from goe.offload.transport.duckdb_transport import OffloadTransportDuckDB
from goe.offload.transport.protocol import OffloadTransportException
from goe.offload.transport.selector import (
    GCP_AUTO_TRANSPORT_METHODS,
    choose_offload_transport_method,
    validate_offload_transport_method,
)


def test_duckdb_is_registered_and_part_of_auto_selection() -> None:
    """DUCKDB is registered in ADAPTER_REGISTRY and included in GCP_AUTO_TRANSPORT_METHODS and GOE_METHODS."""
    assert OFFLOAD_TRANSPORT_DUCKDB in VALID_OFFLOAD_TRANSPORTS
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB in VALID_OFFLOAD_TRANSPORT_METHODS
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB in GCP_AUTO_TRANSPORT_METHODS
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB in OFFLOAD_TRANSPORT_GOE_METHODS
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB not in OFFLOAD_TRANSPORT_SPARK_METHODS
    assert OFFLOAD_TRANSPORT_METHOD_DUCKDB not in OFFLOAD_TRANSPORT_GCP_METHODS
    assert ADAPTER_REGISTRY.resolve(AdapterKind.TRANSPORT, OFFLOAD_TRANSPORT_METHOD_DUCKDB) is OffloadTransportDuckDB


def test_auto_selects_duckdb_when_query_import_exceeded() -> None:
    """AUTO chooses DUCKDB on GCP BigQuery when table size exceeds small_table_threshold."""
    cfg = _config(offload_transport=OFFLOAD_TRANSPORT_AUTO)
    chosen = choose_offload_transport_method(
        _operation(small_table_threshold=100),
        _table(size_in_bytes=1024),
        cfg,
        MagicMock(),
    )
    assert chosen == OFFLOAD_TRANSPORT_METHOD_DUCKDB


def test_explicit_duckdb_transport_config_selects_duckdb() -> None:
    """OFFLOAD_TRANSPORT=DUCKDB chooses DUCKDB when eligible and raises when not."""
    chosen = choose_offload_transport_method(_operation(), _table(), _config(), MagicMock())
    assert chosen == OFFLOAD_TRANSPORT_METHOD_DUCKDB

    with pytest.raises(OffloadTransportException, match="No valid transport methods"):
        choose_offload_transport_method(_operation(), _table(), _config(target=DBTYPE_SNOWFLAKE), MagicMock())


def test_explicit_operation_method_selects_and_validates_duckdb() -> None:
    """Operation-level --offload-transport-method=DUCKDB validates and selects DUCKDB even under AUTO."""
    cfg = _config(offload_transport=OFFLOAD_TRANSPORT_AUTO)
    op = _operation(method=OFFLOAD_TRANSPORT_METHOD_DUCKDB)
    validate_offload_transport_method(OFFLOAD_TRANSPORT_METHOD_DUCKDB, cfg, op, _table(), MagicMock())
    assert choose_offload_transport_method(op, _table(), cfg, MagicMock()) == OFFLOAD_TRANSPORT_METHOD_DUCKDB

    with pytest.raises(OffloadTransportException, match="incompatible"):
        validate_offload_transport_method(
            OFFLOAD_TRANSPORT_METHOD_DUCKDB,
            _config(target=DBTYPE_SNOWFLAKE, offload_transport=OFFLOAD_TRANSPORT_AUTO),
            op,
            _table(),
            MagicMock(),
        )


def _config(
    target: str = DBTYPE_BIGQUERY,
    offload_transport: str = OFFLOAD_TRANSPORT_DUCKDB,
) -> SimpleNamespace:
    return SimpleNamespace(
        db_type=DBTYPE_ORACLE,
        target=target,
        backend_distribution=BACKEND_DISTRO_GCP,
        offload_transport=offload_transport,
        offload_staging_format=FILE_STORAGE_FORMAT_PARQUET,
        offload_fs_scheme="gs",
        offload_transport_duckdb_version=None,
        offload_transport_duckdb_max_bytes=DEFAULT_DUCKDB_MAX_BYTES,
        offload_transport_cmd_host=None,
        offload_transport_spark_thrift_host=None,
        offload_transport_spark_thrift_port=None,
        offload_transport_livy_api_url=None,
        google_dataproc_cluster=None,
        google_dataproc_batches_version=None,
    )


def _operation(method: str | None = None, small_table_threshold: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        offload_transport_method=method,
        offload_transport_small_table_threshold=small_table_threshold,
    )


def _table(size_in_bytes: int = 1024) -> SimpleNamespace:
    return SimpleNamespace(size_in_bytes=size_in_bytes, data_types_in_use=lambda: ["NUMBER"])
