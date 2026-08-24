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

"""Serialization utilities for GOE leveraging sqlspec/msgspec."""

import datetime
from typing import Any

from sqlspec.utils.serializers import (
    DEFAULT_TYPE_ENCODERS,
    from_json,
    schema_dump,
    to_json,
)


def _default(obj: Any) -> Any:
    """Fallback serialization hook handling custom domain objects with .dsl or .id."""
    if hasattr(obj, "dsl"):
        return obj.dsl
    if hasattr(obj, "id"):
        return str(obj.id)
    return str(obj)


def serialize_object(obj: Any) -> str:
    """Encodes an object to a JSON string using sqlspec/msgspec."""
    try:
        return to_json(obj)
    except Exception:
        from msgspec.json import Encoder

        return Encoder(enc_hook=_default).encode(obj).decode()


def serialize_object_bytes(obj: Any) -> bytes:
    """Encodes an object to JSON bytes using sqlspec/msgspec."""
    try:
        return to_json(obj, as_bytes=True)
    except Exception:
        from msgspec.json import Encoder

        return Encoder(enc_hook=_default).encode(obj)


def deserialize_object(obj: bytes | bytearray | memoryview | str) -> Any:
    """Decodes a JSON payload to a Python object using sqlspec/msgspec."""
    return from_json(obj)


def encode_datetime_object(dt: datetime.datetime) -> str:
    """Handles datetime serialization for nested timestamps in models/dataclasses."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.isoformat().replace("+00:00", "Z")


__all__ = (
    "DEFAULT_TYPE_ENCODERS",
    "deserialize_object",
    "encode_datetime_object",
    "from_json",
    "schema_dump",
    "serialize_object",
    "serialize_object_bytes",
    "to_json",
)
