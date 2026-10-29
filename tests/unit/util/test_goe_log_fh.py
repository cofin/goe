# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests proving GOELogFileHandle streams gs:// logs via google.cloud.storage.Blob.open."""

from pathlib import Path
from unittest import mock

from google.auth.credentials import AnonymousCredentials

from goe.config.gcp_credentials import CREDENTIAL_TYPE_AUTHORIZED_USER, GcpCredentialBundle
from goe.util import goe_log_fh
from goe.util.goe_log_fh import GOELogFileHandle


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


def test_gcs_log_path_passes_resolved_credentials_and_project_to_storage_client() -> None:
    """GOELogFileHandle opens gs:// paths via storage.Client and Blob.open."""
    bundle = make_bundle("job-project")
    with (
        mock.patch.object(goe_log_fh, "resolve_gcp_credentials", return_value=bundle) as resolve,
        mock.patch.object(goe_log_fh.storage, "Client") as client_cls,
    ):
        GOELogFileHandle("gs://bucket-a/logs/offload.log")
    resolve.assert_called_once_with()
    client_cls.assert_called_once_with(credentials=bundle.credentials, project="job-project")
    client_cls.return_value.bucket.assert_called_once_with("bucket-a")
    client_cls.return_value.bucket.return_value.blob.assert_called_once_with("logs/offload.log")
    client_cls.return_value.bucket.return_value.blob.return_value.open.assert_called_once_with("w")


def test_gcs_log_path_omits_unresolved_project() -> None:
    """GOELogFileHandle omits project when GcpCredentialBundle.project is None."""
    bundle = make_bundle(None)
    with (
        mock.patch.object(goe_log_fh, "resolve_gcp_credentials", return_value=bundle),
        mock.patch.object(goe_log_fh.storage, "Client") as client_cls,
    ):
        GOELogFileHandle("gs://bucket-a/logs/offload.log")
    client_cls.assert_called_once_with(credentials=bundle.credentials)


def test_local_log_path_does_not_resolve_credentials(tmp_path: Path) -> None:
    """GOELogFileHandle opens local paths directly without resolving GCP credentials."""
    log_path = tmp_path / "offload.log"
    with mock.patch.object(goe_log_fh, "resolve_gcp_credentials") as resolve:
        with GOELogFileHandle(str(log_path)) as fh:
            fh.write("line\n")
    resolve.assert_not_called()
    assert log_path.read_text(encoding="utf-8") == "line\n"
