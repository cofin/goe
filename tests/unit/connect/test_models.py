# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for CheckDetail, CheckResult, and ConnectivityReport models."""

from __future__ import annotations

import gc

import pytest

from goe.connect.models import CheckDetail, CheckResult, ConnectivityReport
from goe.serializers import decode_json
from goe.typing import FrozenBaseStruct


def test_check_result_and_connectivity_report_frozen_and_gc_exempt() -> None:
    """CheckDetail, CheckResult, and ConnectivityReport inherit from FrozenBaseStruct and are GC-exempt."""
    detail = CheckDetail(label="ORA_CONN", value="ora-host:1521/ORCL")
    result = CheckResult(
        name="ORACLE frontend connection",
        category="frontend",
        status="passed",
        duration_ms=4.5,
        details=(detail,),
    )
    report = ConnectivityReport(
        environment_summary="Host: dev | OS: Ubuntu 24.04 | Python: 3.12.0",
        results=(result,),
        total_duration_ms=4.5,
    )

    assert isinstance(detail, FrozenBaseStruct)
    assert isinstance(result, FrozenBaseStruct)
    assert isinstance(report, FrozenBaseStruct)
    assert not gc.is_tracked(detail)
    assert not gc.is_tracked(result)
    assert not gc.is_tracked(report)

    with pytest.raises(AttributeError):
        detail.value = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.status = "failed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        report.total_duration_ms = 99.0  # type: ignore[misc]


def test_connectivity_report_computed_aggregates() -> None:
    """ConnectivityReport computes failure_count, warning_count, passed, has_warnings, and exit_code."""
    passing_report = ConnectivityReport(
        environment_summary="Host: dev",
        results=(
            CheckResult(name="Frontend", category="frontend", status="passed"),
            CheckResult(name="Storage", category="storage", status="warning", message="Slow bucket"),
            CheckResult(name="SSH", category="transport", status="skipped"),
        ),
    )
    assert passing_report.failure_count == 0
    assert passing_report.warning_count == 1
    assert passing_report.passed is True
    assert passing_report.has_warnings is True
    assert passing_report.exit_code == 0

    failing_report = ConnectivityReport(
        environment_summary="Host: dev",
        results=(
            CheckResult(name="Frontend", category="frontend", status="passed"),
            CheckResult(name="Backend", category="backend", status="failed", message="Permission denied"),
        ),
    )
    assert failing_report.failure_count == 1
    assert failing_report.warning_count == 0
    assert failing_report.passed is False
    assert failing_report.has_warnings is False
    assert failing_report.exit_code == 1


def test_format_text_matches_golden_cli_output() -> None:
    """format_text renders deterministic section headers, status indicators, details, and summary."""
    report = ConnectivityReport(
        environment_summary="Host: test-host | OS: Ubuntu 24.04 LTS | Python: 3.12.7",
        results=(
            CheckResult(
                name="ORACLE frontend connection",
                category="frontend",
                status="passed",
                details=(CheckDetail(label="user", value="GOE_ADM"),),
            ),
            CheckResult(
                name="BIGQUERY backend catalog",
                category="backend",
                status="warning",
                message="Dataset location mismatch",
            ),
        ),
    )

    brief = report.format_text(include_details=False)
    assert "Host: test-host | OS: Ubuntu 24.04 LTS | Python: 3.12.7" in brief
    assert "=== FRONTEND ===" in brief
    assert "[PASSED]" in brief
    assert "user: GOE_ADM" not in brief
    assert "=== BACKEND ===" in brief
    assert "[WARNING]" in brief
    assert "  Dataset location mismatch" in brief
    assert brief.endswith("Connectivity check succeeded (with warnings)")

    detailed = report.format_text(include_details=True)
    assert "  user: GOE_ADM" in detailed

    failed_report = ConnectivityReport(
        environment_summary="Host: test-host",
        results=(
            CheckResult(
                name="BIGQUERY backend catalog",
                category="backend",
                status="failed",
                message="Dataset missing",
            ),
        ),
    )
    assert failed_report.format_text().endswith("Connectivity check failed")


def test_to_json_uses_centralized_serializer() -> None:
    """to_json and to_json_bytes round-trip losslessly through decode_json."""
    report = ConnectivityReport(
        environment_summary="Host: node1",
        results=(
            CheckResult(
                name="ORACLE frontend connection",
                category="frontend",
                status="passed",
                duration_ms=2.5,
                details=(CheckDetail(label="dsn", value="ora:1521/ORCL"),),
            ),
        ),
        total_duration_ms=2.5,
    )
    json_str = report.to_json()
    json_bytes = report.to_json_bytes()
    assert isinstance(json_str, str)
    assert isinstance(json_bytes, bytes)
    decoded = decode_json(json_bytes, target_type=ConnectivityReport)
    assert decoded == report
