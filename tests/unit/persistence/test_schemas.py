# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import pytest

from goe.persistence.schemas import (
    CommandExecutionSchema,
    LogEventSchema,
    OffloadMetadataSchema,
    PartitionMetadataSchema,
    StepDetailSchema,
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


def test_offload_metadata_schema_round_trip():
    meta = OffloadMetadataSchema(
        offloaded_owner="SH",
        offloaded_table="SALES",
        target_owner="goe_target",
        target_table="sales",
        offload_status="ACTIVE",
        incremental_key="TIME_ID",
    )
    encoded = encode_schema(meta)
    decoded = decode_schema(OffloadMetadataSchema, encoded)
    assert decoded.offloaded_owner == "SH"
    assert decoded.offloaded_table == "SALES"
    assert decoded.incremental_key == "TIME_ID"


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
