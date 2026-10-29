# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Filesystem-backed log file handle supporting local and GCS log paths without fsspec."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any, Self

from google.cloud import storage

from goe.config.gcp_credentials import resolve_gcp_credentials
from goe.observability.config import ObservabilitySettings
from goe.observability.log_correlation import encode_structured_log_line
from goe.observability.runtime import get_observability_runtime, is_observability_configured

__all__ = [
    "GOELogFileHandle",
    "is_gcs_path",
    "is_valid_path_for_logs",
]


def is_gcs_path(path: str | None) -> bool:
    """Return True if path is a gs:// URI."""
    return bool(path and path.startswith("gs://"))


def is_valid_path_for_logs(path: str | None) -> bool:
    """Return True if path is an absolute local path or a gs:// URI."""
    return bool(path and (path.startswith("/") or is_gcs_path(path)))


class GOELogFileHandle:
    """Log file handle writing text or structured JSON lines to local disk or GCS."""

    name: str | None = None

    def __init__(
        self,
        path: str,
        mode: str = "w",
        log_format: str | None = None,
        json_sidecar: bool | None = None,
    ) -> None:
        """Open path; log_format and json_sidecar default to active observability settings."""
        settings = (
            get_observability_runtime().settings
            if is_observability_configured()
            else ObservabilitySettings.from_env_and_config()
        )
        self.name = path
        self._fh = self._open(path, mode=mode)
        self._log_format = log_format or settings.log_format
        use_sidecar = settings.log_json_sidecar if json_sidecar is None else json_sidecar
        writable = "w" in mode or "a" in mode
        self._sidecar_fh = (
            self._open(f"{path}.jsonl", mode=mode) if use_sidecar and writable and self._log_format == "text" else None
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> Any:
        """Close the primary and optional JSONL sidecar file handles."""
        if self._sidecar_fh is not None and not getattr(self._sidecar_fh, "closed", False):
            self._sidecar_fh.close()
        if not getattr(self._fh, "closed", False):
            return self._fh.close()
        return None

    def flush(self) -> None:
        """Flush buffered log output to the underlying file handle."""
        self._fh.flush()
        if self._sidecar_fh is not None:
            self._sidecar_fh.flush()

    def write(self, data: str) -> int:
        """Write data as text or JSON line; mirror JSON to the sidecar when enabled."""
        if self._log_format == "json":
            return int(self._fh.write(encode_structured_log_line(data)))
        written = int(self._fh.write(data))
        if self._sidecar_fh is not None:
            self._sidecar_fh.write(encode_structured_log_line(data))
        return written

    def _open(self, path: str, mode: str = "w") -> Any:
        if is_gcs_path(path):
            without_scheme = path.removeprefix("gs://")
            bucket_name, _, blob_name = without_scheme.partition("/")
            gcp = resolve_gcp_credentials()
            client_kwargs: dict[str, Any] = {"credentials": gcp.credentials}
            if gcp.project:
                client_kwargs["project"] = gcp.project
            client = storage.Client(**client_kwargs)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            return blob.open(mode)
        return Path(path).open(mode=mode, encoding="utf-8")
