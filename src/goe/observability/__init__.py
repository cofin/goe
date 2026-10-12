# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OpenTelemetry tracing, metrics, and log correlation for GOE.

Import concrete helpers from the submodules (``goe.observability.config``, ``.context``, ``.metrics``,
``.runtime``). The package itself re-exports nothing so that importing it never loads the optional SDK.
"""
