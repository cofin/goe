# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Core utility methods and lazy re-exports for the GOE Listener service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from goe.cli._lazy import LazyImportMap, resolve_lazy_attribute

if TYPE_CHECKING:
    from goe.listener.utils import orchestrate

__all__ = ["orchestrate"]

_LAZY_IMPORTS: LazyImportMap = {
    "orchestrate": ("goe.listener.utils.orchestrate", None),
}


def __getattr__(name: str) -> Any:
    """Lazily resolve listener orchestration utilities on attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
