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

from typing import Any

import msgspec

from goe.util.json_tools import _default

_schema_encoder = msgspec.json.Encoder(enc_hook=_default)


class StepDetailSchema(msgspec.Struct, kw_only=True):
    """Schema representing step execution details."""

    step_name: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    details: dict[str, Any] | None = None


class CommandExecutionSchema(msgspec.Struct, kw_only=True):
    """Schema representing command execution metadata persisted in repo."""

    execution_id: str
    command_type: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    parameters: dict[str, Any] | None = None
    step_details: list[dict[str, Any]] | None = None


class OffloadMetadataSchema(msgspec.Struct, kw_only=True):
    """Schema representing persisted offload table metadata."""

    offloaded_owner: str
    offloaded_table: str
    target_owner: str
    target_table: str
    offload_status: str | None = None
    offload_snapshot: str | None = None
    offload_predicate: str | None = None
    offload_bucket_column: str | None = None
    offload_sort_columns: str | None = None
    incremental_key: str | None = None
    incremental_high_value: str | None = None
    incremental_range: str | None = None
    incremental_predicate_type: str | None = None
    incremental_predicate_value: str | None = None


class LogEventSchema(msgspec.Struct, kw_only=True):
    """Schema representing real-time log event stream."""

    message: str
    timestamp: str | None = None
    level: str | None = None
    execution_id: str | None = None


class PartitionMetadataSchema(msgspec.Struct, kw_only=True):
    """Schema representing partition descriptor."""

    partition_name: str
    high_value: str | None = None
    position: int | None = None


def encode_schema(struct: msgspec.Struct) -> str:
    """Encode a msgspec Struct to a JSON string."""
    return _schema_encoder.encode(struct).decode()


def encode_schema_bytes(struct: msgspec.Struct) -> bytes:
    """Encode a msgspec Struct to JSON bytes."""
    return _schema_encoder.encode(struct)


def decode_schema[T: msgspec.Struct](schema_type: type[T], payload: bytes | str) -> T:
    """Decode a JSON payload into a typed msgspec Struct."""
    if isinstance(payload, str):
        payload = payload.encode()
    return msgspec.json.decode(payload, type=schema_type)
