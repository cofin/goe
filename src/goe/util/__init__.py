# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Focused utility primitives and version metadata for GOE."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path

from packaging.version import Version as GOEVersion

__all__ = [
    "GOEVersion",
    "goe_version",
]


def goe_version() -> str:
    """Return the installed GOE framework version string."""
    offload_home = os.environ.get("OFFLOAD_HOME")
    if offload_home:
        version_file = Path(offload_home) / "version_build"
        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()
    try:
        return importlib.metadata.version("goe-framework")
    except Exception:
        return "1.1.1.dev0"
