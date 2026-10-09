# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""ASGI application entry point for GOE Listener."""

import os

from goe.config.config_file import load_env
from goe.listener.app import app, create_app

if "PYTEST_CURRENT_TEST" not in os.environ and os.environ.get("GOE_NO_AUTOLOAD_ENV") not in ("1", "true", "TRUE"):
    load_env()

__all__ = ("app", "create_app")
