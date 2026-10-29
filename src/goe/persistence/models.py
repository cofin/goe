# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Immutable persistence domain models for offload metadata and command execution records."""

import datetime
from enum import StrEnum
from typing import Any, Final

import msgspec

from goe.offload.predicates import GenericPredicate
from goe.orchestration.execution_id import ExecutionId
from goe.serializers import decode_json, encode_json
from goe.typing import FrozenBaseStruct

__all__ = (
    "ALL_METADATA_ATTRIBUTES",
    "COMMAND_EXECUTION",
    "HADOOP_OWNER",
    "HADOOP_TABLE",
    "INCREMENTAL_HIGH_VALUE",
    "INCREMENTAL_KEY",
    "INCREMENTAL_PREDICATE_TYPE",
    "INCREMENTAL_PREDICATE_TYPES",
    "INCREMENTAL_PREDICATE_TYPES_WITH_PREDICATE_IN_HV",
    "INCREMENTAL_PREDICATE_TYPE_LIST",
    "INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE",
    "INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE",
    "INCREMENTAL_PREDICATE_TYPE_PREDICATE",
    "INCREMENTAL_PREDICATE_TYPE_RANGE",
    "INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE",
    "INCREMENTAL_PREDICATE_VALUE",
    "INCREMENTAL_RANGE",
    "METADATA_ATTRIBUTES",
    "OFFLOADED_OWNER",
    "OFFLOADED_TABLE",
    "OFFLOAD_BUCKET_COLUMN",
    "OFFLOAD_PARTITION_FUNCTIONS",
    "OFFLOAD_SNAPSHOT",
    "OFFLOAD_SORT_COLUMNS",
    "OFFLOAD_TYPE",
    "CommandExecutionRecord",
    "CommandStepRecord",
    "OffloadMetadata",
    "OffloadMetadataRow",
    "RepoQuantityUnit",
    "add_missing_metadata_keys",
    "hwm_column_names_from_predicates",
)

HADOOP_OWNER: Final = "HADOOP_OWNER"
HADOOP_TABLE: Final = "HADOOP_TABLE"
OFFLOAD_TYPE: Final = "OFFLOAD_TYPE"
OFFLOADED_OWNER: Final = "OFFLOADED_OWNER"
OFFLOADED_TABLE: Final = "OFFLOADED_TABLE"
INCREMENTAL_KEY: Final = "INCREMENTAL_KEY"
INCREMENTAL_HIGH_VALUE: Final = "INCREMENTAL_HIGH_VALUE"
INCREMENTAL_RANGE: Final = "INCREMENTAL_RANGE"
INCREMENTAL_PREDICATE_TYPE: Final = "INCREMENTAL_PREDICATE_TYPE"
INCREMENTAL_PREDICATE_VALUE: Final = "INCREMENTAL_PREDICATE_VALUE"
OFFLOAD_BUCKET_COLUMN: Final = "OFFLOAD_BUCKET_COLUMN"
OFFLOAD_SORT_COLUMNS: Final = "OFFLOAD_SORT_COLUMNS"
OFFLOAD_SNAPSHOT: Final = "OFFLOAD_SNAPSHOT"
OFFLOAD_PARTITION_FUNCTIONS: Final = "OFFLOAD_PARTITION_FUNCTIONS"
COMMAND_EXECUTION: Final = "COMMAND_EXECUTION"

ALL_METADATA_ATTRIBUTES: Final[tuple[str, ...]] = (
    HADOOP_OWNER,
    HADOOP_TABLE,
    OFFLOAD_TYPE,
    OFFLOADED_OWNER,
    OFFLOADED_TABLE,
    INCREMENTAL_KEY,
    INCREMENTAL_HIGH_VALUE,
    INCREMENTAL_RANGE,
    INCREMENTAL_PREDICATE_TYPE,
    INCREMENTAL_PREDICATE_VALUE,
    OFFLOAD_BUCKET_COLUMN,
    OFFLOAD_SORT_COLUMNS,
    OFFLOAD_SNAPSHOT,
    OFFLOAD_PARTITION_FUNCTIONS,
    COMMAND_EXECUTION,
)

METADATA_ATTRIBUTES: Final[dict[str, str]] = {
    "backend_owner": HADOOP_OWNER,
    "backend_table": HADOOP_TABLE,
    "offload_type": OFFLOAD_TYPE,
    "offloaded_owner": OFFLOADED_OWNER,
    "offloaded_table": OFFLOADED_TABLE,
    "incremental_key": INCREMENTAL_KEY,
    "incremental_high_value": INCREMENTAL_HIGH_VALUE,
    "incremental_range": INCREMENTAL_RANGE,
    "incremental_predicate_type": INCREMENTAL_PREDICATE_TYPE,
    "incremental_predicate_value": INCREMENTAL_PREDICATE_VALUE,
    "offload_bucket_column": OFFLOAD_BUCKET_COLUMN,
    "offload_sort_columns": OFFLOAD_SORT_COLUMNS,
    "offload_snapshot": OFFLOAD_SNAPSHOT,
    "offload_partition_functions": OFFLOAD_PARTITION_FUNCTIONS,
    "command_execution": COMMAND_EXECUTION,
}

INCREMENTAL_PREDICATE_TYPE_PREDICATE: Final = "PREDICATE"
INCREMENTAL_PREDICATE_TYPE_LIST: Final = "LIST"
INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE: Final = "LIST_AS_RANGE"
INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE: Final = "LIST_AS_RANGE_AND_PREDICATE"
INCREMENTAL_PREDICATE_TYPE_RANGE: Final = "RANGE"
INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE: Final = "RANGE_AND_PREDICATE"

INCREMENTAL_PREDICATE_TYPES_WITH_PREDICATE_IN_HV: Final[tuple[str, ...]] = (
    INCREMENTAL_PREDICATE_TYPE_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
)

INCREMENTAL_PREDICATE_TYPES: Final[tuple[str, ...]] = (
    INCREMENTAL_PREDICATE_TYPE_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
    INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
)


class RepoQuantityUnit(StrEnum):
    """Units recorded by repository chunk and step metrics."""

    ROWS = "ROWS"
    BYTES = "BYTES"
    PARTITIONS = "PARTITIONS"


def add_missing_metadata_keys(metadata_dict: dict[str, Any]) -> None:
    """Populate missing upper-case metadata keys with None in a legacy dictionary."""
    for key_name in METADATA_ATTRIBUTES.values():
        if key_name not in metadata_dict:
            metadata_dict[key_name] = None


def hwm_column_names_from_predicates(offload_predicates: list[GenericPredicate] | None) -> list[str]:
    """Return sorted unique upper-case column names referenced across offload predicates."""
    if not offload_predicates:
        return []
    col_set: set[str] = set()
    for predicate in offload_predicates:
        for col_name in predicate.column_names():
            col_set.add(col_name.upper())
    return sorted(col_set)


class OffloadMetadataRow(FrozenBaseStruct, frozen=True, kw_only=True):
    """Row projected from ``offload_metadata_v`` with ``fetch_lobs=False``."""

    frontend_object_owner: str
    frontend_object_name: str
    backend_object_owner: str
    backend_object_name: str
    offload_type: str
    offload_range_type: str | None = None
    offload_key: str | None = None
    offload_high_value: str | None = None
    offload_predicate_type: str | None = None
    offload_predicate_value: str | None = None
    offload_snapshot: int | str | None = None
    offload_hash_column: str | None = None
    offload_sort_columns: str | None = None
    offload_partition_functions: str | None = None
    command_execution: Any = None


class OffloadMetadata(FrozenBaseStruct, frozen=True, kw_only=True):
    """Immutable offload metadata for a single hybrid frontend/backend table pair."""

    offloaded_owner: str
    offloaded_table: str
    backend_owner: str
    backend_table: str
    offload_type: str
    incremental_key: str | None = None
    incremental_high_value: str | None = None
    incremental_range: str | None = None
    incremental_predicate_type: str | None = None
    incremental_predicate_value: list[str] | None = None
    offload_bucket_column: str | None = None
    offload_sort_columns: str | None = None
    offload_snapshot: int | str | None = None
    offload_partition_functions: str | None = None
    command_execution: ExecutionId | None = None

    @classmethod
    def from_attributes(cls, **kwargs: Any) -> "OffloadMetadata":
        """Construct ``OffloadMetadata`` from keyword attributes, ignoring legacy client/config kwargs."""
        raw_exec = kwargs.get("command_execution")
        exec_id = _coerce_execution_id(raw_exec)
        pred_val = kwargs.get("incremental_predicate_value")
        if isinstance(pred_val, str):
            pred_val = decode_json(pred_val)
        return cls(
            offloaded_owner=str(kwargs.get("offloaded_owner") or ""),
            offloaded_table=str(kwargs.get("offloaded_table") or ""),
            backend_owner=str(kwargs.get("backend_owner") or ""),
            backend_table=str(kwargs.get("backend_table") or ""),
            offload_type=str(kwargs.get("offload_type") or ""),
            incremental_key=kwargs.get("incremental_key") or None,
            incremental_high_value=kwargs.get("incremental_high_value") or None,
            incremental_range=kwargs.get("incremental_range") or None,
            incremental_predicate_type=kwargs.get("incremental_predicate_type") or None,
            incremental_predicate_value=list(pred_val) if pred_val else None,
            offload_bucket_column=kwargs.get("offload_bucket_column") or None,
            offload_sort_columns=kwargs.get("offload_sort_columns") or None,
            offload_snapshot=kwargs.get("offload_snapshot") or None,
            offload_partition_functions=kwargs.get("offload_partition_functions") or None,
            command_execution=exec_id,
        )

    @classmethod
    def from_legacy_dict(cls, metadata_dict: "dict[str, Any] | OffloadMetadata") -> "OffloadMetadata":
        """Construct ``OffloadMetadata`` from a legacy upper-case metadata dictionary or existing instance."""
        if isinstance(metadata_dict, OffloadMetadata):
            return metadata_dict
        return cls.from_attributes(
            offloaded_owner=metadata_dict.get(OFFLOADED_OWNER),
            offloaded_table=metadata_dict.get(OFFLOADED_TABLE),
            backend_owner=metadata_dict.get(HADOOP_OWNER),
            backend_table=metadata_dict.get(HADOOP_TABLE),
            offload_type=metadata_dict.get(OFFLOAD_TYPE),
            incremental_key=metadata_dict.get(INCREMENTAL_KEY),
            incremental_high_value=metadata_dict.get(INCREMENTAL_HIGH_VALUE),
            incremental_range=metadata_dict.get(INCREMENTAL_RANGE),
            incremental_predicate_type=metadata_dict.get(INCREMENTAL_PREDICATE_TYPE),
            incremental_predicate_value=metadata_dict.get(INCREMENTAL_PREDICATE_VALUE),
            offload_bucket_column=metadata_dict.get(OFFLOAD_BUCKET_COLUMN),
            offload_sort_columns=metadata_dict.get(OFFLOAD_SORT_COLUMNS),
            offload_snapshot=metadata_dict.get(OFFLOAD_SNAPSHOT),
            offload_partition_functions=metadata_dict.get(OFFLOAD_PARTITION_FUNCTIONS),
            command_execution=metadata_dict.get(COMMAND_EXECUTION),
        )

    @classmethod
    def from_repo_row(cls, row: OffloadMetadataRow) -> "OffloadMetadata":
        """Hydrate ``OffloadMetadata`` from an ``offload_metadata_v`` row."""
        raw_pred = row.offload_predicate_value
        decoded_pred = decode_json(raw_pred) if raw_pred else None
        return cls(
            offloaded_owner=row.frontend_object_owner,
            offloaded_table=row.frontend_object_name,
            backend_owner=row.backend_object_owner,
            backend_table=row.backend_object_name,
            offload_type=row.offload_type,
            incremental_key=row.offload_key or None,
            incremental_high_value=row.offload_high_value or None,
            incremental_range=row.offload_range_type or None,
            incremental_predicate_type=row.offload_predicate_type or None,
            incremental_predicate_value=list(decoded_pred) if decoded_pred else None,
            offload_bucket_column=row.offload_hash_column or None,
            offload_sort_columns=row.offload_sort_columns or None,
            offload_snapshot=row.offload_snapshot or None,
            offload_partition_functions=row.offload_partition_functions or None,
            command_execution=_coerce_execution_id(row.command_execution),
        )

    def to_repo_binds(self) -> dict[str, Any]:
        """Return attribute dictionary matching Oracle ``OFFLOAD_METADATA_OT`` fields."""
        return {
            "FRONTEND_OBJECT_OWNER": self.offloaded_owner,
            "FRONTEND_OBJECT_NAME": self.offloaded_table,
            "BACKEND_OBJECT_OWNER": self.backend_owner,
            "BACKEND_OBJECT_NAME": self.backend_table,
            "OFFLOAD_TYPE": self.offload_type,
            "OFFLOAD_RANGE_TYPE": self.incremental_range,
            "OFFLOAD_KEY": self.incremental_key,
            "OFFLOAD_HIGH_VALUE": self.incremental_high_value,
            "OFFLOAD_PREDICATE_TYPE": self.incremental_predicate_type,
            "OFFLOAD_PREDICATE_VALUE": (
                encode_json(self.incremental_predicate_value) if self.incremental_predicate_value is not None else None
            ),
            "OFFLOAD_SNAPSHOT": self.offload_snapshot,
            "OFFLOAD_HASH_COLUMN": self.offload_bucket_column,
            "OFFLOAD_SORT_COLUMNS": self.offload_sort_columns,
            "OFFLOAD_PARTITION_FUNCTIONS": self.offload_partition_functions,
            "COMMAND_EXECUTION": self.command_execution.as_bytes() if self.command_execution is not None else None,
        }

    def as_dict(self) -> dict[str, Any]:
        """Return a dictionary keyed by legacy upper-case metadata attribute constants."""
        return {
            HADOOP_OWNER: self.backend_owner,
            HADOOP_TABLE: self.backend_table,
            OFFLOAD_TYPE: self.offload_type,
            OFFLOADED_OWNER: self.offloaded_owner,
            OFFLOADED_TABLE: self.offloaded_table,
            INCREMENTAL_KEY: self.incremental_key,
            INCREMENTAL_HIGH_VALUE: self.incremental_high_value,
            INCREMENTAL_RANGE: self.incremental_range,
            INCREMENTAL_PREDICATE_TYPE: self.incremental_predicate_type,
            INCREMENTAL_PREDICATE_VALUE: self.incremental_predicate_value,
            OFFLOAD_BUCKET_COLUMN: self.offload_bucket_column,
            OFFLOAD_SORT_COLUMNS: self.offload_sort_columns,
            OFFLOAD_SNAPSHOT: self.offload_snapshot,
            OFFLOAD_PARTITION_FUNCTIONS: self.offload_partition_functions,
            COMMAND_EXECUTION: self.command_execution,
        }

    def with_updates(self, **changes: Any) -> "OffloadMetadata":
        """Return a copy of this metadata struct with the specified fields replaced."""
        return msgspec.structs.replace(self, **changes)

    def with_join_target(self, offloaded_owner: str, offloaded_table: str) -> "OffloadMetadata":
        """Return a copy with ``offloaded_owner`` and ``offloaded_table`` updated for join presentation."""
        return msgspec.structs.replace(
            self,
            offloaded_owner=offloaded_owner,
            offloaded_table=offloaded_table,
        )

    def decode_incremental_predicate_values(self, as_dsl: bool = False) -> list[Any] | None:
        """Convert ``incremental_predicate_value`` strings into ``GenericPredicate`` objects or normalized DSL strings."""
        if not self.incremental_predicate_value:
            return None
        if as_dsl:
            return [GenericPredicate(dsl).dsl for dsl in self.incremental_predicate_value]
        return [GenericPredicate(dsl) for dsl in self.incremental_predicate_value]

    def hwm_column_names(self) -> list[str]:
        """Return sorted unique upper-case column names in the hybrid view HWM predicate."""
        if not self.is_hwm_in_hybrid_view():
            return []
        inc_keys = _csv_split_upper(self.incremental_key) if self.incremental_key else []
        pred_cols = hwm_column_names_from_predicates(self.decode_incremental_predicate_values())
        return sorted(set(inc_keys + pred_cols))

    def incremental_data_append_feature(self) -> str:
        """Return the human-readable feature name for this metadata's offload configuration."""
        ida_features: list[str] = []
        if self.incremental_range:
            ida_features.append(self.incremental_range.title())
        if self.incremental_predicate_type in INCREMENTAL_PREDICATE_TYPES_WITH_PREDICATE_IN_HV:
            ida_features.append("Predicate")
        if ida_features:
            return " and ".join(ida_features) + "-Based Offload"
        return "Full Offload"

    def is_hwm_in_hybrid_view(self) -> bool:
        """Return True if the hybrid view contains a high-water-mark or predicate UNION ALL branch."""
        return bool((self.incremental_key and self.incremental_high_value) or self.incremental_predicate_value)

    def is_subpartition_offload(self) -> bool:
        """Return True when this table is offloaded at the subpartition level."""
        return bool(self.incremental_range == "SUBPARTITION")


class CommandExecutionRecord(FrozenBaseStruct, frozen=True, kw_only=True):
    """Typed command execution history record."""

    execution_id: ExecutionId
    command_type_code: str
    command_type: str
    status_code: str
    status: str
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    command_log_path: str
    command_input: str
    command_parameters: dict[str, Any] | None
    goe_version: str
    goe_build: str

    @classmethod
    def from_row(cls, row: Any) -> "CommandExecutionRecord":
        """Convert a ``CommandExecutionRow`` into a ``CommandExecutionRecord``."""
        params = decode_json(row.command_parameters) if row.command_parameters else None
        return cls(
            execution_id=_coerce_execution_id(row.execution_id) or ExecutionId(),
            command_type_code=row.command_type_code,
            command_type=row.command_type,
            status_code=row.status_code,
            status=row.status,
            started_at=row.started_at,
            completed_at=row.completed_at,
            command_log_path=row.command_log_path,
            command_input=row.command_input,
            command_parameters=params if isinstance(params, dict) else None,
            goe_version=row.goe_version,
            goe_build=row.goe_build,
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        """Return the legacy dictionary representation expected by Listener and CLI callers."""
        return {
            "execution_id": self.execution_id.as_bytes(),
            "command_type_code": self.command_type_code,
            "command_type": self.command_type,
            "status_code": self.status_code,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "command_log_path": self.command_log_path,
            "command_input": self.command_input,
            "command_parameters": encode_json(self.command_parameters) if self.command_parameters is not None else None,
            "goe_version": self.goe_version,
            "goe_build": self.goe_build,
        }


class CommandStepRecord(FrozenBaseStruct, frozen=True, kw_only=True):
    """Typed command execution step record."""

    execution_id: ExecutionId
    step_id: int
    step_code: str
    step_title: str
    step_status_code: str
    step_status: str
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    step_details: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Any) -> "CommandStepRecord":
        """Convert a ``CommandExecutionStepRow`` into a ``CommandStepRecord``."""
        details = decode_json(row.step_details) if row.step_details else None
        return cls(
            execution_id=_coerce_execution_id(row.execution_id) or ExecutionId(),
            step_id=int(row.step_id),
            step_code=row.step_code,
            step_title=row.step_title,
            step_status_code=row.step_status_code,
            step_status=row.step_status,
            started_at=row.started_at,
            completed_at=row.completed_at,
            step_details=details if isinstance(details, dict) else None,
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        """Return the legacy dictionary representation expected by Listener callers."""
        return {
            "execution_id": self.execution_id.as_bytes(),
            "step_id": self.step_id,
            "step_code": self.step_code,
            "step_title": self.step_title,
            "step_status_code": self.step_status_code,
            "step_status": self.step_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "step_details": encode_json(self.step_details) if self.step_details is not None else None,
        }


def _coerce_execution_id(value: Any) -> ExecutionId | None:
    """Convert raw bytes, string, or ExecutionId into an ExecutionId or None."""
    if value is None:
        return None
    if isinstance(value, ExecutionId):
        return value
    if isinstance(value, bytes):
        return ExecutionId.from_bytes(value)
    return ExecutionId.from_str(str(value))


def _csv_split_upper(csv_string: str) -> list[str]:
    """Split a comma-separated string into stripped upper-case tokens."""
    return [token.strip().upper() for token in csv_string.split(",") if token.strip()]
