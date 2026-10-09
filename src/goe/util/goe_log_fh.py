# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Filesystem-backed log file handle supporting local and GCS log paths."""

from typing import TYPE_CHECKING, Any

import fsspec

from goe.cli._lazy import LazyImportMap, bind_lazy_imports, resolve_lazy_attribute

if TYPE_CHECKING:
    from gcsfs.core import GCS_MIN_BLOCK_SIZE

_LAZY_IMPORTS: LazyImportMap = {
    "GCS_MIN_BLOCK_SIZE": ("gcsfs.core", "GCS_MIN_BLOCK_SIZE"),
}


def is_gcs_path(path: str):
    return bool(path and path.startswith("gs://"))


def is_valid_path_for_logs(path: str):
    return bool(path and (path.startswith("/") or is_gcs_path(path)))


class GOELogFileHandle:
    name: str | None = None

    def __init__(self, path: str, mode="w"):
        self._fs = self._get_fs(path)
        self.name = path
        self._fh = self._open(path, mode=mode)

    def __enter__(self):
        return self._fh

    def __exit__(self, type, value, traceback):
        self.close()

    def _get_fs(self, path: str) -> fsspec.AbstractFileSystem:
        """Get fsspec filesystem for path.

        Do not pass in the token for gs:// paths so that gcsfs will try and get the
        application default credentials from a number of sources. This will raise an
        exception if it cannot authenticate with GCS.
        https://gcsfs.readthedocs.io/en/latest/api.html#gcsfs.core.GCSFileSystem
        """
        if path.startswith("gs://"):
            bind_lazy_imports(__name__, _LAZY_IMPORTS)
            fs = fsspec.filesystem("gs", block_size=GCS_MIN_BLOCK_SIZE)
        else:
            fs = fsspec.filesystem("file")
        return fs

    def _open(self, path: str, mode="w"):
        return self._fs.open(path, mode=mode)

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


def __getattr__(name: str) -> Any:
    """Lazily resolve GCS_MIN_BLOCK_SIZE from gcsfs.core on attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
