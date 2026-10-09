# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Core utility methods and lazy re-exports for the GOE Listener service."""

from typing import TYPE_CHECKING, Any

from goe.cli._lazy import LazyImportMap, resolve_lazy_attribute
from goe.listener.utils import system
from goe.listener.utils.cache import cache
from goe.listener.utils.group_by import groupby

if TYPE_CHECKING:
    from goe.listener.utils import orchestrate
    from goe.listener.utils.ping import ping

__all__ = ["cache", "groupby", "orchestrate", "ping", "system"]

_LAZY_IMPORTS: LazyImportMap = {
    "orchestrate": ("goe.listener.utils.orchestrate", None),
    "ping": ("goe.listener.utils.ping", "ping"),
}


def __getattr__(name: str) -> Any:
    """Lazily resolve heavy listener orchestration and HTTP ping utilities on attribute access."""
    return resolve_lazy_attribute(__name__, _LAZY_IMPORTS, name)
