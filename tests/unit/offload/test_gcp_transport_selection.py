# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for GCP AUTO transport selection priority and fallthrough."""

from types import SimpleNamespace

import pytest

from goe.offload.offload_constants import (
    BACKEND_DISTRO_CDH,
    BACKEND_DISTRO_GCP,
    DBTYPE_ORACLE,
    FILE_STORAGE_FORMAT_PARQUET,
    OFFLOAD_TRANSPORT_AUTO,
    OFFLOAD_TRANSPORT_GCP,
)
from goe.offload.transport import selector as transport_selector
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_GCP_METHODS,
    OFFLOAD_TRANSPORT_GOE_METHODS,
    OFFLOAD_TRANSPORT_METHOD_DUCKDB,
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
)
from goe.offload.transport.protocol import OffloadTransportException
from goe.offload.transport.selector import (
    GCP_AUTO_TRANSPORT_METHODS,
    choose_offload_transport_method,
)


def test_gcp_auto_order():
    assert GCP_AUTO_TRANSPORT_METHODS == [
        OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
        OFFLOAD_TRANSPORT_METHOD_DUCKDB,
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    ]


def test_gcp_auto_fallthrough(monkeypatch):
    availability = {}
    monkeypatch.setattr(
        transport_selector,
        "is_query_import_available",
        lambda *a, **kw: availability[OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT],
    )
    monkeypatch.setattr(
        transport_selector,
        "is_duckdb_available",
        lambda *a, **kw: availability[OFFLOAD_TRANSPORT_METHOD_DUCKDB],
    )
    monkeypatch.setattr(
        transport_selector,
        "is_spark_gcloud_dataproc_available",
        lambda *a, **kw: availability[OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD],
    )
    monkeypatch.setattr(
        transport_selector,
        "is_spark_gcloud_batches_available",
        lambda *a, **kw: availability[OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD],
    )
    monkeypatch.setattr(
        transport_selector,
        "is_spark_submit_available",
        lambda *a, **kw: availability[OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT],
    )
    monkeypatch.setattr(
        transport_selector,
        "is_spark_thrift_available",
        lambda *a, **kw: availability[OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT],
    )
    monkeypatch.setattr(
        transport_selector,
        "is_livy_available",
        lambda *a, **kw: availability[OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY],
    )

    cfg = _gcp_config()
    op = _op()
    tbl = _table()
    msgs = _messages()

    for idx, expected in enumerate(GCP_AUTO_TRANSPORT_METHODS):
        for m in GCP_AUTO_TRANSPORT_METHODS[:idx]:
            availability[m] = False
        for m in GCP_AUTO_TRANSPORT_METHODS[idx:]:
            availability[m] = True
        assert choose_offload_transport_method(op, tbl, cfg, msgs) == expected

    for m in GCP_AUTO_TRANSPORT_METHODS:
        availability[m] = False
    with pytest.raises(OffloadTransportException):
        choose_offload_transport_method(op, tbl, cfg, msgs)


def test_gcp_small_table_picks_query_import_large_picks_dataproc(monkeypatch):
    monkeypatch.setattr(transport_selector, "spark_submit_executable_exists", lambda *a, **kw: True)
    monkeypatch.setattr(transport_selector, "is_duckdb_available", lambda *a, **kw: False)
    cfg = _gcp_config()
    op = _op(small_table_threshold=100)
    msgs = _messages()

    assert choose_offload_transport_method(op, _table(50), cfg, msgs) == OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
    assert choose_offload_transport_method(op, _table(500), cfg, msgs) == OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD


def test_non_gcp_auto_keeps_goe_first(monkeypatch):
    cfg = _gcp_config()
    cfg.backend_distribution = BACKEND_DISTRO_CDH
    monkeypatch.setattr(transport_selector, "is_spark_thrift_available", lambda *a, **kw: True)
    monkeypatch.setattr(transport_selector, "is_query_import_available", lambda *a, **kw: True)
    assert choose_offload_transport_method(_op(), _table(10), cfg, _messages()) == OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT
    assert OFFLOAD_TRANSPORT_GOE_METHODS[0] == OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT


def test_explicit_gcp_transport_restricts_to_dataproc(monkeypatch):
    monkeypatch.setattr(transport_selector, "spark_submit_executable_exists", lambda *a, **kw: True)
    cfg = _gcp_config(offload_transport=OFFLOAD_TRANSPORT_GCP)
    assert choose_offload_transport_method(_op(), _table(10), cfg, _messages()) in OFFLOAD_TRANSPORT_GCP_METHODS


def _gcp_config(offload_transport=OFFLOAD_TRANSPORT_AUTO):
    return SimpleNamespace(
        db_type=DBTYPE_ORACLE,
        backend_distribution=BACKEND_DISTRO_GCP,
        offload_transport=offload_transport,
        offload_staging_format=FILE_STORAGE_FORMAT_PARQUET,
        offload_transport_cmd_host="localhost",
        offload_transport_user="goe",
        offload_transport_spark_submit_executable="spark-submit",
        offload_transport_spark_thrift_host="thrift.internal",
        offload_transport_spark_thrift_port=10000,
        offload_transport_livy_api_url="http://livy.internal:8998",
        google_dataproc_cluster="cluster-a",
        google_dataproc_batches_version="2.1",
    )


def _op(method=None, small_table_threshold=100):
    return SimpleNamespace(
        offload_transport_method=method,
        offload_transport_small_table_threshold=small_table_threshold,
    )


def _table(size_in_bytes=10):
    return SimpleNamespace(size_in_bytes=size_in_bytes)


def _messages():
    return SimpleNamespace(log=lambda *a, **kw: None)
