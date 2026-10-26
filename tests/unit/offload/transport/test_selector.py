# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TransportSelector, protocol structs, and AUTO byte-threshold selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    DBTYPE_BIGQUERY,
    DBTYPE_ORACLE,
    FILE_STORAGE_FORMAT_PARQUET,
    OFFLOAD_TRANSPORT_AUTO,
)
from goe.offload.transport import selector as selector_module
from goe.offload.transport.constants import (
    DEFAULT_DUCKDB_MAX_BYTES,
    DEFAULT_QUERY_IMPORT_MAX_BYTES,
    OFFLOAD_TRANSPORT_METHOD_DUCKDB,
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
)
from goe.offload.transport.protocol import (
    OffloadTransportException,
    OffloadTransportProtocol,
    TransportBatchSplit,
    TransportExecutionSummary,
    TransportPlan,
)
from goe.offload.transport.selector import (
    GCP_AUTO_TRANSPORT_METHODS,
    TransportSelector,
    choose_offload_transport_method,
    validate_offload_transport_method,
)

GIB = 1024 * 1024 * 1024


def test_gcp_auto_order_includes_duckdb_between_query_import_and_spark() -> None:
    """GCP_AUTO_TRANSPORT_METHODS must evaluate QUERY_IMPORT, then DUCKDB, then Spark transports."""
    assert GCP_AUTO_TRANSPORT_METHODS == [
        OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
        OFFLOAD_TRANSPORT_METHOD_DUCKDB,
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    ]


def test_select_transport_method_byte_thresholds() -> None:
    """TransportSelector.select_transport_method routes across <=5GiB, <=100GiB, and >100GiB tiers."""
    assert TransportSelector.select_transport_method(1 * GIB) == OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
    assert TransportSelector.select_transport_method(5 * GIB) == OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
    assert TransportSelector.select_transport_method(10 * GIB) == OFFLOAD_TRANSPORT_METHOD_DUCKDB
    assert TransportSelector.select_transport_method(100 * GIB) == OFFLOAD_TRANSPORT_METHOD_DUCKDB
    assert TransportSelector.select_transport_method(150 * GIB) == OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD


def test_select_transport_method_falls_back_to_spark_when_duckdb_unavailable() -> None:
    """Medium tables fall back to the first available Spark cluster transport when DuckDB is unavailable."""
    selected = TransportSelector.select_transport_method(
        25 * GIB,
        duckdb_available=False,
        available_spark_methods=(
            OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
            OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
        ),
    )
    assert selected == OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD


@pytest.mark.parametrize("removed_method", ["SQOOP", "SQOOP_BY_QUERY", "UNKNOWN_TRANSPORT"])
def test_select_and_validate_reject_removed_sqoop_methods(removed_method: str) -> None:
    """Removed Sqoop transport names must raise OffloadTransportException."""
    with pytest.raises(OffloadTransportException, match=removed_method):
        TransportSelector.select_transport_method(1 * GIB, explicit_method=removed_method)

    with pytest.raises(OffloadTransportException, match=removed_method):
        validate_offload_transport_method(removed_method, _build_gcp_config())


def test_choose_offload_transport_method_routes_small_medium_large_on_gcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """choose_offload_transport_method selects QUERY_IMPORT for small, DUCKDB for medium, and Spark for large tables."""
    monkeypatch.setattr(selector_module, "spark_submit_executable_exists", lambda *a, **kw: True)
    config = _build_gcp_config()
    op = _build_operation()
    messages = _build_messages()

    assert (
        choose_offload_transport_method(op, _build_table(1 * GIB), config, messages)
        == OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
    )
    assert (
        choose_offload_transport_method(op, _build_table(20 * GIB), config, messages) == OFFLOAD_TRANSPORT_METHOD_DUCKDB
    )
    assert (
        choose_offload_transport_method(op, _build_table(200 * GIB), config, messages)
        == OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD
    )


def test_transport_protocol_and_frozen_structs() -> None:
    """TransportBatchSplit, TransportPlan, and TransportExecutionSummary are frozen structs."""
    split = TransportBatchSplit(split_id=0, predicate="MOD(ORA_HASH(ID, 3), 4) = 0")
    plan = TransportPlan(
        method=OFFLOAD_TRANSPORT_METHOD_DUCKDB,
        parallelism=4,
        staging_format=FILE_STORAGE_FORMAT_PARQUET,
        target_uris=("gs://bucket/path/part-0.parquet",),
        splits=(split,),
    )
    summary = TransportExecutionSummary(
        method=OFFLOAD_TRANSPORT_METHOD_DUCKDB,
        rows_transported=1250,
        bytes_staged=65536,
        files_written=1,
        elapsed_seconds=0.42,
    )
    assert plan.splits[0].split_id == 0
    assert summary.rows_transported == 1250

    class _DummyTransport:
        def transport(self, partition_chunk: object = None) -> int | None:
            return 10

        def ping_source_rdbms(self) -> bool:
            return True

    assert isinstance(_DummyTransport(), OffloadTransportProtocol)


def _build_gcp_config(
    *,
    small_table_threshold: int = DEFAULT_QUERY_IMPORT_MAX_BYTES,
    duckdb_max_bytes: int = DEFAULT_DUCKDB_MAX_BYTES,
) -> SimpleNamespace:
    return SimpleNamespace(
        db_type=DBTYPE_ORACLE,
        target=DBTYPE_BIGQUERY,
        backend_distribution=BACKEND_DISTRO_GCP,
        offload_transport=OFFLOAD_TRANSPORT_AUTO,
        offload_staging_format=FILE_STORAGE_FORMAT_PARQUET,
        offload_fs_scheme="gs",
        offload_transport_small_table_threshold=small_table_threshold,
        offload_transport_duckdb_max_bytes=duckdb_max_bytes,
        offload_transport_duckdb_version=None,
        offload_transport_cmd_host="localhost",
        offload_transport_user="goe",
        offload_transport_spark_submit_executable="spark-submit",
        offload_transport_spark_thrift_host=None,
        offload_transport_spark_thrift_port=None,
        offload_transport_livy_api_url=None,
        google_dataproc_cluster="dataproc-cluster",
        google_dataproc_batches_version=None,
    )


def _build_operation(
    *,
    method: str | None = None,
    small_table_threshold: int = DEFAULT_QUERY_IMPORT_MAX_BYTES,
) -> SimpleNamespace:
    return SimpleNamespace(
        offload_transport_method=method,
        offload_transport_small_table_threshold=small_table_threshold,
    )


def _build_table(size_in_bytes: int, data_types: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        size_in_bytes=size_in_bytes,
        data_types_in_use=lambda: data_types or ["NUMBER", "VARCHAR2"],
    )


def _build_messages() -> SimpleNamespace:
    return SimpleNamespace(log=lambda *args, **kwargs: None)
