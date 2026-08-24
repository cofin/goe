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

from collections.abc import Mapping
from typing import Any

from goe.persistence.schemas import (
    CommandExecutionSchema,
    OffloadMetadataSchema,
    StepDetailSchema,
    decode_schema,
    encode_schema,
)


class SQLSpecRepositoryClient:
    """Repository client interface leveraging SQLSpec and msgspec Structs for metadata management."""

    def __init__(self, connection_config: Mapping[str, Any] | None = None):
        self._connection_config = dict(connection_config or {})

    def format_command_execution(self, schema: CommandExecutionSchema) -> str:
        """Serialize a command execution record to JSON string."""
        return encode_schema(schema)

    def parse_command_execution(self, payload: bytes | str) -> CommandExecutionSchema:
        """Parse JSON payload into a CommandExecutionSchema."""
        return decode_schema(CommandExecutionSchema, payload)

    def format_offload_metadata(self, schema: OffloadMetadataSchema) -> str:
        """Serialize offload table metadata to JSON string."""
        return encode_schema(schema)

    def parse_offload_metadata(self, payload: bytes | str) -> OffloadMetadataSchema:
        """Parse JSON payload into an OffloadMetadataSchema."""
        return decode_schema(OffloadMetadataSchema, payload)

    def format_step_detail(self, schema: StepDetailSchema) -> str:
        """Serialize step detail record to JSON string."""
        return encode_schema(schema)

    def parse_step_detail(self, payload: bytes | str) -> StepDetailSchema:
        """Parse JSON payload into a StepDetailSchema."""
        return decode_schema(StepDetailSchema, payload)
