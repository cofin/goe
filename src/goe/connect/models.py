# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Immutable connectivity probe result and report models."""

from __future__ import annotations

from typing import Literal

from goe.serializers import encode_json, encode_json_bytes
from goe.typing import FrozenBaseStruct

__all__ = (
    "CheckCategory",
    "CheckDetail",
    "CheckResult",
    "CheckStatus",
    "ConnectivityReport",
)

type CheckStatus = Literal["passed", "warning", "failed", "skipped"]
type CheckCategory = Literal["environment", "frontend", "backend", "storage", "transport", "repository"]


class CheckDetail(FrozenBaseStruct, frozen=True):
    """Diagnostic detail entry attached to a connectivity check."""

    label: str
    value: str


class CheckResult(FrozenBaseStruct, frozen=True):
    """Outcome of a single connectivity probe."""

    name: str
    category: CheckCategory
    status: CheckStatus
    duration_ms: float = 0.0
    message: str | None = None
    details: tuple[CheckDetail, ...] = ()


class ConnectivityReport(FrozenBaseStruct, frozen=True):
    """Aggregated report across all executed connectivity probes."""

    environment_summary: str
    results: tuple[CheckResult, ...] = ()
    total_duration_ms: float = 0.0

    @property
    def failure_count(self) -> int:
        """Return the number of failed probes."""
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def warning_count(self) -> int:
        """Return the number of probes that completed with warnings."""
        return sum(1 for r in self.results if r.status == "warning")

    @property
    def passed(self) -> bool:
        """Return True when zero probes failed."""
        return self.failure_count == 0

    @property
    def has_warnings(self) -> bool:
        """Return True when at least one probe emitted a warning."""
        return self.warning_count > 0

    @property
    def exit_code(self) -> int:
        """Return CLI exit code 0 when all probes pass or warn, 1 on any failure."""
        return 0 if self.passed else 1

    def format_text(self, *, include_details: bool = False) -> str:
        """Render the connectivity report in the canonical CLI text format."""
        lines: list[str] = [self.environment_summary, ""]
        current_category: CheckCategory | None = None
        for result in self.results:
            if result.category != current_category:
                current_category = result.category
                lines.append(f"=== {current_category.upper()} ===")
            status_tag = result.status.upper()
            line = f"{result.name:<60} [{status_tag}]"
            lines.append(line)
            if include_details:
                for item in result.details:
                    lines.append(f"  {item.label}: {item.value}")
            if result.message:
                lines.append(f"  {result.message}")
        summary = "Connectivity check succeeded" if self.passed else "Connectivity check failed"
        if self.passed and self.has_warnings:
            summary = "Connectivity check succeeded (with warnings)"
        lines.extend(["", summary])
        return "\n".join(lines)

    def to_json(self) -> str:
        """Serialize the report to a UTF-8 JSON string via goe.serializers."""
        return encode_json(self)

    def to_json_bytes(self) -> bytes:
        """Serialize the report to UTF-8 JSON bytes via goe.serializers."""
        return encode_json_bytes(self)
