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

import datetime
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import msgspec


def _default(obj: Any) -> Any:
    """Fallback serialization hook for msgspec encoder handling custom domain types."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime.datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=datetime.UTC)
        return obj.isoformat().replace("+00:00", "Z")
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, Exception):
        return str(obj)
    if hasattr(obj, "dsl"):
        return obj.dsl
    if hasattr(obj, "tolist") and callable(obj.tolist):
        return obj.tolist()
    if hasattr(obj, "item") and callable(obj.item):
        return obj.item()
    if hasattr(obj, "id"):
        return str(obj.id)
    return str(obj)


_msgspec_json_encoder = msgspec.json.Encoder(enc_hook=_default)
_msgspec_json_decoder = msgspec.json.Decoder()


def serialize_object(obj: Any) -> str:
    """Encodes an object to a JSON string using msgspec."""
    return _msgspec_json_encoder.encode(obj).decode()


def serialize_object_bytes(obj: Any) -> bytes:
    """Encodes an object to JSON bytes using msgspec."""
    return _msgspec_json_encoder.encode(obj)


def deserialize_object(obj: bytes | bytearray | memoryview | str) -> Any:
    """Decodes a JSON payload to a Python object using msgspec."""
    if isinstance(obj, str):
        return _msgspec_json_decoder.decode(obj.encode())
    return _msgspec_json_decoder.decode(obj)


def encode_datetime_object(dt: datetime.datetime) -> str:
    """Handles datetime serialization for nested timestamps in models/dataclasses."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.isoformat().replace("+00:00", "Z")


def convert_field_to_camel_case(string: str) -> str:
    """Convert snake_case string to camelCase."""
    return "".join(word if index == 0 else word.capitalize() for index, word in enumerate(string.split("_")))
