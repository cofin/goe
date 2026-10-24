# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Core typing primitives and GC-exempt msgspec Struct base classes."""

from collections.abc import Mapping
from typing import Any

import msgspec
from msgspec import UNSET, UnsetType

__all__ = [
    "UNSET",
    "BaseStruct",
    "CamelStruct",
    "FrozenBaseStruct",
    "FrozenCamelStruct",
    "UnsetType",
    "WireFrameStruct",
    "filter_unset",
]


class BaseStruct(msgspec.Struct, gc=False):
    """Mutable msgspec Struct with cyclic garbage collection disabled."""

    def to_dict(self, *, exclude_unset: bool = False) -> dict[str, Any]:
        """Convert the struct into a plain dictionary."""
        raw = msgspec.structs.asdict(self)
        return filter_unset(raw) if exclude_unset else raw


class FrozenBaseStruct(msgspec.Struct, frozen=True, gc=False):
    """Immutable msgspec Struct with cyclic garbage collection disabled."""

    def to_dict(self, *, exclude_unset: bool = False) -> dict[str, Any]:
        """Convert the struct into a plain dictionary."""
        raw = msgspec.structs.asdict(self)
        return filter_unset(raw) if exclude_unset else raw


class WireFrameStruct(msgspec.Struct, frozen=True, gc=False, array_like=True):
    """Compact tuple-backed immutable struct for hot-path wire and plan records."""


class CamelStruct(msgspec.Struct, rename="camel", gc=False):
    """Mutable msgspec Struct with camelCase field renaming and cyclic GC disabled."""


class FrozenCamelStruct(msgspec.Struct, rename="camel", frozen=True, gc=False):
    """Immutable msgspec Struct with camelCase field renaming and cyclic GC disabled."""


def filter_unset(data: Mapping[str, Any] | msgspec.Struct) -> dict[str, Any]:
    """Return a dictionary with all keys whose value is UNSET removed."""
    source = msgspec.structs.asdict(data) if isinstance(data, msgspec.Struct) else data
    return {key: value for key, value in source.items() if value is not UNSET}
