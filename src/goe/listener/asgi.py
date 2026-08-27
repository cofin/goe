# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""ASGI application entry point for GOE Listener."""

from goe.listener.app import app, create_app

__all__ = ("app", "create_app")
