# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Filesystem-backed log file handle supporting local and GCS log paths."""

from typing import TYPE_CHECKING, Any

import fsspec

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute
from goe.util.gcp_credentials import resolve_gcp_credentials

if TYPE_CHECKING:
    from gcsfs.core import GCS_MIN_BLOCK_SIZE

_LAZY_IMPORTS: LazyImportMap = {
    "GCS_MIN_BLOCK_SIZE": ("gcsfs.core", "GCS_MIN_BLOCK_SIZE"),
}


def is_gcs_path(path: str) -> bool:
    return bool(path and path.startswith("gs://"))


def is_valid_path_for_logs(path: str) -> bool:
    return bool(path and (path.startswith("/") or is_gcs_path(path)))


class GOELogFileHandle:
    name: str | None = None

    def __init__(self, path: str, mode: str = "w") -> None:
        self._fs = self._get_fs(path)
        self.name = path
        self._fh = self._open(path, mode=mode)

    def __enter__(self):
        return self._fh

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        if not self._fh.closed:
            return self._fh.close()

    def flush(self):
        """Flush buffered log output to the underlying file handle.

        On GCSFileSystem, _fh.flush() does not flush unless the buffer is beyond the
        minimum block size.
        """
        self._fh.flush()

    def write(self, *args, **kwargs):
        return self._fh.write(*args, **kwargs)

    def _get_fs(self, path: str) -> fsspec.AbstractFileSystem:
        """Get fsspec filesystem for path.

        gs:// paths pass the shared GOE Google Cloud credentials object as the gcsfs token. With token=None gcsfs
        walks google_default -> cache -> cloud -> anon and silently degrades to anonymous access, so an ADC or
        impersonation failure would surface later as a misleading 401/403 on the first log write.
        GOELogFileHandle has no OrchestrationConfig, so resolution reads the same environment variables
        OrchestrationConfig defaults read.
        https://gcsfs.readthedocs.io/en/latest/api.html#gcsfs.core.GCSFileSystem
        """
        if path.startswith("gs://"):
            bind_lazy_imports(__name__, _LAZY_IMPORTS)
            gcp = resolve_gcp_credentials()
            fs_kwargs = {"project": gcp.project} if gcp.project else {}
            fs = fsspec.filesystem("gs", block_size=GCS_MIN_BLOCK_SIZE, token=gcp.credentials, **fs_kwargs)
        else:
            fs = fsspec.filesystem("file")
        return fs

    def _open(self, path: str, mode: str = "w") -> Any:
        return self._fs.open(path, mode=mode)


def __getattr__(name: str) -> Any:
    """Lazily resolve GCS_MIN_BLOCK_SIZE from gcsfs.core on attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
