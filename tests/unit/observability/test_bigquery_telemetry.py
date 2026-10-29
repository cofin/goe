# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for BigQuery job telemetry."""

import re
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from google.cloud import bigquery
from opentelemetry.trace import SpanKind

from goe.observability import runtime
from goe.observability.bigquery import merge_trace_labels
from goe.observability.config import ObservabilitySettings
from goe.observability.spans import traced_command, traced_step
from goe.offload.backend_cache import CachedBackendCatalog
from goe.offload.bigquery.bigquery_backend_api import BackendBigQueryApi, sanitize_bigquery_label_value
from goe.offload.bigquery.bigquery_backend_table import BackendBigQueryTable
from goe.offload.offload_constants import FILE_STORAGE_FORMAT_PARQUET

EXEC_ID = "2f1b7c1e-0000-4000-8000-000000000070"
LABEL_RE = re.compile(r"^[a-z0-9_-]{0,63}$")


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime for one test."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_trace_labels_merge(memory_runtime: runtime.ObservabilityRuntime) -> None:
    with traced_command("OFFLOAD", EXEC_ID):
        with traced_step("create_backend_table", "CREATE_TABLE", "Create backend table"):
            labels = merge_trace_labels({"goe_command": "offload"}, sanitize_bigquery_label_value)
    assert labels["goe_command"] == "offload"
    assert labels["goe_step"] == "create_backend_table"
    assert labels["goe_execution_id"] == EXEC_ID
    assert len(labels["goe_trace_id"]) == 32
    assert all(LABEL_RE.match(value) for value in labels.values())


def test_ddl_span_and_metrics(memory_runtime: runtime.ObservabilityRuntime) -> None:
    query_job = MagicMock(
        job_id="job_1",
        state="DONE",
        location="US",
        project="goe-proj",
        statement_type="INSERT",
        total_bytes_processed=2048,
        total_bytes_billed=10485760,
        slot_millis=55,
        num_dml_affected_rows=3,
    )
    with traced_command("OFFLOAD", EXEC_ID):
        _api(query_job)._execute_ddl_or_dml("INSERT INTO t SELECT 1")
    span = next(s for s in memory_runtime.get_finished_spans() if s.name == "goe.backend.bigquery.ddl_dml")
    assert span.kind == SpanKind.CLIENT
    assert span.attributes["goe.bigquery.job_id"] == "job_1"
    assert span.attributes["goe.bigquery.total_bytes_billed"] == 10485760
    assert span.attributes["goe.bigquery.slot_millis"] == 55
    assert memory_runtime.get_metrics_data() is not None


def test_query_and_load_spans_and_dry_run(memory_runtime: runtime.ObservabilityRuntime) -> None:
    row_iter = MagicMock(
        job_id="job_q1",
        location="US",
        project="goe-proj",
        total_bytes_processed=1024,
        total_bytes_billed=None,
        slot_millis=12,
        total_rows=1,
    )
    row_iter.__iter__.return_value = iter([(1,)])
    api = _api(MagicMock())
    api._client.query_and_wait.return_value = row_iter
    with traced_command("OFFLOAD", EXEC_ID):
        assert api.execute_query_fetch_all("SELECT 1") == [(1,)]
    query_span = next(s for s in memory_runtime.get_finished_spans() if s.name == "goe.backend.bigquery.query")
    assert query_span.kind == SpanKind.CLIENT
    assert query_span.attributes["goe.bigquery.job_id"] == "job_q1"
    assert query_span.attributes["goe.bigquery.slot_millis"] == 12

    table = object.__new__(BackendBigQueryTable)
    table._dry_run = False
    table._load_db_name = "stage_ds"
    table._load_table_name = "stage_tbl"
    table._kms_key_name = None
    table._log = MagicMock()
    load_job = MagicMock(
        job_id="job_load_1",
        location="US",
        project="goe-proj",
        output_rows=42,
        output_bytes=8192,
        slot_millis=30,
        total_bytes_billed=None,
    )
    bq_client = MagicMock(project="goe-proj")
    bq_client.load_table_from_uri.return_value = load_job
    load_api = _api(MagicMock())
    load_api._client = bq_client
    table._db_api = load_api
    staging_file = MagicMock(file_format=FILE_STORAGE_FORMAT_PARQUET)
    with traced_command("OFFLOAD", EXEC_ID):
        table._load_native_load_table(staging_file, "gs://b/p/part*")
    load_span = next(s for s in memory_runtime.get_finished_spans() if s.name == "goe.backend.bigquery.load")
    assert load_span.kind == SpanKind.CLIENT
    assert load_span.attributes["goe.bigquery.job_id"] == "job_load_1"
    assert load_span.attributes["goe.bigquery.output_rows"] == 42
    assert load_span.attributes["goe.bigquery.output_bytes"] == 8192


def _api(query_job: MagicMock) -> BackendBigQueryApi:
    """Build a BackendBigQueryApi with a mocked client and no logging side effects."""
    api = object.__new__(BackendBigQueryApi)
    api._dry_run = False
    api._kms_key_name = None
    api._bigquery_dataset_project = "goe-proj"
    api._global_session_parameters = {}
    api._messages = MagicMock(get_execution_id=lambda: EXEC_ID, command_type="offload")
    api.catalog = CachedBackendCatalog(no_caching=True)
    api._client = MagicMock(project="goe-proj")
    api._client.query.return_value = query_job
    api._sql_engine_name = "BigQuery"
    api._log_query_id_tag = "BigQuery job_id"
    api._log = MagicMock()
    api._log_or_not = MagicMock()
    api._default_job_config = lambda: bigquery.QueryJobConfig()
    return api
