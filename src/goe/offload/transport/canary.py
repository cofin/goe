# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unified transport connectivity canary probe replacing per-transport *Canary subclasses."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from goe.offload.offload_messages import VVERBOSE
from goe.offload.registry import create_transport_rdbms_api
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
from goe.offload.transport.spark.dataproc import (
    OffloadTransportSparkBatchesGcloud,
    OffloadTransportSparkDataprocGcloud,
)
from goe.offload.transport.spark.spark_livy import OffloadTransportSparkLivy
from goe.offload.transport.spark.spark_submit import OffloadTransportSparkSubmit
from goe.offload.transport.spark.spark_thrift import OffloadTransportSparkThrift
from goe.typing import FrozenBaseStruct


class TransportCanaryResult(FrozenBaseStruct, frozen=True):
    """Structured result of a transport RDBMS connectivity canary probe."""

    method: str
    ok: bool
    elapsed_seconds: float = 0.0
    details: str = ""
    error: str | None = None


class TransportCanaryProbe:
    """Unified connectivity canary probe across Spark, Query Import, and DuckDB transports."""

    def __init__(
        self,
        method: str,
        offload_options: Any = None,
        messages: Any = None,
        *,
        probe_fn: Callable[[], bool] | None = None,
    ) -> None:
        if method not in VALID_OFFLOAD_TRANSPORT_METHODS:
            raise OffloadTransportException(f"Unsupported transport method for canary probe: {method}")
        self.method = method
        self._offload_options = offload_options
        self._messages = messages
        self._probe_fn = probe_fn

    def probe(self) -> TransportCanaryResult:
        """Execute the connectivity probe and return a structured TransportCanaryResult."""
        started = time.perf_counter()
        try:
            ok = bool(self._execute_probe())
            elapsed = time.perf_counter() - started
            return TransportCanaryResult(
                method=self.method,
                ok=ok,
                elapsed_seconds=elapsed,
                details=f"{self.method} RDBMS connectivity check {'succeeded' if ok else 'failed'}",
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            return TransportCanaryResult(
                method=self.method,
                ok=False,
                elapsed_seconds=elapsed,
                details=f"{self.method} RDBMS connectivity check raised {type(exc).__name__}",
                error=str(exc),
            )

    def ping(self) -> bool:
        """Execute the connectivity probe and return True on success, raising on unhandled errors."""
        return bool(self._execute_probe())

    def ping_source_rdbms(self) -> bool:
        """Execute the RDBMS connectivity probe for goe connect compatibility."""
        return self.ping()

    def _execute_probe(self) -> bool:
        if self._probe_fn is not None:
            return bool(self._probe_fn())

        if self.method == OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT:
            return OffloadTransportSparkThrift.for_canary(self._offload_options, self._messages).ping_source_rdbms()
        if self.method == OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT:
            return OffloadTransportSparkSubmit.for_canary(self._offload_options, self._messages).ping_source_rdbms()
        if self.method == OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY:
            return OffloadTransportSparkLivy.for_canary(self._offload_options, self._messages).ping_source_rdbms()
        if self.method == OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD:
            return OffloadTransportSparkDataprocGcloud.for_canary(
                self._offload_options, self._messages
            ).ping_source_rdbms()
        if self.method == OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD:
            return OffloadTransportSparkBatchesGcloud.for_canary(
                self._offload_options, self._messages
            ).ping_source_rdbms()
        if self.method in (OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT, OFFLOAD_TRANSPORT_METHOD_DUCKDB):
            rdbms_api = create_transport_rdbms_api(
                "dummy_owner",
                "dummy_table",
                self._offload_options,
                self._messages,
                dry_run=False,
            )
            return bool(rdbms_api.get_rdbms_canary_query())
        raise OffloadTransportException(f"Unsupported transport method for canary probe: {self.method}")


def spark_thrift_jdbc_connectivity_checker(offload_options: Any, messages: Any) -> TransportCanaryProbe:
    """Return a TransportCanaryProbe for Spark Thrift Server RDBMS connectivity."""
    if messages:
        messages.log("Invoking TransportCanaryProbe(SPARK_THRIFT)", detail=VVERBOSE)
    return TransportCanaryProbe(OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT, offload_options, messages)


def spark_submit_jdbc_connectivity_checker(offload_options: Any, messages: Any) -> TransportCanaryProbe:
    """Return a TransportCanaryProbe for Spark Submit RDBMS connectivity."""
    if messages:
        messages.log("Invoking TransportCanaryProbe(SPARK_SUBMIT)", detail=VVERBOSE)
    return TransportCanaryProbe(OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT, offload_options, messages)


def spark_livy_jdbc_connectivity_checker(offload_options: Any, messages: Any) -> TransportCanaryProbe:
    """Return a TransportCanaryProbe for Spark Livy RDBMS connectivity."""
    if messages:
        messages.log("Invoking TransportCanaryProbe(SPARK_LIVY)", detail=VVERBOSE)
    return TransportCanaryProbe(OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY, offload_options, messages)


def spark_dataproc_jdbc_connectivity_checker(offload_options: Any, messages: Any) -> TransportCanaryProbe:
    """Return a TransportCanaryProbe for Managed Spark Dataproc cluster RDBMS connectivity."""
    if messages:
        messages.log("Invoking TransportCanaryProbe(SPARK_DATAPROC_GCLOUD)", detail=VVERBOSE)
    return TransportCanaryProbe(OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD, offload_options, messages)


def spark_dataproc_batches_jdbc_connectivity_checker(offload_options: Any, messages: Any) -> TransportCanaryProbe:
    """Return a TransportCanaryProbe for Managed Spark Serverless Batches RDBMS connectivity."""
    if messages:
        messages.log("Invoking TransportCanaryProbe(SPARK_BATCHES_GCLOUD)", detail=VVERBOSE)
    return TransportCanaryProbe(OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD, offload_options, messages)


__all__ = [
    "TransportCanaryProbe",
    "TransportCanaryResult",
    "spark_dataproc_batches_jdbc_connectivity_checker",
    "spark_dataproc_jdbc_connectivity_checker",
    "spark_livy_jdbc_connectivity_checker",
    "spark_submit_jdbc_connectivity_checker",
    "spark_thrift_jdbc_connectivity_checker",
]
