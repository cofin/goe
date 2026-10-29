# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for decomposed Spark transport modules, PySpark codegen, and PollingThread."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    DBTYPE_ORACLE,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.transport.protocol import OffloadTransportException
from goe.offload.transport.spark import (
    DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED,
    OffloadTransportSparkBatchesGcloud,
    OffloadTransportSparkDataprocGcloud,
    OffloadTransportSparkLivy,
    OffloadTransportSparkSubmit,
    OffloadTransportSparkThrift,
    PollingThread,
    PySparkCodegen,
    PySparkJobSpec,
    SparkCommandRunner,
    TransportSplitPlanner,
)
from goe.serializers import decode_json


class _FakeMessages:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.warnings: list[str] = []

    def log(self, msg: object, detail: object = None) -> None:
        self.logs.append(str(msg))

    def debug(self, msg: object) -> None:
        return None

    def notice(self, msg: object) -> None:
        self.logs.append(str(msg))

    def warning(self, msg: object) -> None:
        self.warnings.append(str(msg))


def test_pyspark_job_spec_and_codegen_round_trip() -> None:
    """PySparkCodegen generates valid PySpark scripts and serializes specs with msgspec."""
    spec = PySparkJobSpec(
        app_name="GOE.analytics.sales",
        jdbc_url="jdbc:oracle:thin:@//oracle:1521/ORCL",
        jdbc_driver_name="oracle.jdbc.OracleDriver",
        source_query="(SELECT ID, AMOUNT, GOE_SPLIT FROM SALES) v2",
        write_format="parquet",
        target_uri="gs://goe-staging-bucket/sales",
        load_db="analytics",
        table_name="sales",
        parallelism=8,
        fetch_size=5000,
        batch_col="GOE_SPLIT",
        batch_col_min=0,
        batch_col_max=8,
        rdbms_app_user="goe_app",
        session_init_statement="NULL;",
        jdbc_option_clauses=".option('oracle.jdbc.timezoneAsRegion', 'false')",
        base64_columns=("RAW_PAYLOAD",),
        all_columns=("ID", "RAW_PAYLOAD"),
        standalone_spark=True,
        create_spark_context=True,
        include_utf8_header=True,
    )
    serialized = PySparkCodegen.serialize_spec(spec)
    decoded = decode_json(serialized)
    assert decoded["app_name"] == "GOE.analytics.sales"
    assert decoded["parallelism"] == 8

    script = PySparkCodegen.generate(spec)
    assert "# -*- coding: UTF-8 -*-" in script
    assert "from pyspark.sql.functions import base64" in script
    assert "SparkSession.builder.appName('GOE.analytics.sales').getOrCreate()" in script
    assert "base64(df.RAW_PAYLOAD).alias('RAW_PAYLOAD')" in script
    assert ".write.format('parquet').save('gs://goe-staging-bucket/sales')" in script


def test_polling_thread_captures_results_and_exceptions() -> None:
    """PollingThread queues results and captures exceptions without leaking threads."""
    calls = 0

    def _poll() -> int:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("boom in poller")
        return calls

    poller = PollingThread(target=_poll, interval=0.02, name="unit-test-poller")
    poller.start()
    time.sleep(0.08)
    poller.stop()

    assert not poller.is_alive()
    assert poller.drain_queue() == [1]
    exceptions = poller.get_exceptions()
    assert len(exceptions) == 1
    assert isinstance(exceptions[0], RuntimeError)
    assert len(poller.DrainExceptions()) == 1
    assert poller.get_exceptions() == []


def test_spark_command_runner_scp_short_circuit_and_remote_commands() -> None:
    """SparkCommandRunner provides a single canonical implementation for scp_to_host and scp_from_host."""
    executed_cmds: list[list[str]] = []
    messages = _FakeMessages()
    runner = SparkCommandRunner("remote_user", lambda cmd: executed_cmds.append(list(cmd)), messages)

    dest = runner.scp_to_host("remote.host.internal", "/tmp/local.py", "/tmp/remote.py")
    assert dest == "/tmp/remote.py"
    assert any("scp" in token for token in executed_cmds[0])

    pulled = runner.scp_from_host("remote.host.internal", "/tmp/remote.log", "/tmp/local.log")
    assert pulled == "/tmp/local.log"
    assert any("scp" in token for token in executed_cmds[1])


def test_transport_split_planner_falls_back_to_mod_when_bounds_missing() -> None:
    """TransportSplitPlanner switches from range to MOD split when RDBMS returns NULL min/max bounds."""
    messages = _FakeMessages()
    fake_api = SimpleNamespace(get_id_range=lambda col, pred, partition_chunk=None: (None, None))
    fake_table = SimpleNamespace(predicate_to_where_clause=lambda pred: None)

    split_by, id_min, id_max = TransportSplitPlanner.resolve_id_range(
        fake_api,
        fake_table,
        None,
        "ID_RANGE",
        "ORDER_ID",
        None,
        messages,
    )
    assert split_by == "mod"
    assert id_min is None
    assert id_max is None


def test_dataproc_cluster_and_batches_command_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """OffloadTransportSparkDataprocGcloud and OffloadTransportSparkBatchesGcloud build gcloud commands."""
    monkeypatch.setattr(
        "goe.offload.transport.spark.dataproc.create_transport_rdbms_api",
        lambda *a, **kw: SimpleNamespace(
            generate_transport_action=lambda: "act",
            get_rdbms_canary_query=lambda: "SELECT 1 FROM DUAL",
            jdbc_url=lambda: "jdbc:oracle:thin:@//oracle:1521/ORCL",
            jdbc_driver_name=lambda: "oracle.jdbc.OracleDriver",
            get_rdbms_session_setup_commands=lambda *a, **kw: [],
        ),
    )
    messages = _FakeMessages()
    config = _make_config(google_dataproc_service_account="runtime-sa@proj.iam.gserviceaccount.com")
    cluster_transport = OffloadTransportSparkDataprocGcloud.for_canary(config, messages)
    cmd = cluster_transport._gcloud_dataproc_submit_command()
    assert cmd[:4] == ["gcloud", "dataproc", "jobs", "submit"]
    assert "--cluster=goe-dataproc-cluster" in cmd
    assert DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED in messages.warnings

    batches_transport = OffloadTransportSparkBatchesGcloud.for_canary(config, messages)
    batches_cmd = batches_transport._gcloud_dataproc_submit_command(id="batch-123")
    assert batches_cmd[:4] == ["gcloud", "dataproc", "batches", "submit"]
    assert "--batch=batch-123" in batches_cmd
    assert "--service-account=runtime-sa@proj.iam.gserviceaccount.com" in batches_cmd

    with pytest.raises(OffloadTransportException, match="TTL"):
        batches_transport._verify_batch_describe_response('{"state": "CANCELLED"}')


def test_spark_submit_thrift_and_livy_canary_factories(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spark Submit, Thrift, and Livy transport classes expose for_canary factory constructors."""
    monkeypatch.setattr(
        "goe.offload.transport.spark.spark_submit.create_transport_rdbms_api",
        lambda *a, **kw: SimpleNamespace(generate_transport_action=lambda: "act"),
    )
    monkeypatch.setattr(
        "goe.offload.transport.spark.spark_thrift.create_transport_rdbms_api",
        lambda *a, **kw: SimpleNamespace(generate_transport_action=lambda: "act"),
    )
    monkeypatch.setattr(
        "goe.offload.transport.spark.spark_livy.create_transport_rdbms_api",
        lambda *a, **kw: SimpleNamespace(generate_transport_action=lambda: "act"),
    )
    monkeypatch.setattr(
        "goe.offload.transport.spark.spark_livy.get_dfs_from_options",
        lambda *a, **kw: SimpleNamespace(backend_dfs="GCS"),
    )
    monkeypatch.setattr(
        "goe.offload.transport.spark.spark_livy.OffloadTransportLivyRequests",
        lambda *a, **kw: SimpleNamespace(),
    )
    config = _make_config()
    messages = _FakeMessages()

    submit_inst = OffloadTransportSparkSubmit.for_canary(config, messages)
    thrift_inst = OffloadTransportSparkThrift.for_canary(config, messages)
    livy_inst = OffloadTransportSparkLivy.for_canary(config, messages)

    assert submit_inst.get_transport_method() == "SPARK_SUBMIT"
    assert thrift_inst.get_transport_method() == "SPARK_THRIFT"
    assert livy_inst.get_transport_method() == "SPARK_LIVY"


def _make_config(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "db_type": DBTYPE_ORACLE,
        "backend_distribution": BACKEND_DISTRO_GCP,
        "offload_staging_format": FILE_STORAGE_FORMAT_PARQUET,
        "offload_transport_auth_using_oracle_wallet": False,
        "offload_transport_cmd_host": "localhost",
        "offload_transport_credential_provider_path": None,
        "offload_transport_dsn": "oracle-host:1521/ORCL",
        "offload_transport_password_alias": None,
        "offload_transport_rdbms_session_parameters": None,
        "offload_transport_spark_thrift_host": "thrift.internal",
        "offload_transport_spark_thrift_port": 10000,
        "offload_transport_spark_submit_executable": "spark-submit",
        "offload_transport_spark_submit_master_url": "spark://master:7077",
        "offload_transport_livy_api_url": "http://livy.internal:8998",
        "offload_transport_livy_max_sessions": 4,
        "offload_transport_livy_idle_session_timeout": 60,
        "offload_transport_spark_files": None,
        "offload_transport_spark_jars": None,
        "offload_transport_user": "goe",
        "offload_fs_container": "goe-staging-bucket",
        "google_dataproc_cluster": "goe-dataproc-cluster",
        "google_dataproc_project": "goe-project",
        "google_dataproc_region": "us-central1",
        "google_dataproc_service_account": None,
        "google_dataproc_batches_subnet": "projects/p/regions/r/subnetworks/s",
        "google_dataproc_batches_ttl": "3600s",
        "google_dataproc_batches_version": "2.2",
        "google_impersonate_service_account": None,
        "google_dataproc_impersonate_service_account": None,
        "rdbms_app_user": "goe_app",
        "rdbms_app_pass": "secret",
        "suppress_stdout": True,
        "vverbose": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)
