# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
