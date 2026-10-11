# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unified Google Cloud Application Default Credentials (ADC) and service account impersonation resolver.

Every GOE Google Cloud client (BigQuery, Cloud KMS, Cloud Storage, gcsfs) obtains credentials, the job
project, and the quota project from `resolve_gcp_credentials`. `gcloud` subprocesses obtain their caller
impersonation principal from `resolve_gcloud_impersonation_principal` because they run through
`run_os_cmd` (optionally over SSH), so per-command flags are the only reliable propagation channel.
"""

import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass

import google.auth
from google.auth import compute_engine, external_account, external_account_authorized_user, impersonated_credentials
from google.auth.credentials import Credentials
from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account

from goe.exceptions import OffloadOptionError

__all__ = (
    "CREDENTIAL_TYPE_AUTHORIZED_USER",
    "CREDENTIAL_TYPE_COMPUTE_ENGINE",
    "CREDENTIAL_TYPE_EXTERNAL_ACCOUNT",
    "CREDENTIAL_TYPE_IMPERSONATED",
    "CREDENTIAL_TYPE_SERVICE_ACCOUNT_KEY",
    "DEFAULT_GCP_SCOPES",
    "IMPERSONATION_LIFETIME_SECONDS",
    "GcpCredentialBundle",
    "classify_credentials",
    "clear_gcp_credentials_cache",
    "credential_principal",
    "resolve_gcloud_impersonation_principal",
    "resolve_gcp_credentials",
)

DEFAULT_GCP_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/cloud-platform",)
IMPERSONATION_LIFETIME_SECONDS = 3600

CREDENTIAL_TYPE_AUTHORIZED_USER = "authorized_user"
CREDENTIAL_TYPE_COMPUTE_ENGINE = "compute_engine"
CREDENTIAL_TYPE_EXTERNAL_ACCOUNT = "external_account"
CREDENTIAL_TYPE_IMPERSONATED = "impersonated_service_account"
CREDENTIAL_TYPE_SERVICE_ACCOUNT_KEY = "service_account_key"


@dataclass(frozen=True)
class GcpCredentialBundle:
    """Resolved Google Cloud credentials plus the project bindings and identity metadata derived from them."""

    credentials: Credentials
    project: str | None
    quota_project: str | None
    principal: str | None
    impersonated_principal: str | None
    credential_type: str
    using_service_account_key: bool


_CacheKey = tuple[str | None, str | None, str | None, str | None, tuple[str, ...]]
_BUNDLE_CACHE: dict[_CacheKey, GcpCredentialBundle] = {}
_BUNDLE_CACHE_LOCK = threading.Lock()


def resolve_gcp_credentials(config: object | None = None, scopes: Sequence[str] | None = None) -> GcpCredentialBundle:
    """Resolve process-wide Google Cloud credentials from ADC with optional service account impersonation.

    Attribute values on `config` (normally an `OrchestrationConfig`) win over environment variables:
    `google_cloud_project`/`GOOGLE_CLOUD_PROJECT`, `google_cloud_quota_project`/`GOOGLE_CLOUD_QUOTA_PROJECT`,
    `google_impersonate_service_account`/`GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`, and
    `bigquery_dataset_project`/`BIGQUERY_DATASET_PROJECT`.

    Project precedence: explicit `GOOGLE_CLOUD_PROJECT`, then the ADC project, then `BIGQUERY_DATASET_PROJECT`.
    An ADC credential that is already impersonated is reused when it targets the configured principal and
    rejected with `OffloadOptionError` when it targets a different one. Bundles are cached per resolved input
    tuple so repeated client construction does not re-run ADC discovery or mint extra impersonated tokens.
    """
    target_scopes = tuple(scopes) if scopes else DEFAULT_GCP_SCOPES
    explicit_project = _config_or_env(config, "google_cloud_project", "GOOGLE_CLOUD_PROJECT")
    fallback_project = _config_or_env(config, "bigquery_dataset_project", "BIGQUERY_DATASET_PROJECT")
    quota_project = _config_or_env(config, "google_cloud_quota_project", "GOOGLE_CLOUD_QUOTA_PROJECT")
    target_principal = _config_or_env(
        config, "google_impersonate_service_account", "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"
    )
    cache_key: _CacheKey = (explicit_project, fallback_project, quota_project, target_principal, target_scopes)
    with _BUNDLE_CACHE_LOCK:
        bundle = _BUNDLE_CACHE.get(cache_key)
        if bundle is None:
            bundle = _build_bundle(explicit_project, fallback_project, quota_project, target_principal, target_scopes)
            _BUNDLE_CACHE[cache_key] = bundle
    return bundle


def resolve_gcloud_impersonation_principal(config: object | None = None) -> str | None:
    """Return the service account `gcloud` subprocesses impersonate, or None to use the active gcloud account.

    `google_dataproc_impersonate_service_account` (`GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT`) overrides
    `google_impersonate_service_account` (`GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`). The Managed Spark serverless
    runtime service account (`GOOGLE_DATAPROC_SERVICE_ACCOUNT`) is never used for caller impersonation.
    """
    return _config_or_env(
        config, "google_dataproc_impersonate_service_account", "GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT"
    ) or _config_or_env(config, "google_impersonate_service_account", "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")


def clear_gcp_credentials_cache() -> None:
    """Drop every cached credential bundle; unit tests call this to isolate ADC/environment patches."""
    with _BUNDLE_CACHE_LOCK:
        _BUNDLE_CACHE.clear()


def classify_credentials(credentials: Credentials) -> str:
    """Return a stable credential type label for diagnostics, matching the ADC file `type` vocabulary."""
    if isinstance(credentials, impersonated_credentials.Credentials):
        return CREDENTIAL_TYPE_IMPERSONATED
    if isinstance(credentials, service_account.Credentials):
        return CREDENTIAL_TYPE_SERVICE_ACCOUNT_KEY
    if isinstance(credentials, user_credentials.Credentials):
        return CREDENTIAL_TYPE_AUTHORIZED_USER
    if isinstance(credentials, external_account.Credentials | external_account_authorized_user.Credentials):
        return CREDENTIAL_TYPE_EXTERNAL_ACCOUNT
    if isinstance(credentials, compute_engine.Credentials):
        return CREDENTIAL_TYPE_COMPUTE_ENGINE
    return type(credentials).__name__


def credential_principal(credentials: Credentials) -> str | None:
    """Return the human-readable identity behind a credential, or None when google-auth does not expose one.

    Compute Engine credentials report `default` until refreshed; callers that need the real email refresh first.
    """
    if isinstance(credentials, user_credentials.Credentials):
        return credentials.account or None
    email = getattr(credentials, "service_account_email", None)
    return email if isinstance(email, str) and email else None


def _build_bundle(
    explicit_project: str | None,
    fallback_project: str | None,
    quota_project: str | None,
    target_principal: str | None,
    target_scopes: tuple[str, ...],
) -> GcpCredentialBundle:
    """Run ADC discovery and wrap the source credential in impersonation when a target principal is set."""
    source_credentials, adc_project = google.auth.default(scopes=list(target_scopes), quota_project_id=quota_project)
    project = explicit_project or adc_project or fallback_project
    using_key = isinstance(source_credentials, service_account.Credentials)
    if not target_principal:
        return GcpCredentialBundle(
            credentials=source_credentials,
            project=project,
            quota_project=quota_project,
            principal=credential_principal(source_credentials),
            impersonated_principal=None,
            credential_type=classify_credentials(source_credentials),
            using_service_account_key=using_key,
        )
    if isinstance(source_credentials, impersonated_credentials.Credentials):
        existing_principal = source_credentials.service_account_email
        if existing_principal != target_principal:
            raise OffloadOptionError(
                f"ADC credentials are already impersonating {existing_principal}, which conflicts with "
                f"GOOGLE_IMPERSONATE_SERVICE_ACCOUNT={target_principal}"
            )
        credentials: Credentials = source_credentials
    else:
        credentials = impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=target_principal,
            target_scopes=list(target_scopes),
            lifetime=IMPERSONATION_LIFETIME_SECONDS,
            quota_project_id=quota_project,
        )
    return GcpCredentialBundle(
        credentials=credentials,
        project=project,
        quota_project=quota_project,
        principal=target_principal,
        impersonated_principal=target_principal,
        credential_type=CREDENTIAL_TYPE_IMPERSONATED,
        using_service_account_key=using_key,
    )


def _config_or_env(config: object | None, attribute: str, env_name: str) -> str | None:
    """Return a non-empty config attribute value, falling back to a non-empty environment variable."""
    value = getattr(config, attribute, None) if config is not None else None
    return value or os.environ.get(env_name) or None
