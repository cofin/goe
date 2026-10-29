# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for stateless concurrent ConnectRunner."""

from __future__ import annotations

from unittest import mock

import pytest

from goe.config.settings import GOESettings
from goe.connect.models import CheckResult
from goe.connect.runner import (
    ConnectProbeSpec,
    ConnectRunner,
    _parse_os_release_content,
)
from goe.exceptions import TransportError
from goe.util.subprocess_utils import CommandResult


def test_connect_runner_executes_all_probes_via_run_bounded() -> None:
    """ConnectRunner(settings).run() executes all default probes in deterministic order."""
    settings = _sample_settings()
    runner = ConnectRunner(settings, max_workers=4)
    report = runner.run()

    categories = [r.category for r in report.results]
    assert categories == ["frontend", "repository", "storage", "backend", "transport"]
    assert report.passed is True
    assert report.exit_code == 0


def test_connect_runner_traps_exception_but_propagates_base_exception() -> None:
    """ConnectRunner captures Exception as status='failed' and never swallows BaseException."""
    settings = _sample_settings()

    def failing_probe() -> CheckResult:
        raise TransportError("connection timed out")

    def passing_probe() -> CheckResult:
        return CheckResult(name="Passing probe", category="backend", status="passed", duration_ms=1.0)

    probes = (
        ConnectProbeSpec(name="Failing probe", category="transport", probe_fn=failing_probe),
        ConnectProbeSpec(name="Passing probe", category="backend", probe_fn=passing_probe),
    )
    runner = ConnectRunner(settings, max_workers=2)
    report = runner.run(probes=probes)

    assert len(report.results) == 2
    assert report.results[0].status == "failed"
    assert "connection timed out" in (report.results[0].message or "")
    assert report.results[1].status == "passed"
    assert report.passed is False

    def interrupt_probe() -> CheckResult:
        raise KeyboardInterrupt("user cancelled")

    interrupt_runner = ConnectRunner(settings, max_workers=1)
    with pytest.raises(KeyboardInterrupt, match="user cancelled"):
        interrupt_runner.run(
            probes=(ConnectProbeSpec(name="Interrupt probe", category="frontend", probe_fn=interrupt_probe),)
        )


def test_ssh_probe_checks_all_hosts_when_first_host_fails() -> None:
    """When host1 fails SSH, host2 is still probed and both CheckResult entries appear in report.results."""
    settings = _sample_settings(
        OFFLOAD_TRANSPORT_CMD_HOST="spark-node-1,spark-node-2",
        OFFLOAD_TRANSPORT_USER="goe_spark",
    )

    def fake_run_checked_cmd(cmd: list[str], *, timeout: float | None = None) -> CommandResult:
        _ = timeout
        target = cmd[5]
        if "spark-node-1" in target:
            raise RuntimeError("ssh: connect to host spark-node-1 port 22: Connection refused")
        return CommandResult(
            args=tuple(cmd),
            returncode=0,
            stdout="uid=1001(goe_spark) gid=1001(goe_spark)\n",
            stderr="",
            duration_seconds=0.01,
        )

    runner = ConnectRunner(settings, max_workers=2)
    with mock.patch("goe.connect.runner.run_checked_cmd", side_effect=fake_run_checked_cmd):
        report = runner.run(categories=("transport",))

    ssh_results = [r for r in report.results if "password-less ssh" in r.name]
    assert len(ssh_results) == 2
    assert ssh_results[0].name == "spark-node-1: password-less ssh"
    assert ssh_results[0].status == "failed"
    assert ssh_results[1].name == "spark-node-2: password-less ssh"
    assert ssh_results[1].status == "passed"


def test_os_release_parses_pretty_name_key() -> None:
    """_parse_os_release_content extracts PRETTY_NAME rather than returning lines[0]."""
    sample = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\nID=ubuntu\n'
    assert _parse_os_release_content(sample) == "Ubuntu 24.04.1 LTS"


def test_duckdb_transport_probe_checks_duckdb_and_extensions() -> None:
    """The DuckDB transport probe checks duckdb availability and reports category='transport'."""
    settings = _sample_settings()
    runner = ConnectRunner(settings, max_workers=1)

    with mock.patch("goe.connect.runner.module_available", return_value=True):
        report_ok = runner.run(categories=("transport",))
    assert report_ok.results[0].category == "transport"
    assert report_ok.results[0].status == "passed"

    with mock.patch("goe.connect.runner.module_available", return_value=False):
        report_missing = runner.run(categories=("transport",))
    assert report_missing.results[0].category == "transport"
    assert report_missing.results[0].status == "failed"
    assert "duckdb package is not installed" in (report_missing.results[0].message or "")


def _sample_settings(**extra_env: str) -> GOESettings:
    env = {
        "ORA_CONN": "ora-host:1521/ORCL",
        "ORA_ADM_USER": "GOE_ADM",
        "ORA_APP_USER": "GOE_APP",
        "QUERY_ENGINE": "BIGQUERY",
        "GOOGLE_CLOUD_PROJECT": "my-gcp-project",
        "OFFLOAD_FS_SCHEME": "gs",
        "OFFLOAD_FS_CONTAINER": "my-staging-bucket",
    }
    env.update(extra_env)
    return GOESettings.from_env(environ=env)
