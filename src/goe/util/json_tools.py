# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import datetime
from typing import Any

from sqlspec.utils.serializers import (
    from_json,
    to_json,
)
from sqlspec.utils.text import camelize


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


def convert_field_to_camel_case(string: str) -> str:
    """Convert snake_case string to camelCase using sqlspec.utils.text."""
    return camelize(string)
