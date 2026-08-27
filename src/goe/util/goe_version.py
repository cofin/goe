# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import importlib.metadata
import os

try:
    from packaging.version import Version as GOEVersion
except ModuleNotFoundError:
    pass


def goe_version() -> str:
    """Returns the installed GOE framework version string."""
    offload_home = os.environ.get("OFFLOAD_HOME")
    if offload_home:
        version_file = os.path.join(offload_home, "version_build")
        if os.path.exists(version_file):
            with open(version_file) as f:
                return f.read().strip()
    try:
        return importlib.metadata.version("goe-framework")
    except Exception:
        return "1.1.1.dev0"


__all__ = ("GOEVersion", "goe_version")
