# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests proving GOELogFileHandle passes explicit credentials to gcsfs instead of the anonymous fallback."""

from pathlib import Path
from unittest import mock

from gcsfs.core import GCS_MIN_BLOCK_SIZE
from google.auth.credentials import AnonymousCredentials

from goe.util import goe_log_fh
from goe.util.gcp_credentials import CREDENTIAL_TYPE_AUTHORIZED_USER, GcpCredentialBundle
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


def test_gcs_log_path_passes_resolved_token_and_project() -> None:
    bundle = make_bundle("job-project")
    with (
        mock.patch.object(goe_log_fh, "resolve_gcp_credentials", return_value=bundle) as resolve,
        mock.patch.object(goe_log_fh.fsspec, "filesystem") as filesystem,
    ):
        GOELogFileHandle("gs://bucket/logs/offload.log")
    resolve.assert_called_once_with()
    filesystem.assert_called_once_with(
        "gs", block_size=GCS_MIN_BLOCK_SIZE, token=bundle.credentials, project="job-project"
    )


def test_gcs_log_path_omits_unresolved_project() -> None:
    bundle = make_bundle(None)
    with (
        mock.patch.object(goe_log_fh, "resolve_gcp_credentials", return_value=bundle),
        mock.patch.object(goe_log_fh.fsspec, "filesystem") as filesystem,
    ):
        GOELogFileHandle("gs://bucket/logs/offload.log")
    filesystem.assert_called_once_with("gs", block_size=GCS_MIN_BLOCK_SIZE, token=bundle.credentials)


def test_local_log_path_does_not_resolve_credentials(tmp_path: Path) -> None:
    log_path = tmp_path / "offload.log"
    with mock.patch.object(goe_log_fh, "resolve_gcp_credentials") as resolve:
        with GOELogFileHandle(str(log_path)) as fh:
            fh.write("line\n")
    resolve.assert_not_called()
    assert log_path.read_text() == "line\n"
