# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for gcloud caller impersonation flags in Dataproc Spark transports."""

from types import SimpleNamespace

import pytest

from goe.offload.offload_constants import (
    BACKEND_DISTRO_GCP,
    DBTYPE_ORACLE,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.transport.spark.dataproc import (
    DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED,
    OffloadTransportSparkBatchesGcloud,
    OffloadTransportSparkDataprocGcloud,
)


class FakeMessages:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.logs: list[str] = []

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def log(self, msg: str, detail=None) -> None:
        self.logs.append(msg)

    def debug(self, msg: str) -> None:
        pass


def _make_config(**overrides) -> SimpleNamespace:
    defaults = {
        "db_type": DBTYPE_ORACLE,
        "backend_distribution": BACKEND_DISTRO_GCP,
        "offload_staging_format": FILE_STORAGE_FORMAT_PARQUET,
        "offload_transport_auth_using_oracle_wallet": False,
        "offload_transport_cmd_host": "localhost",
        "offload_transport_credential_provider_path": None,
        "offload_transport_dsn": "dsn",
        "offload_transport_password_alias": None,
        "offload_transport_rdbms_session_parameters": None,
        "offload_transport_spark_thrift_host": None,
        "offload_transport_spark_thrift_port": None,
        "offload_transport_spark_files": None,
        "offload_transport_spark_jars": None,
        "offload_fs_container": "my-staging-bucket",
        "google_dataproc_cluster": "my-cluster",
        "google_dataproc_project": "my-dataproc-proj",
        "google_dataproc_region": "us-central1",
        "google_dataproc_service_account": None,
        "google_dataproc_batches_subnet": None,
        "google_dataproc_batches_ttl": None,
        "google_dataproc_batches_version": "2.1",
        "google_impersonate_service_account": None,
        "google_dataproc_impersonate_service_account": None,
        "rdbms_dsn": "dsn",
        "ora_adm_user": "adm",
        "ora_adm_pass": "secret",
        "use_oracle_wallet": False,
        "oracledb_thick_mode": False,
        "rdbms_app_user": "app",
        "rdbms_app_pass": "secret",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_dataproc_transport(config: SimpleNamespace, messages: FakeMessages) -> OffloadTransportSparkDataprocGcloud:
    return OffloadTransportSparkDataprocGcloud.for_canary(config, messages)


def _build_batches_transport(config: SimpleNamespace, messages: FakeMessages) -> OffloadTransportSparkBatchesGcloud:
    return OffloadTransportSparkBatchesGcloud.for_canary(config, messages)


class TestDataprocClusterGcloudCommand:
    def test_no_impersonation_no_runtime_sa(self) -> None:
        messages = FakeMessages()
        transport = _build_dataproc_transport(_make_config(), messages)
        cmd = transport._gcloud_dataproc_submit_command()
        assert "--impersonate-service-account" not in " ".join(cmd)
        assert "--service-account" not in " ".join(cmd)
        assert messages.warnings == []

    def test_dataproc_impersonation_flag_added(self) -> None:
        messages = FakeMessages()
        config = _make_config(
            google_impersonate_service_account="global@proj.iam.gserviceaccount.com",
            google_dataproc_impersonate_service_account="dp-caller@proj.iam.gserviceaccount.com",
        )
        transport = _build_dataproc_transport(config, messages)
        cmd = transport._gcloud_dataproc_submit_command()
        assert "--impersonate-service-account=dp-caller@proj.iam.gserviceaccount.com" in cmd
        assert messages.warnings == []

    def test_global_impersonation_fallback(self) -> None:
        messages = FakeMessages()
        config = _make_config(google_impersonate_service_account="global@proj.iam.gserviceaccount.com")
        transport = _build_dataproc_transport(config, messages)
        cmd = transport._gcloud_dataproc_submit_command()
        assert "--impersonate-service-account=global@proj.iam.gserviceaccount.com" in cmd
        assert messages.warnings == []

    def test_runtime_service_account_not_passed_to_jobs_submit_and_warns(self) -> None:
        messages = FakeMessages()
        config = _make_config(google_dataproc_service_account="runtime@proj.iam.gserviceaccount.com")
        transport = _build_dataproc_transport(config, messages)
        cmd = transport._gcloud_dataproc_submit_command()
        assert not any(arg.startswith("--service-account") for arg in cmd)
        assert not any(arg.startswith("--impersonate-service-account") for arg in cmd)
        assert messages.warnings == [DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED]

    def test_runtime_sa_with_caller_impersonation_does_not_warn(self) -> None:
        messages = FakeMessages()
        config = _make_config(
            google_dataproc_service_account="runtime@proj.iam.gserviceaccount.com",
            google_dataproc_impersonate_service_account="caller@proj.iam.gserviceaccount.com",
        )
        transport = _build_dataproc_transport(config, messages)
        cmd = transport._gcloud_dataproc_submit_command()
        assert "--impersonate-service-account=caller@proj.iam.gserviceaccount.com" in cmd
        assert not any(arg.startswith("--service-account") for arg in cmd)
        assert messages.warnings == []


class TestDataprocBatchesGcloudCommand:
    @pytest.mark.parametrize(
        ("global_sa", "dp_sa", "runtime_sa", "expected_impersonate", "expected_runtime"),
        [
            (None, None, None, None, None),
            (
                "global@p.iam.gserviceaccount.com",
                None,
                "runtime@p.iam.gserviceaccount.com",
                "global@p.iam.gserviceaccount.com",
                "runtime@p.iam.gserviceaccount.com",
            ),
            (
                "global@p.iam.gserviceaccount.com",
                "dp@p.iam.gserviceaccount.com",
                "runtime@p.iam.gserviceaccount.com",
                "dp@p.iam.gserviceaccount.com",
                "runtime@p.iam.gserviceaccount.com",
            ),
        ],
    )
    def test_submit_passes_distinct_caller_impersonation_and_runtime_sa(
        self,
        global_sa: str | None,
        dp_sa: str | None,
        runtime_sa: str | None,
        expected_impersonate: str | None,
        expected_runtime: str | None,
    ) -> None:
        messages = FakeMessages()
        config = _make_config(
            google_impersonate_service_account=global_sa,
            google_dataproc_impersonate_service_account=dp_sa,
            google_dataproc_service_account=runtime_sa,
        )
        transport = _build_batches_transport(config, messages)
        submit_cmd = transport._gcloud_dataproc_submit_command(id="batch-1")
        describe_cmd = transport._gcloud_dataproc_describe_command("batch-1")

        if expected_impersonate:
            assert f"--impersonate-service-account={expected_impersonate}" in submit_cmd
            assert f"--impersonate-service-account={expected_impersonate}" in describe_cmd
        else:
            assert not any(a.startswith("--impersonate-service-account") for a in submit_cmd)
            assert not any(a.startswith("--impersonate-service-account") for a in describe_cmd)

        if expected_runtime:
            assert f"--service-account={expected_runtime}" in submit_cmd
        else:
            assert not any(a.startswith("--service-account") for a in submit_cmd)
        assert not any(a.startswith("--service-account") for a in describe_cmd)
