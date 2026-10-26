# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests proving CloudStorageDfsAdapter and StagingStorageService build storage.Client from the shared GOE credential bundle."""

from unittest import mock

from google.auth.credentials import AnonymousCredentials

from goe.config.gcp_credentials import CREDENTIAL_TYPE_AUTHORIZED_USER, GcpCredentialBundle
from goe.filesystem import storage_service
from goe.filesystem.goe_dfs import CloudStorageDfsAdapter
from goe.filesystem.goe_dfs_factory import get_dfs_from_options
from goe.offload.offload_messages import OffloadMessages
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def make_bundle(project: str | None) -> GcpCredentialBundle:
    """Return a resolved bundle with a configurable project."""
    return GcpCredentialBundle(
        credentials=AnonymousCredentials(),
        project=project,
        quota_project=None,
        principal="dev@example.com",
        impersonated_principal=None,
        credential_type=CREDENTIAL_TYPE_AUTHORIZED_USER,
        using_service_account_key=False,
    )


def test_storage_client_uses_resolved_credentials_and_project() -> None:
    """CloudStorageDfsAdapter initializes storage.Client with resolved credentials and project."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    bundle = make_bundle("job-project")
    with (
        mock.patch.object(storage_service, "resolve_gcp_credentials", return_value=bundle) as resolve,
        mock.patch.object(storage_service.storage, "Client") as storage_client,
    ):
        CloudStorageDfsAdapter(OffloadMessages(), scheme="gs", config=config)
    resolve.assert_called_once_with(config)
    storage_client.assert_called_once_with(credentials=bundle.credentials, project="job-project")


def test_storage_client_omits_unresolved_project() -> None:
    """CloudStorageDfsAdapter omits project kwarg when resolved bundle has project=None."""
    bundle = make_bundle(None)
    with (
        mock.patch.object(storage_service, "resolve_gcp_credentials", return_value=bundle),
        mock.patch.object(storage_service.storage, "Client") as storage_client,
    ):
        CloudStorageDfsAdapter(OffloadMessages(), scheme="gs")
    storage_client.assert_called_once_with(credentials=bundle.credentials)


def test_dfs_factory_forwards_config_to_cloud_storage_adapter() -> None:
    """get_dfs_from_options forwards config to resolve_gcp_credentials when building GCS adapter."""
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    with (
        mock.patch.object(
            storage_service, "resolve_gcp_credentials", return_value=make_bundle("job-project")
        ) as resolve,
        mock.patch.object(storage_service.storage, "Client"),
    ):
        get_dfs_from_options(config, OffloadMessages(), dry_run=True)
    resolve.assert_called_once_with(config)
