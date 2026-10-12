# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for goe.observability.metrics.GOEMetrics."""

from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from goe.observability.metrics import METRIC_NAMES, GOEMetrics


def test_all_eight_instruments_record() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics = GOEMetrics(provider.get_meter("test"))
    metrics.record_command("OFFLOAD", "success", "bigquery", False, 2.5)
    metrics.record_step("stage_data", "OFFLOAD", "success", True, 1.0)
    metrics.record_transport("QUERY_IMPORT", "bigquery", "SH", 100, 4096, "PARQUET", "gs")
    metrics.record_bytes_loaded("bigquery", 2048)
    metrics.record_bigquery_job("query", "proj", 1024, 55)
    points = _collect(reader)
    assert set(points) == set(METRIC_NAMES)
    assert points["goe.offload.rows_transported"][0].value == 100
    assert points["goe.bigquery.slot_ms"][0].value == 55
    assert dict(points["goe.commands.total"][0].attributes)["command_type"] == "OFFLOAD"


def test_none_and_non_positive_values_are_skipped() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics = GOEMetrics(provider.get_meter("test"))
    metrics.record_transport("QUERY_IMPORT", "bigquery", "SH", None, 0, "PARQUET", "gs")
    metrics.record_bytes_loaded("bigquery", None)
    metrics.record_bigquery_job("query", "proj", None, 0)
    assert _collect(reader) == {}


def test_noop_meter_accepts_all_calls() -> None:
    metrics = GOEMetrics(NoOpMeterProvider().get_meter("test"))
    metrics.record_command("OFFLOAD", "error", "", True, -1.0)
    metrics.record_step("stage_data", "", "skipped", False, 0.0)


def _collect(reader: InMemoryMetricReader) -> dict[str, list]:
    """Return data points keyed by metric name from an in-memory reader."""
    points: dict[str, list] = {}
    data = reader.get_metrics_data()
    if data is None:
        return points
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.data.data_points:
                    points[metric.name] = list(metric.data.data_points)
    return points
