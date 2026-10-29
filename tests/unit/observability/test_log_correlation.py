# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavior tests for structured log correlation."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.log_correlation import StructuredLogEntry
from goe.observability.spans import traced_command
from goe.serializers import decode_json
from goe.util.goe_log_fh import GOELogFileHandle

EXEC_ID = "2f1b7c1e-0000-4000-8000-000000000030"


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory runtime with log correlation."""
    active = runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    yield active
    runtime.shutdown_observability()


def test_text_mode_is_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOE_LOG_FORMAT", raising=False)
    monkeypatch.delenv("GOE_LOG_JSON_SIDECAR", raising=False)
    target = tmp_path / "offload.log"
    handle = GOELogFileHandle(str(target))
    handle.write("Offload v1\n")
    handle.write("WARNING:sample\n")
    handle.close()
    assert target.read_text() == "Offload v1\nWARNING:sample\n"
    assert not (tmp_path / "offload.log.jsonl").exists()


def test_json_mode_and_sidecar_carry_trace_ids(tmp_path: Path, memory_runtime: runtime.ObservabilityRuntime) -> None:
    json_log = GOELogFileHandle(str(tmp_path / "a.log"), log_format="json")
    sidecar_log = GOELogFileHandle(str(tmp_path / "b.log"), json_sidecar=True)
    with traced_command("OFFLOAD", EXEC_ID):
        json_log.write("WARNING:sample\n")
        sidecar_log.write("plain line\n")
    json_log.close()
    sidecar_log.close()
    entry = decode_json((tmp_path / "a.log").read_bytes().splitlines()[0], target_type=StructuredLogEntry)
    assert entry.level == "WARNING"
    assert entry.execution_id == EXEC_ID
    assert entry.trace_id is not None
    assert (tmp_path / "b.log").read_text() == "plain line\n"
    sidecar = decode_json((tmp_path / "b.log.jsonl").read_bytes().splitlines()[0], target_type=StructuredLogEntry)
    assert sidecar.message == "plain line"


def test_log_records_receive_trace_fields(
    memory_runtime: runtime.ObservabilityRuntime, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        with traced_command("OFFLOAD", EXEC_ID):
            logging.getLogger("goe.test").info("inside")
    record = caplog.records[-1]
    assert record.execution_id == EXEC_ID
    assert len(record.trace_id) == 32


def test_shutdown_restores_record_factory() -> None:
    original = logging.getLogRecordFactory()
    runtime.configure_observability(ObservabilitySettings(enabled=True, exporter="memory"), set_global=False)
    assert logging.getLogRecordFactory() is not original
    runtime.shutdown_observability()
    assert logging.getLogRecordFactory() is original
