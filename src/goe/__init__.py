# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import importlib.metadata
import os

from goe.config.config_file import load_env

__version__ = importlib.metadata.version("goe-framework")


def _autoload_environment() -> None:
    """Automatically load environment variables from offload.env unless opted out.

    Bypasses auto-loading if GOE_NO_AUTOLOAD_ENV is set to '1' or 'true',
    or if executing inside a pytest runner (PYTEST_CURRENT_TEST is present).
    """
    if os.environ.get("GOE_NO_AUTOLOAD_ENV", "").lower() in ("1", "true"):
        return
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    load_env()


_autoload_environment()
