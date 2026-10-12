# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Regression and behavior tests for BackendBigQueryApi modernization."""

from unittest.mock import MagicMock, patch

import pytest

from goe.offload.backend_api import BackendApiException
from goe.offload.bigquery.bigquery_backend_api import BackendBigQueryApi, sanitize_bigquery_label_value
from goe.offload.factory.backend_api_factory import backend_api_factory
from goe.offload.offload_constants import DBTYPE_BIGQUERY
from goe.offload.offload_messages import OffloadMessages
from goe.orchestration.execution_id import ExecutionId
from goe.orchestration.orchestration_constants import COMMAND_OFFLOAD
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options

KMS_KEY = "projects/kms-project/locations/US/keyRings/ring-name/cryptoKeys/key-name"


def test_partition_count_uses_information_schema() -> None:
    """Partition count is a parameterized GoogleSQL query, not Legacy SQL."""
    api = _api()
    api._client.query_and_wait.return_value = _row_iterator([(4,)])
    with patch.object(api, "_table_is_partitioned", return_value=True):
        assert api.get_table_partition_count("sales_ds", "orders") == 4
    sql = api._client.query_and_wait.call_args.args[0]
    job_config = api._client.query_and_wait.call_args.kwargs["job_config"]
    assert "`bq-project.sales_ds`.INFORMATION_SCHEMA.PARTITIONS" in sql
    assert "COUNT(DISTINCT partition_id)" in sql
    assert "$__PARTITIONS_SUMMARY__" not in sql
    assert not job_config.use_legacy_sql
    assert [(p.name, p.value) for p in job_config.query_parameters] == [("table_name", "orders")]


def test_partitions_keep_pseudo_partitions() -> None:
    """Partition listing keeps __NULL__/__UNPARTITIONED__ like the legacy meta-table."""
    api = _api()
    api._client.query_and_wait.return_value = _row_iterator([("20260101",), ("__NULL__",)])
    with patch.object(api, "_table_is_partitioned", return_value=True):
        partitions = api.get_table_partitions("sales_ds", "orders")
    assert list(partitions) == ["20260101", "__NULL__"]
    assert partitions["20260101"]["partition_id"] == "20260101"
    assert "SELECT DISTINCT partition_id" in api._client.query_and_wait.call_args.args[0]


def test_legacy_sql_option_is_rejected() -> None:
    """Passing use_legacy_sql raises instead of silently enabling Legacy SQL."""
    api = _api()
    with pytest.raises(BackendApiException, match="Legacy SQL"):
        api.execute_query_fetch_one("SELECT 1", query_options={"use_legacy_sql": True})


def test_default_job_config_keeps_utc_and_adds_labels() -> None:
    """Default job config keeps the UTC connection property and carries sanitized GOE labels."""
    messages = OffloadMessages(execution_id=ExecutionId(), command_type=COMMAND_OFFLOAD)
    api = _api(messages)
    job_config = api._default_job_config()
    assert [(p.key, p.value) for p in job_config.connection_properties] == [("time_zone", "UTC")]
    assert job_config.labels["goe_command"] == "offload"
    assert job_config.labels["goe_execution_id"] == str(messages.get_execution_id())
    assert set(job_config.labels["goe_version"]) <= set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def test_sanitize_bigquery_label_value() -> None:
    """Label values are lower-cased, restricted to [a-z0-9_-] and truncated to 63 characters."""
    assert sanitize_bigquery_label_value("2.0.0-SNAPSHOT+build.1") == "2_0_0-snapshot_build_1"
    assert len(sanitize_bigquery_label_value("A" * 100)) == 63


def test_non_profiled_reads_use_query_and_wait_and_profiled_use_query() -> None:
    """Non-profiled reads use the jobs.query fast path; profiled reads keep the QueryJob."""
    api = _api()
    api._client.query_and_wait.return_value = _row_iterator([("user@example.com",)])
    assert api.execute_query_fetch_one("SELECT SESSION_USER()") == ("user@example.com",)
    api._client.query.assert_not_called()
    query_job = MagicMock()
    query_job.result.return_value = _row_iterator([(1,)])
    api._client.query.return_value = query_job
    with patch.object(api, "_get_query_profile", return_value="profile"):
        assert api.execute_query_fetch_all("SELECT 1", profile=True) == [(1,)]
    api._client.query.assert_called_once()


def test_session_allow_list_accepts_job_options() -> None:
    """labels, priority, job_timeout_ms and reservation are accepted session parameters."""
    api = _api()
    api._global_session_parameters = {"priority": "BATCH", "job_timeout_ms": 600000}
    job_config = api._execute_global_session_parameters()
    assert job_config.priority == "BATCH"
    assert int(job_config.job_timeout_ms) == 600000


def test_close_is_idempotent_and_safe_without_client() -> None:
    """close() closes once, clears the client, and tolerates partially initialised objects."""
    assert "__del__" not in BackendBigQueryApi.__dict__
    api = _api()
    client = api._client
    with api as entered:
        assert entered is api
    client.close.assert_called_once()
    assert api._client is None
    api.close()
    client.close.assert_called_once()
    BackendBigQueryApi.close(object.__new__(BackendBigQueryApi))


def test_create_database_sets_default_kms_key_name() -> None:
    """CREATE SCHEMA carries default_kms_key_name when CMEK is configured."""
    api = _api()
    api._kms_key_name = KMS_KEY
    with (
        patch.object(api, "database_exists", return_value=False),
        patch.object(api, "execute_ddl", return_value=["CREATE SCHEMA"]) as execute_ddl,
    ):
        api.create_database("sales_load", comment="Offload load")
    assert f"default_kms_key_name='{KMS_KEY}'" in execute_ddl.call_args.args[0]


def _row_iterator(rows: list[tuple]) -> MagicMock:
    """Return a RowIterator stand-in yielding rows."""
    iterator = MagicMock()
    iterator.job_id = "job-1"
    iterator.total_rows = len(rows)
    iterator.__iter__.side_effect = lambda: iter(rows)
    return iterator


def _api(messages: OffloadMessages | None = None) -> BackendBigQueryApi:
    """Build a non-connecting BigQuery API with a mocked client."""
    api = backend_api_factory(
        DBTYPE_BIGQUERY,
        build_mock_options(FAKE_ORACLE_BQ_ENV),
        messages or OffloadMessages(),
        dry_run=False,
        do_not_connect=True,
    )
    api._client = MagicMock()
    return api
