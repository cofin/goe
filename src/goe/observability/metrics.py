# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Canonical OpenTelemetry metric instruments for GOE orchestration, transport, and BigQuery."""

from opentelemetry.metrics import Counter, Histogram, Meter

__all__ = ("METRIC_NAMES", "GOEMetrics")

METRIC_NAMES: tuple[str, ...] = (
    "goe.commands.total",
    "goe.command.duration",
    "goe.steps.duration",
    "goe.offload.rows_transported",
    "goe.offload.bytes_staged",
    "goe.offload.bytes_loaded",
    "goe.bigquery.bytes_billed",
    "goe.bigquery.slot_ms",
)


class GOEMetrics:
    """Typed recorder for the eight canonical GOE instruments created from one Meter."""

    def __init__(self, meter: Meter) -> None:
        """Create all instruments from ``meter``; a no-op meter yields no-op instruments."""
        self._commands_total: Counter = meter.create_counter(
            "goe.commands.total", unit="1", description="GOE orchestration commands executed"
        )
        self._command_duration: Histogram = meter.create_histogram(
            "goe.command.duration", unit="s", description="End-to-end GOE command duration"
        )
        self._steps_duration: Histogram = meter.create_histogram(
            "goe.steps.duration", unit="s", description="GOE orchestration step duration"
        )
        self._rows_transported: Counter = meter.create_counter(
            "goe.offload.rows_transported", unit="1", description="Rows extracted and staged from the source RDBMS"
        )
        self._bytes_staged: Counter = meter.create_counter(
            "goe.offload.bytes_staged", unit="By", description="Bytes written to staging storage by transport"
        )
        self._bytes_loaded: Counter = meter.create_counter(
            "goe.offload.bytes_loaded", unit="By", description="Bytes added to backend target tables"
        )
        self._bigquery_bytes_billed: Counter = meter.create_counter(
            "goe.bigquery.bytes_billed", unit="By", description="Bytes billed by BigQuery jobs"
        )
        self._bigquery_slot_ms: Counter = meter.create_counter(
            "goe.bigquery.slot_ms", unit="ms", description="Slot milliseconds consumed by BigQuery jobs"
        )

    def record_command(self, command_type: str, status: str, backend: str, dry_run: bool, duration_s: float) -> None:
        """Increment ``goe.commands.total`` and record ``goe.command.duration``."""
        attributes: dict[str, str | bool] = {
            "command_type": command_type,
            "status": status,
            "backend": backend or "unknown",
            "dry_run": dry_run,
        }
        self._commands_total.add(1, attributes=attributes)
        self._command_duration.record(max(0.0, duration_s), attributes=attributes)

    def record_step(self, step_id: str, command_type: str, status: str, mandatory: bool, duration_s: float) -> None:
        """Record ``goe.steps.duration`` for one orchestration step."""
        attributes: dict[str, str | bool] = {
            "step_id": step_id,
            "command_type": command_type or "unknown",
            "status": status,
            "mandatory": mandatory,
        }
        self._steps_duration.record(max(0.0, duration_s), attributes=attributes)

    def record_transport(
        self,
        transport_method: str,
        backend: str,
        source_owner: str,
        rows: int | None,
        bytes_staged: int | None,
        storage_format: str,
        scheme: str,
    ) -> None:
        """Add positive row and staged-byte counts for one transport invocation."""
        if rows is not None and rows > 0:
            self._rows_transported.add(
                rows,
                attributes={
                    "transport_method": transport_method,
                    "backend": backend or "unknown",
                    "source_owner": source_owner or "unknown",
                },
            )
        if bytes_staged is not None and bytes_staged > 0:
            self._bytes_staged.add(
                bytes_staged,
                attributes={
                    "transport_method": transport_method,
                    "storage_format": storage_format or "unknown",
                    "scheme": scheme or "unknown",
                },
            )

    def record_bytes_loaded(self, backend: str, bytes_loaded: int | None) -> None:
        """Add positive backend byte growth for one loaded chunk."""
        if bytes_loaded is not None and bytes_loaded > 0:
            self._bytes_loaded.add(bytes_loaded, attributes={"backend": backend or "unknown"})

    def record_bigquery_job(self, operation: str, project: str, bytes_billed: int | None, slot_ms: int | None) -> None:
        """Add positive BigQuery bytes billed and slot milliseconds for one job."""
        attributes = {"operation": operation, "project": project or "unknown"}
        if bytes_billed is not None and bytes_billed > 0:
            self._bigquery_bytes_billed.add(bytes_billed, attributes=attributes)
        if slot_ms is not None and slot_ms > 0:
            self._bigquery_slot_ms.add(slot_ms, attributes=attributes)
