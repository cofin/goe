# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the root goe CLI group and environment initialization."""

import json
import subprocess
import sys
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

import goe.cli.commands.connect as connect_cmd_module
import goe.cli.common as common_module
from goe.cli.main import cli
from goe.util.goe_version import goe_version


def test_cli_help() -> None:
    """Verify goe --help renders all subcommands in borderless modern format without raw Rich tags."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    plain_output = click.unstyle(result.output)
    assert "Gluent Offload Engine (GOE)" in plain_output
    assert "Core Orchestration Commands" in plain_output
    assert "Service & Maintenance Commands" in plain_output
    assert "[bold" not in plain_output
    assert "[dim]" not in plain_output
    assert "╭" not in plain_output
    assert "╰" not in plain_output
    assert "│" not in plain_output
    assert "offload" in plain_output
    assert "connect" in plain_output
    assert "validate" in plain_output
    assert "sync" in plain_output
    assert "listener" in plain_output
    assert "logmgr" in plain_output


def test_cli_version() -> None:
    """Verify goe --version prints the package version."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "goe version" in result.output
    assert goe_version() in result.output


@patch("goe.cli.main.load_env")
def test_cli_bare_invocation_loads_env(mock_load_env) -> None:
    """Verify bare goe invocation calls load_env() and displays help."""
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "Usage: goe" in result.output
    assert mock_load_env.called


def test_cli_quiet_short_flag() -> None:
    """Verify goe -q --help succeeds and exposes the short quiet flag."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-q", "--help"])
    assert result.exit_code == 0
    assert "-q" in result.output
    assert "--quiet" in result.output


def test_cli_help_does_not_import_heavy_backends() -> None:
    """Verify importing goe.cli.main and rendering help does not eagerly load heavy backend modules."""
    probe = (
        "import json, sys; "
        "from click.testing import CliRunner; "
        "from goe.cli.main import cli; "
        "CliRunner().invoke(cli, ['--help']); "
        "CliRunner().invoke(cli, ['offload', '--help']); "
        "forbidden = ['goe.goe', 'goe.connect.connect', 'granian', 'httpx', 'oracledb', 'litestar', 'gcsfs']; "
        "loaded = [m for m in forbidden if m in sys.modules]; "
        "print(json.dumps(loaded))"
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    loaded = json.loads(proc.stdout.strip())
    assert loaded == [], f"Heavy modules eagerly imported during CLI help rendering: {loaded}"


def test_cli_lazy_attribute_resolution() -> None:
    """Verify PEP 562 lazy attribute resolution caches resolved symbols and raises AttributeError for unknown names."""
    assert callable(connect_cmd_module.check_config_path)
    assert hasattr(common_module.orchestration_defaults, "log_path_default")
    with pytest.raises(AttributeError):
        _ = connect_cmd_module.nonexistent_cli_symbol


def test_offload_messages_import_does_not_load_litestar_or_gcsfs() -> None:
    """Verify importing goe.offload.offload_messages does not eagerly import litestar or gcsfs."""
    probe = (
        "import json, sys; "
        "import goe.offload.offload_messages; "
        "forbidden = ['litestar', 'gcsfs', 'gcsfs.core']; "
        "loaded = [m for m in forbidden if m in sys.modules]; "
        "print(json.dumps(loaded))"
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    loaded = json.loads(proc.stdout.strip())
    assert loaded == [], f"Transitive heavy modules eagerly imported by offload_messages: {loaded}"
