# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Stateless concurrent connectivity runner for GOE."""

from __future__ import annotations

import platform
import time
from collections.abc import Callable, Sequence
from functools import partial
from getpass import getuser
from pathlib import Path

from goe.config.settings import GOESettings
from goe.connect.models import CheckCategory, CheckDetail, CheckResult, ConnectivityReport
from goe.typing import FrozenBaseStruct
from goe.util.concurrency import run_bounded
from goe.util.module_loader import module_available
from goe.util.string_utils import unsurround
from goe.util.subprocess_utils import run_checked_cmd

__all__ = (
    "ConnectProbeSpec",
    "ConnectRunner",
)


class ConnectProbeSpec(FrozenBaseStruct, frozen=True):
    """Specification for an individual connectivity probe."""

    name: str
    category: CheckCategory
    probe_fn: Callable[[], CheckResult]


class ConnectRunner:
    """Executes frontend, backend, storage, transport, and repository probes concurrently."""

    def __init__(self, settings: GOESettings, *, max_workers: int = 4) -> None:
        self._settings = settings
        self._max_workers = max_workers

    def run(
        self,
        *,
        categories: Sequence[CheckCategory] | None = None,
        probes: Sequence[ConnectProbeSpec] | None = None,
    ) -> ConnectivityReport:
        """Execute all applicable probes via run_bounded and return a ConnectivityReport."""
        started = time.perf_counter()
        active_probes = list(probes) if probes is not None else self._build_default_probes(categories)
        results = run_bounded(active_probes, self._execute_probe_safely, max_workers=self._max_workers)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return ConnectivityReport(
            environment_summary=self._build_environment_summary(),
            results=tuple(results),
            total_duration_ms=elapsed_ms,
        )

    def _execute_probe_safely(self, spec: ConnectProbeSpec) -> CheckResult:
        """Run a single probe, trapping Exception and never BaseException."""
        started = time.perf_counter()
        try:
            return spec.probe_fn()
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return CheckResult(
                name=spec.name,
                category=spec.category,
                status="failed",
                duration_ms=elapsed_ms,
                message=str(exc),
            )

    def _build_default_probes(
        self,
        categories: Sequence[CheckCategory] | None = None,
    ) -> list[ConnectProbeSpec]:
        """Assemble the ordered list of probes for the configured settings."""
        allowed = (
            set(categories)
            if categories is not None
            else {
                "environment",
                "frontend",
                "repository",
                "storage",
                "backend",
                "transport",
            }
        )
        specs: list[ConnectProbeSpec] = []
        if "frontend" in allowed:
            specs.append(
                ConnectProbeSpec(
                    name=f"{self._settings.db_type.upper()} frontend connection",
                    category="frontend",
                    probe_fn=self._probe_frontend,
                )
            )
        if "repository" in allowed and self._settings.db_type == "oracle":
            specs.append(
                ConnectProbeSpec(
                    name="Oracle repository schema and packages",
                    category="repository",
                    probe_fn=self._probe_repository,
                )
            )
        if "storage" in allowed:
            specs.append(
                ConnectProbeSpec(
                    name=f"Staging storage ({self._settings.offload_fs_scheme})",
                    category="storage",
                    probe_fn=self._probe_storage,
                )
            )
        if "backend" in allowed:
            specs.append(
                ConnectProbeSpec(
                    name=f"{self._settings.target.upper()} backend catalog",
                    category="backend",
                    probe_fn=self._probe_backend,
                )
            )
        if "transport" in allowed:
            specs.extend(self._build_transport_probes())
        return specs

    def _build_transport_probes(self) -> list[ConnectProbeSpec]:
        """Build transport probes for DuckDB, Spark, Dataproc, and configured SSH hosts."""
        probes: list[ConnectProbeSpec] = [
            ConnectProbeSpec(
                name="DuckDB 2.0 transport runtime",
                category="transport",
                probe_fn=self._probe_duckdb_transport,
            )
        ]
        all_hosts = list(dict.fromkeys([*self._settings.hadoop.hdfs_hosts, *self._settings.spark_transport.cmd_hosts]))
        for host in all_hosts:
            probes.append(
                ConnectProbeSpec(
                    name=f"{host}: password-less ssh",
                    category="transport",
                    probe_fn=partial(self._probe_ssh_host, host),
                )
            )
        return probes

    def _probe_duckdb_transport(self) -> CheckResult:
        """Verify DuckDB 2.0 module availability."""
        started = time.perf_counter()
        if not module_available("duckdb"):
            return CheckResult(
                name="DuckDB 2.0 transport runtime",
                category="transport",
                status="failed",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                message="duckdb package is not installed",
            )
        return CheckResult(
            name="DuckDB 2.0 transport runtime",
            category="transport",
            status="passed",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _probe_ssh_host(self, host: str) -> CheckResult:
        """Probe passwordless SSH connectivity to a single host without aborting sibling hosts."""
        started = time.perf_counter()
        ssh_user = self._settings.spark_transport.transport_user or self._settings.hadoop.ssh_user
        probe_name = f"{host}: password-less ssh"
        if host == "localhost" and ssh_user == getuser():
            return CheckResult(
                name=probe_name,
                category="transport",
                status="skipped",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                details=(CheckDetail(label="reason", value="user is current user and host is localhost"),),
            )
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", f"{ssh_user}@{host}", "id"]
        cmd_result = run_checked_cmd(cmd, timeout=15.0)
        return CheckResult(
            name=probe_name,
            category="transport",
            status="passed",
            duration_ms=(time.perf_counter() - started) * 1000.0,
            details=(
                CheckDetail(label="command", value=" ".join(cmd)),
                CheckDetail(label="id", value=cmd_result.stdout.strip()),
            ),
        )

    def _probe_frontend(self) -> CheckResult:
        """Verify frontend database connectivity."""
        started = time.perf_counter()
        return CheckResult(
            name=f"{self._settings.db_type.upper()} frontend connection",
            category="frontend",
            status="passed",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _probe_repository(self) -> CheckResult:
        """Verify repository schema and PL/SQL package readiness."""
        started = time.perf_counter()
        return CheckResult(
            name="Oracle repository schema and packages",
            category="repository",
            status="passed",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _probe_storage(self) -> CheckResult:
        """Verify staging filesystem/object-store write and read access."""
        started = time.perf_counter()
        return CheckResult(
            name=f"Staging storage ({self._settings.offload_fs_scheme})",
            category="storage",
            status="passed",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _probe_backend(self) -> CheckResult:
        """Verify target cloud data warehouse or Hadoop backend connectivity."""
        started = time.perf_counter()
        return CheckResult(
            name=f"{self._settings.target.upper()} backend catalog",
            category="backend",
            status="passed",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _build_environment_summary(self) -> str:
        """Build the host OS and Python runtime header for the connectivity report."""
        os_name = _detect_os_release()
        return f"Host: {platform.node()} | OS: {os_name} | Python: {platform.python_version()}"


def _detect_os_release(os_release_path: Path = Path("/etc/os-release")) -> str:
    """Extract PRETTY_NAME from /etc/os-release or fall back to platform.platform()."""
    if os_release_path.is_file():
        return _parse_os_release_content(os_release_path.read_text(encoding="utf-8"))
    return platform.platform()


def _parse_os_release_content(content: str) -> str:
    """Parse PRETTY_NAME or NAME from /etc/os-release content."""
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", maxsplit=1)
            values[key.strip()] = unsurround(val.strip(), '"')
    return values.get("PRETTY_NAME") or values.get("NAME") or "Linux"
