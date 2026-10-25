# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for immutable OffloadMetadata, CommandExecutionRecord, and CommandStepRecord models."""

import datetime

import pytest

from goe.orchestration.execution_id import ExecutionId
from goe.persistence.models import (
    ALL_METADATA_ATTRIBUTES,
    HADOOP_OWNER,
    INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
    OFFLOADED_OWNER,
    CommandExecutionRecord,
    CommandStepRecord,
    OffloadMetadata,
    OffloadMetadataRow,
    RepoQuantityUnit,
    add_missing_metadata_keys,
)
from goe.persistence.schemas import CommandExecutionRow, CommandExecutionStepRow


def test_offload_metadata_from_attributes_and_immutability() -> None:
    """OffloadMetadata is frozen and supports copy-on-write updates via with_updates and with_join_target."""
    exec_id = ExecutionId()
    meta = OffloadMetadata.from_attributes(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="goe_sh",
        backend_table="sales",
        offload_type="FULL",
        incremental_key="TIME_ID",
        incremental_high_value="TO_DATE('2025-01-01','YYYY-MM-DD')",
        incremental_range="PARTITION",
        incremental_predicate_type=INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
        incremental_predicate_value=["(column(CHANNEL_ID) = numeric(3))"],
        offload_bucket_column="PROD_ID",
        offload_sort_columns="CUST_ID",
        offload_snapshot=123456,
        offload_partition_functions="UDF1",
        command_execution=exec_id,
    )
    assert meta.offloaded_owner == "SH"
    assert meta.offloaded_table == "SALES"
    assert meta.backend_owner == "goe_sh"
    assert meta.backend_table == "sales"
    assert meta.offload_type == "FULL"
    assert meta.incremental_key == "TIME_ID"
    assert meta.incremental_high_value == "TO_DATE('2025-01-01','YYYY-MM-DD')"
    assert meta.incremental_range == "PARTITION"
    assert meta.incremental_predicate_type == INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE
    assert meta.incremental_predicate_value == ["(column(CHANNEL_ID) = numeric(3))"]
    assert meta.offload_bucket_column == "PROD_ID"
    assert meta.offload_sort_columns == "CUST_ID"
    assert meta.offload_snapshot == 123456
    assert meta.offload_partition_functions == "UDF1"
    assert meta.command_execution == exec_id

    with pytest.raises(AttributeError):
        meta.offload_type = "INCREMENTAL"  # type: ignore[misc]

    updated = meta.with_updates(offload_type="INCREMENTAL")
    assert updated.offload_type == "INCREMENTAL"
    assert meta.offload_type == "FULL"

    joined = meta.with_join_target("SH2", "SALES2")
    assert joined.offloaded_owner == "SH2"
    assert joined.offloaded_table == "SALES2"
    assert meta.offloaded_owner == "SH"


def test_offload_metadata_from_repo_row_and_to_repo_binds_round_trip() -> None:
    """from_repo_row and to_repo_binds round-trip all 15 columns including inline JSON CLOBs and UUID bytes."""
    exec_id = ExecutionId()
    row = OffloadMetadataRow(
        frontend_object_owner="SH",
        frontend_object_name="SALES",
        backend_object_owner="goe_sh",
        backend_object_name="sales",
        offload_type="INCREMENTAL",
        offload_range_type="PARTITION",
        offload_key="TIME_ID",
        offload_high_value="100",
        offload_predicate_type="PREDICATE",
        offload_predicate_value='["(column(COL) > numeric(10))"]',
        offload_snapshot=999,
        offload_hash_column="CUST_ID",
        offload_sort_columns="PROD_ID",
        offload_partition_functions="FN_PART",
        command_execution=exec_id.as_bytes(),
    )
    meta = OffloadMetadata.from_repo_row(row)
    assert meta.offloaded_owner == "SH"
    assert meta.incremental_predicate_value == ["(column(COL) > numeric(10))"]
    assert isinstance(meta.command_execution, ExecutionId)
    assert meta.command_execution == exec_id

    binds = meta.to_repo_binds()
    assert binds["FRONTEND_OBJECT_OWNER"] == "SH"
    assert binds["BACKEND_OBJECT_OWNER"] == "goe_sh"
    assert binds["OFFLOAD_PREDICATE_VALUE"] == '["(column(COL) > numeric(10))"]'
    assert binds["COMMAND_EXECUTION"] == exec_id.as_bytes()


def test_offload_metadata_as_dict_and_from_legacy_dict() -> None:
    """as_dict and from_legacy_dict preserve all 15 upper-case metadata keys."""
    exec_id = ExecutionId()
    meta = OffloadMetadata.from_attributes(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="goe_sh",
        backend_table="sales",
        offload_type="FULL",
        command_execution=exec_id,
    )
    legacy = meta.as_dict()
    assert set(legacy.keys()) == set(ALL_METADATA_ATTRIBUTES)
    assert legacy[OFFLOADED_OWNER] == "SH"
    assert legacy[HADOOP_OWNER] == "goe_sh"
    assert OffloadMetadata.from_legacy_dict(legacy) == meta
    assert OffloadMetadata.from_legacy_dict(meta) is meta

    partial: dict[str, object] = {OFFLOADED_OWNER: "SH"}
    add_missing_metadata_keys(partial)
    assert set(partial.keys()) == set(ALL_METADATA_ATTRIBUTES)


def test_offload_metadata_domain_helpers() -> None:
    """Domain helpers compute HWM presence, subpartition flag, feature description, and HWM column names."""
    full_meta = OffloadMetadata.from_attributes(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="goe_sh",
        backend_table="sales",
        offload_type="FULL",
    )
    assert full_meta.is_hwm_in_hybrid_view() is False
    assert full_meta.is_subpartition_offload() is False
    assert full_meta.incremental_data_append_feature() == "Full Offload"
    assert full_meta.hwm_column_names() == []
    assert full_meta.decode_incremental_predicate_values() is None

    part_meta = full_meta.with_updates(
        incremental_key="time_id, prod_id",
        incremental_high_value="100",
        incremental_range="PARTITION",
    )
    assert part_meta.is_hwm_in_hybrid_view() is True
    assert part_meta.is_subpartition_offload() is False
    assert part_meta.incremental_data_append_feature() == "Partition-Based Offload"

    subpart_meta = part_meta.with_updates(
        incremental_range="SUBPARTITION",
        incremental_predicate_type=INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
        incremental_predicate_value=["(column(channel_id) = numeric(3))"],
    )
    assert subpart_meta.is_subpartition_offload() is True
    assert subpart_meta.incremental_data_append_feature() == "Subpartition and Predicate-Based Offload"
    assert subpart_meta.hwm_column_names() == ["CHANNEL_ID", "PROD_ID", "TIME_ID"]
    dsl_list = subpart_meta.decode_incremental_predicate_values(as_dsl=True)
    assert dsl_list == ["column(CHANNEL_ID) = numeric(3)"]
    preds = subpart_meta.decode_incremental_predicate_values(as_dsl=False)
    assert preds is not None and len(preds) == 1


def test_command_execution_and_step_records_from_rows() -> None:
    """CommandExecutionRecord and CommandStepRecord hydrate from row structs and convert back to legacy dicts."""
    assert RepoQuantityUnit.ROWS == "ROWS"
    exec_id = ExecutionId()
    started = datetime.datetime(2026, 10, 24, 12, 0, 0)
    completed = datetime.datetime(2026, 10, 24, 12, 5, 0)

    exec_row = CommandExecutionRow(
        execution_id=exec_id.as_bytes(),
        command_type_code="OFFLOAD",
        command_type="Offload",
        status_code="SUCCESS",
        status="Succeeded",
        started_at=started,
        completed_at=completed,
        command_log_path="/tmp/offload.log",
        command_input="SH.SALES",
        command_parameters='{"execute": true}',
        goe_version="3.0.0",
        goe_build="abc123",
    )
    record = CommandExecutionRecord.from_row(exec_row)
    assert record.execution_id == exec_id
    assert record.command_parameters == {"execute": True}
    legacy_exec = record.to_legacy_dict()
    assert legacy_exec["execution_id"] == exec_id.as_bytes()
    assert legacy_exec["command_parameters"] == '{"execute":true}'

    step_row = CommandExecutionStepRow(
        execution_id=exec_id.as_bytes(),
        step_id=4,
        step_code="OFFLOAD_TRANSPORT",
        step_title="Offload transport",
        step_status_code="SUCCESS",
        step_status="Succeeded",
        started_at=started,
        completed_at=completed,
        step_details='{"rows": 500}',
    )
    step_record = CommandStepRecord.from_row(step_row)
    assert step_record.execution_id == exec_id
    assert step_record.step_id == 4
    assert step_record.step_details == {"rows": 500}
    legacy_step = step_record.to_legacy_dict()
    assert legacy_step["execution_id"] == exec_id.as_bytes()
    assert legacy_step["step_details"] == '{"rows":500}'
