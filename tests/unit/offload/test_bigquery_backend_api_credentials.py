# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests proving BackendBigQueryApi builds BigQuery and Cloud KMS clients from the shared credential bundle."""

from unittest import mock

from google.auth.credentials import AnonymousCredentials

from goe.offload.bigquery import bigquery_backend_api
from goe.offload.bigquery.bigquery_backend_api import BackendBigQueryApi
from goe.offload.offload_constants import DBTYPE_BIGQUERY
from goe.offload.offload_messages import OffloadMessages
from goe.util.gcp_credentials import CREDENTIAL_TYPE_IMPERSONATED, GcpCredentialBundle
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options

TARGET_SA = "goe-sa@job-project.iam.gserviceaccount.com"


def make_bundle() -> GcpCredentialBundle:
    """Return a resolved bundle whose credentials object identity can be asserted on."""
    return GcpCredentialBundle(
        credentials=AnonymousCredentials(),
        project="job-project",
        quota_project="quota-project",
        principal=TARGET_SA,
        impersonated_principal=TARGET_SA,
        credential_type=CREDENTIAL_TYPE_IMPERSONATED,
        using_service_account_key=False,
    )


def test_bigquery_and_kms_clients_use_resolved_credentials() -> None:
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    bundle = make_bundle()
    with (
        mock.patch.object(bigquery_backend_api, "resolve_gcp_credentials", return_value=bundle) as resolve,
        mock.patch.object(bigquery_backend_api.bigquery, "Client") as bq_client,
        mock.patch.object(bigquery_backend_api.kms, "KeyManagementServiceClient") as kms_client,
    ):
        BackendBigQueryApi(config, DBTYPE_BIGQUERY, OffloadMessages())
    resolve.assert_called_with(config)
    bq_kwargs = bq_client.call_args.kwargs
    assert bq_kwargs["credentials"] is bundle.credentials
    assert bq_kwargs["project"] == "job-project"
    assert bq_kwargs["location"] == config.bigquery_dataset_location
    kms_client.assert_called_once_with(credentials=bundle.credentials)


def test_do_not_connect_skips_credential_resolution() -> None:
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    with mock.patch.object(bigquery_backend_api, "resolve_gcp_credentials") as resolve:
        BackendBigQueryApi(config, DBTYPE_BIGQUERY, OffloadMessages(), do_not_connect=True)
    resolve.assert_not_called()
