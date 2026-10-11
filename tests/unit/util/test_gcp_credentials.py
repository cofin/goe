# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe.util.gcp_credentials ADC, impersonation, and project resolution."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest import mock

import pytest
from google.auth import impersonated_credentials
from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account

from goe.exceptions import OffloadOptionError
from goe.util import gcp_credentials
from goe.util.gcp_credentials import (
    CREDENTIAL_TYPE_AUTHORIZED_USER,
    CREDENTIAL_TYPE_IMPERSONATED,
    CREDENTIAL_TYPE_SERVICE_ACCOUNT_KEY,
    DEFAULT_GCP_SCOPES,
    clear_gcp_credentials_cache,
    resolve_gcloud_impersonation_principal,
    resolve_gcp_credentials,
)

GCP_ENV_VARS = (
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_QUOTA_PROJECT",
    "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT",
    "GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT",
    "BIGQUERY_DATASET_PROJECT",
)
TARGET_SA = "goe-sa@target-proj.iam.gserviceaccount.com"


@pytest.fixture(autouse=True)
def isolated_gcp_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove ambient GCP variables and cached bundles so every test controls its own inputs."""
    for name in GCP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    clear_gcp_credentials_cache()
    yield
    clear_gcp_credentials_cache()


def make_config(**overrides: str | None) -> SimpleNamespace:
    """Build an OrchestrationConfig stand-in exposing only the attributes the resolver reads."""
    values: dict[str, str | None] = {
        "google_cloud_project": None,
        "google_cloud_quota_project": None,
        "google_impersonate_service_account": None,
        "google_dataproc_impersonate_service_account": None,
        "bigquery_dataset_project": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def user_creds() -> user_credentials.Credentials:
    """Return an offline authorized_user credential with a known account."""
    return user_credentials.Credentials(token="token", account="dev@example.com")


def test_direct_adc_uses_explicit_project_and_quota() -> None:
    source = user_creds()
    config = make_config(google_cloud_project="cfg-proj", google_cloud_quota_project="quota-proj")
    with mock.patch.object(gcp_credentials.google.auth, "default", return_value=(source, "adc-proj")) as adc:
        bundle = resolve_gcp_credentials(config)
    adc.assert_called_once_with(scopes=list(DEFAULT_GCP_SCOPES), quota_project_id="quota-proj")
    assert bundle.credentials is source
    assert bundle.project == "cfg-proj"
    assert bundle.quota_project == "quota-proj"
    assert bundle.principal == "dev@example.com"
    assert bundle.impersonated_principal is None
    assert bundle.credential_type == CREDENTIAL_TYPE_AUTHORIZED_USER
    assert bundle.using_service_account_key is False


@pytest.mark.parametrize(
    ("config_project", "adc_project", "dataset_project", "expected"),
    [
        ("cfg-proj", "adc-proj", "bq-proj", "cfg-proj"),
        (None, "adc-proj", "bq-proj", "adc-proj"),
        (None, None, "bq-proj", "bq-proj"),
        (None, None, None, None),
    ],
)
def test_project_precedence(
    config_project: str | None, adc_project: str | None, dataset_project: str | None, expected: str | None
) -> None:
    config = make_config(google_cloud_project=config_project, bigquery_dataset_project=dataset_project)
    with mock.patch.object(gcp_credentials.google.auth, "default", return_value=(user_creds(), adc_project)):
        assert resolve_gcp_credentials(config).project == expected


def test_impersonation_wraps_source_credentials() -> None:
    config = make_config(google_impersonate_service_account=TARGET_SA, google_cloud_quota_project="quota-proj")
    with mock.patch.object(gcp_credentials.google.auth, "default", return_value=(user_creds(), "adc-proj")):
        bundle = resolve_gcp_credentials(config)
    assert isinstance(bundle.credentials, impersonated_credentials.Credentials)
    assert bundle.credentials.service_account_email == TARGET_SA
    assert bundle.credentials.quota_project_id == "quota-proj"
    assert bundle.principal == TARGET_SA
    assert bundle.impersonated_principal == TARGET_SA
    assert bundle.credential_type == CREDENTIAL_TYPE_IMPERSONATED


def test_impersonation_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT", TARGET_SA)
    with mock.patch.object(gcp_credentials.google.auth, "default", return_value=(user_creds(), "adc-proj")):
        bundle = resolve_gcp_credentials()
    assert bundle.impersonated_principal == TARGET_SA


def test_already_impersonated_adc_is_not_wrapped_twice() -> None:
    adc = impersonated_credentials.Credentials(
        source_credentials=user_creds(), target_principal=TARGET_SA, target_scopes=list(DEFAULT_GCP_SCOPES)
    )
    config = make_config(google_impersonate_service_account=TARGET_SA)
    with mock.patch.object(gcp_credentials.google.auth, "default", return_value=(adc, "adc-proj")):
        bundle = resolve_gcp_credentials(config)
    assert bundle.credentials is adc


def test_already_impersonated_adc_with_different_target_raises() -> None:
    adc = impersonated_credentials.Credentials(
        source_credentials=user_creds(),
        target_principal="other-sa@proj.iam.gserviceaccount.com",
        target_scopes=list(DEFAULT_GCP_SCOPES),
    )
    config = make_config(google_impersonate_service_account=TARGET_SA)
    with (
        mock.patch.object(gcp_credentials.google.auth, "default", return_value=(adc, "adc-proj")),
        pytest.raises(OffloadOptionError, match="already impersonating"),
    ):
        resolve_gcp_credentials(config)


def test_service_account_key_is_flagged() -> None:
    key_creds = mock.Mock(spec=service_account.Credentials)
    key_creds.service_account_email = "key-sa@proj.iam.gserviceaccount.com"
    with mock.patch.object(gcp_credentials.google.auth, "default", return_value=(key_creds, "proj")):
        bundle = resolve_gcp_credentials(make_config())
    assert bundle.using_service_account_key is True
    assert bundle.credential_type == CREDENTIAL_TYPE_SERVICE_ACCOUNT_KEY
    assert bundle.principal == "key-sa@proj.iam.gserviceaccount.com"


def test_bundles_are_cached_per_inputs() -> None:
    config = make_config(google_cloud_project="cfg-proj")
    with mock.patch.object(gcp_credentials.google.auth, "default", return_value=(user_creds(), None)) as adc:
        first = resolve_gcp_credentials(config)
        second = resolve_gcp_credentials(config)
        resolve_gcp_credentials(make_config(google_cloud_project="other-proj"))
    assert first is second
    assert adc.call_count == 2


@pytest.mark.parametrize(
    ("dataproc_sa", "general_sa", "expected"),
    [
        ("dp-caller@p.iam.gserviceaccount.com", TARGET_SA, "dp-caller@p.iam.gserviceaccount.com"),
        (None, TARGET_SA, TARGET_SA),
        (None, None, None),
    ],
)
def test_resolve_gcloud_impersonation_principal(
    dataproc_sa: str | None, general_sa: str | None, expected: str | None
) -> None:
    config = make_config(
        google_dataproc_impersonate_service_account=dataproc_sa, google_impersonate_service_account=general_sa
    )
    assert resolve_gcloud_impersonation_principal(config) == expected
