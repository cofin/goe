# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TransportCanaryProbe and create_transport_canary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from goe.offload.registry import AdapterNotRegisteredError, create_transport_canary
from goe.offload.transport.canary import (
    TransportCanaryProbe,
    TransportCanaryResult,
    spark_dataproc_batches_jdbc_connectivity_checker,
    spark_dataproc_jdbc_connectivity_checker,
    spark_livy_jdbc_connectivity_checker,
    spark_submit_jdbc_connectivity_checker,
    spark_thrift_jdbc_connectivity_checker,
)
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_METHOD_DUCKDB,
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    VALID_OFFLOAD_TRANSPORT_METHODS,
)
from goe.offload.transport.protocol import OffloadTransportException


@pytest.mark.parametrize("method", VALID_OFFLOAD_TRANSPORT_METHODS)
def test_canary_probe_succeeds_across_all_registered_methods(method: str) -> None:
    """TransportCanaryProbe and create_transport_canary succeed across every registered transport method."""
    probe = create_transport_canary(method, probe_fn=lambda: True)
    assert isinstance(probe, TransportCanaryProbe)
    result = probe.probe()
    assert isinstance(result, TransportCanaryResult)
    assert result.method == method
    assert result.ok is True
    assert result.error is None
    assert probe.ping() is True
    assert probe.ping_source_rdbms() is True


def test_canary_probe_captures_failure_and_exception() -> None:
    """TransportCanaryProbe.probe() captures False returns and raised exceptions cleanly."""
    false_probe = TransportCanaryProbe(OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT, probe_fn=lambda: False)
    false_res = false_probe.probe()
    assert false_res.ok is False
    assert false_res.error is None

    def _boom() -> bool:
        raise RuntimeError("JDBC timeout")

    err_probe = TransportCanaryProbe(OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT, probe_fn=_boom)
    err_res = err_probe.probe()
    assert err_res.ok is False
    assert err_res.error == "JDBC timeout"


def test_canary_probe_rejects_unknown_transport_method() -> None:
    """TransportCanaryProbe and create_transport_canary reject unknown transport methods."""
    with pytest.raises(OffloadTransportException, match="SQOOP"):
        TransportCanaryProbe("SQOOP")

    with pytest.raises(AdapterNotRegisteredError):
        create_transport_canary("SQOOP")


def test_jdbc_connectivity_checker_helpers_return_canary_probes() -> None:
    """Connectivity checker helper functions return TransportCanaryProbe instances for each Spark method."""
    messages = SimpleNamespace(log=lambda *a, **kw: None)
    options = SimpleNamespace()

    assert spark_thrift_jdbc_connectivity_checker(options, messages).method == OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT
    assert spark_submit_jdbc_connectivity_checker(options, messages).method == OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT
    assert spark_livy_jdbc_connectivity_checker(options, messages).method == OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY
    assert (
        spark_dataproc_jdbc_connectivity_checker(options, messages).method
        == OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD
    )
    assert (
        spark_dataproc_batches_jdbc_connectivity_checker(options, messages).method
        == OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD
    )


def test_canary_probe_default_query_import_and_duckdb_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default probe execution for QUERY_IMPORT and DUCKDB queries the transport RDBMS API."""
    monkeypatch.setattr(
        "goe.offload.transport.canary.create_transport_rdbms_api",
        lambda *a, **kw: SimpleNamespace(get_rdbms_canary_query=lambda: "SELECT 1 FROM DUAL"),
    )
    for method in (OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT, OFFLOAD_TRANSPORT_METHOD_DUCKDB):
        probe = TransportCanaryProbe(method, offload_options=SimpleNamespace(), messages=SimpleNamespace())
        assert probe.ping() is True
