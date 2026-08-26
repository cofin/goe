# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Base structs and schemas for GOE using msgspec."""

from typing import Any

from msgspec import Struct, convert

__all__ = (
    "BaseStruct",
    "CamelizedBaseStruct",
    "CamelizedFrozenStruct",
    "FrozenBaseStruct",
    "Message",
)


class BaseStruct(Struct):
    """Base struct configuration for all schemas."""


class CamelizedBaseStruct(BaseStruct, rename="camel"):
    """Base struct with camelCase field names for API responses."""


class FrozenBaseStruct(Struct, frozen=True):
    """Base frozen struct configuration for immutable schemas."""


class CamelizedFrozenStruct(FrozenBaseStruct, rename="camel", frozen=True):
    """Base frozen struct with camelCase field names."""


class Message(CamelizedBaseStruct):
    """Simple message response schema."""

    message: str
