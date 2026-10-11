# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the goe connect Google Cloud credential preflight and Managed Spark identity report."""

from types import SimpleNamespace
from unittest import mock

import pytest
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError, RefreshError

from goe.connect import connect_backend, connect_transport
from goe.connect.connect_backend import (
    GCP_ADC_MISSING_HINT,
    GCP_PROJECT_MISSING_HINT,
    GCP_SERVICE_ACCOUNT_KEY_HINT,
    GCP_TOKEN_REFRESH_HINT,
    uses_google_cloud,
)
from goe.connect.connect_transport import report_gcloud_identity
from goe.offload.spark.dataproc_offload_transport import DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED
from goe.util.gcp_credentials import (
    CREDENTIAL_TYPE_AUTHORIZED_USER,
    CREDENTIAL_TYPE_SERVICE_ACCOUNT_KEY,
    GcpCredentialBundle,
)

Event = tuple[str, str | None]


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[Event]:
    """Capture connect output helpers as (kind, text-or-hint) tuples instead of writing to the GOE log."""
    recorded: list[Event] = []

    def record_detail(text: object) -> None:
        recorded.append(("detail", str(text)))

    def record_success(test_name: str) -> None:
        recorded.append(("success", None))

    def record_warning(test_name: str, hint: str | None = None) -> None:
        recorded.append(("warning", hint))

    def record_failure(test_name: str, hint: str | None = None) -> None:
        recorded.append(("failure", hint))

    for module in (connect_backend, connect_transport):
        monkeypatch.setattr(module, "test_header", mock.Mock())
        monkeypatch.setattr(module, "detail", record_detail)
        monkeypatch.setattr(module, "success", record_success)
        monkeypatch.setattr(module, "warning", record_warning)
        monkeypatch.setattr(module, "failure", record_failure)
    return recorded


def make_bundle(
    project: str | None = "job-project",
    using_key: bool = False,
    credential_type: str = CREDENTIAL_TYPE_AUTHORIZED_USER,
) -> GcpCredentialBundle:
    """Return a bundle whose credentials refresh offline."""
    return GcpCredentialBundle(
        credentials=mock.Mock(spec=Credentials),
        project=project,
        quota_project="quota-project",
        principal="dev@example.com",
        impersonated_principal=None,
        credential_type=credential_type,
        using_service_account_key=using_key,
    )


def test_gcp_credentials_check_reports_identity_and_passes(events: list[Event]) -> None:
    bundle = make_bundle()
    with mock.patch.object(connect_backend, "resolve_gcp_credentials", return_value=bundle):
        connect_backend.test_gcp_credentials(SimpleNamespace())
    bundle.credentials.refresh.assert_called_once()
    assert ("detail", f"Credential type: {CREDENTIAL_TYPE_AUTHORIZED_USER}") in events
    assert ("detail", "Project: job-project") in events
    assert ("detail", "Quota project: quota-project") in events
    assert events[-1] == ("success", None)


def test_gcp_credentials_check_warns_on_service_account_key(events: list[Event]) -> None:
    bundle = make_bundle(using_key=True, credential_type=CREDENTIAL_TYPE_SERVICE_ACCOUNT_KEY)
    with mock.patch.object(connect_backend, "resolve_gcp_credentials", return_value=bundle):
        connect_backend.test_gcp_credentials(SimpleNamespace())
    assert events[-1] == ("warning", GCP_SERVICE_ACCOUNT_KEY_HINT)


def test_gcp_credentials_check_warns_on_missing_project(events: list[Event]) -> None:
    with mock.patch.object(connect_backend, "resolve_gcp_credentials", return_value=make_bundle(project=None)):
        connect_backend.test_gcp_credentials(SimpleNamespace())
    assert events[-1] == ("warning", GCP_PROJECT_MISSING_HINT)


def test_gcp_credentials_check_fails_without_adc(events: list[Event]) -> None:
    with mock.patch.object(connect_backend, "resolve_gcp_credentials", side_effect=DefaultCredentialsError("no ADC")):
        connect_backend.test_gcp_credentials(SimpleNamespace())
    assert events[-1] == ("failure", GCP_ADC_MISSING_HINT)


def test_gcp_credentials_check_fails_when_token_refresh_is_denied(events: list[Event]) -> None:
    bundle = make_bundle()
    bundle.credentials.refresh.side_effect = RefreshError("iam.serviceAccounts.getAccessToken denied")
    with mock.patch.object(connect_backend, "resolve_gcp_credentials", return_value=bundle):
        connect_backend.test_gcp_credentials(SimpleNamespace())
    assert events[-1] == ("failure", GCP_TOKEN_REFRESH_HINT)


@pytest.mark.parametrize(
    ("backend_distribution", "offload_fs_scheme", "expected"),
    [("GCP", "gs", True), ("SNOWFLAKE", "gs", True), ("SNOWFLAKE", "s3", False), ("MSAZURE", "abfs", False)],
)
def test_uses_google_cloud(backend_distribution: str, offload_fs_scheme: str, expected: bool) -> None:
    config = SimpleNamespace(backend_distribution=backend_distribution, offload_fs_scheme=offload_fs_scheme)
    assert uses_google_cloud(config) is expected


def test_report_gcloud_identity_warns_for_cluster_runtime_sa_without_caller(
    events: list[Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT", raising=False)
    monkeypatch.delenv("GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT", raising=False)
    config = SimpleNamespace(
        google_dataproc_cluster="cluster-name",
        google_dataproc_service_account="sa@proj.com",
        google_impersonate_service_account=None,
        google_dataproc_impersonate_service_account=None,
    )
    report_gcloud_identity(config)
    assert ("detail", "gcloud caller impersonation: none (active gcloud account)") in events
    assert events[-1] == ("warning", DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED)


def test_report_gcloud_identity_passes_with_caller(events: list[Event], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT", raising=False)
    config = SimpleNamespace(
        google_dataproc_cluster="cluster-name",
        google_dataproc_service_account="sa@proj.com",
        google_impersonate_service_account="goe-caller@proj.iam.gserviceaccount.com",
        google_dataproc_impersonate_service_account=None,
    )
    report_gcloud_identity(config)
    assert ("detail", "gcloud caller impersonation: goe-caller@proj.iam.gserviceaccount.com") in events
    assert events[-1] == ("success", None)
