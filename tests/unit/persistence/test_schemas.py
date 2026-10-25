# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from goe.persistence.schemas import (
    ColumnDetail,
    CommandExecutionSchema,
    LogEventSchema,
    PartitionMetadataSchema,
    StepDetailSchema,
    SubPartitionDetail,
    decode_schema,
    encode_schema,
    encode_schema_bytes,
)


def test_step_detail_schema_round_trip():
    step = StepDetailSchema(
        step_name="STEP_CREATE_TABLE",
        status="SUCCESS",
        start_time="2026-08-24T22:00:00Z",
        end_time="2026-08-24T22:01:00Z",
        details={"rows": 1000, "table": "SALES"},
    )
    encoded = encode_schema(step)
    decoded = decode_schema(StepDetailSchema, encoded)
    assert decoded.step_name == "STEP_CREATE_TABLE"
    assert decoded.status == "SUCCESS"
    assert decoded.details == {"rows": 1000, "table": "SALES"}


def test_command_execution_schema_round_trip():
    cmd = CommandExecutionSchema(
        execution_id="86199702-f17b-4fbe-b3ee-8a780bb1f650",
        command_type="OFFLOAD",
        status="EXECUTING",
        parameters={"table": "SH.SALES", "mode": "INCREMENTAL"},
        step_details=[{"step": "STEP_EXTRACT", "status": "SUCCESS"}],
    )
    encoded = encode_schema_bytes(cmd)
    decoded = decode_schema(CommandExecutionSchema, encoded)
    assert decoded.execution_id == "86199702-f17b-4fbe-b3ee-8a780bb1f650"
    assert decoded.command_type == "OFFLOAD"
    assert decoded.parameters == {"table": "SH.SALES", "mode": "INCREMENTAL"}


def test_partition_metadata_schema_round_trip():
    part = PartitionMetadataSchema(
        partition_name="P_2025",
        high_values_csv="2025-01-01",
        partition_size=65536,
        num_rows=1000,
    )
    encoded = encode_schema(part)
    decoded = decode_schema(PartitionMetadataSchema, encoded)
    assert decoded.partition_name == "P_2025"
    assert decoded.partition_size == 65536
    assert decoded.num_rows == 1000


def test_log_event_schema():
    log_event = LogEventSchema(
        message="Offload process started",
        level="INFO",
        execution_id="exec-12345",
    )
    encoded = encode_schema(log_event)
    decoded = decode_schema(LogEventSchema, encoded)
    assert decoded.message == "Offload process started"
    assert decoded.level == "INFO"


def test_column_detail_with_data_precision():
    """Verify ColumnDetail supports both data_precision and data_scale."""
    col = ColumnDetail(
        column_name="AMOUNT",
        data_type="NUMBER",
        data_precision=10,
        data_scale=2,
        is_nullable=False,
    )
    assert col.data_precision == 10
    assert col.data_scale == 2
    assert col.is_nullable is False


def test_subpartition_detail_with_partition_name_and_position():
    """Verify SubPartitionDetail.from_orm and to_dict preserve partition_name and partition_position."""

    class DummyOrmSubpart:
        partition_name = "P_2025"
        partition_position = 1
        subpartition_name = "SP_1"
        subpartition_position = 1
        high_value = "100"

    subpart = SubPartitionDetail.from_orm(DummyOrmSubpart())
    assert subpart.partition_name == "P_2025"
    assert subpart.partition_position == 1
    assert subpart.to_dict() == {
        "partition_name": "P_2025",
        "partition_position": 1,
        "subpartition_name": "SP_1",
        "subpartition_position": 1,
        "high_value": "100",
    }
