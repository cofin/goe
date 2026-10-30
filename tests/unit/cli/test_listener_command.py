# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the goe listener CLI command group."""

from __future__ import annotations

import logging
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import msgspec
from click.testing import CliRunner

from goe.cli.main import cli
from goe.listener.config import settings
from goe.serializers import decode_json


def test_listener_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "status" in result.output
    assert "mcp" in result.output


def test_listener_start_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--workers" in result.output


@patch("goe.cli.commands.listener.subprocess.run")
@patch("goe.cli.commands.listener.verify_vertebra_runtime_gate", new_callable=AsyncMock)
def test_listener_start_dispatch(mock_gate: AsyncMock, mock_run) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "start", "--port", "9000"])
    assert result.exit_code == 0
    assert mock_gate.called
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert "--port" in cmd
    assert cmd[cmd.index("--port") + 1] == "9000"


@patch("goe.cli.commands.listener.httpx2.get")
def test_listener_status_healthy(mock_get) -> None:
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = '{"status":true}'
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 0
    assert "healthy" in result.output.lower()
    called_url = mock_get.call_args_list[0].args[0]
    assert called_url == f"{settings.base_url}/api/system/status/"


@patch("goe.cli.commands.listener.httpx2.get")
def test_listener_status_with_shared_token_forwards_console_key(mock_get) -> None:
    status_resp = MagicMock(status_code=200, text='{"status":true}')
    config_resp = MagicMock(status_code=200, text='{"host":"127.0.0.1"}')
    mock_get.side_effect = [status_resp, config_resp]
    secured = msgspec.structs.replace(settings, host="0.0.0.0", port=8443, ssl_enabled=True, shared_token="tok-123")
    runner = CliRunner()
    with patch("goe.cli.commands.listener.settings", secured):
        result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 0
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[0].args[0] == "https://127.0.0.1:8443/api/system/status/"
    assert mock_get.call_args_list[1].args[0] == "https://127.0.0.1:8443/api/system/config/"
    assert mock_get.call_args_list[1].kwargs["headers"] == {"x-goe-console-key": "tok-123"}


@patch("goe.cli.commands.listener.httpx2.get")
def test_listener_status_non_200_exits_nonzero(mock_get) -> None:
    mock_get.return_value.status_code = 503
    mock_get.return_value.text = "Service Unavailable"
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 1
    assert "503" in result.output


@patch("goe.cli.commands.listener.httpx2.get", side_effect=OSError("connection refused"))
def test_listener_status_unreachable(mock_get) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "status"])
    assert result.exit_code == 1
    assert "not reachable" in result.output.lower()


@patch("goe.cli.commands.listener.run_stdio", return_value=0)
@patch("goe.cli.commands.listener.create_app")
def test_listener_mcp_stdio_forwards_console_key_and_redirects_stdout_handlers(
    mock_create_app,
    mock_run_stdio,
) -> None:
    fake_app = MagicMock()
    mock_create_app.return_value = fake_app
    stdout_handler = logging.StreamHandler(sys.stdout)
    original_stream = stdout_handler.stream
    root_logger = logging.getLogger()
    root_logger.addHandler(stdout_handler)
    secured = msgspec.structs.replace(settings, shared_token="stdio-secret")
    try:
        runner = CliRunner()
        with patch("goe.cli.commands.listener.settings", secured):
            result = runner.invoke(
                cli,
                ["listener", "mcp", "stdio", "--client-id", "claude-code", "--owner-id", "dba-1"],
            )
        assert result.exit_code == 0
        assert stdout_handler.stream is not original_stream
        mock_create_app.assert_called_once_with(enable_background_worker=False)
        kwargs = mock_run_stdio.call_args.kwargs
        assert kwargs["header_name"] == "x-goe-console-key"
        assert kwargs["token_prefix"] == ""
        assert kwargs["headers"] == {"x-goe-console-key": "stdio-secret"}
        stdio_ctx = kwargs["stdio_context"]
        assert stdio_ctx.client_id == "claude-code"
        assert stdio_ctx.owner_id == "dba-1"
    finally:
        root_logger.removeHandler(stdout_handler)


@patch("goe.cli.commands.listener.run_stdio_streamable_http_bridge", new_callable=AsyncMock, return_value=0)
def test_listener_mcp_bridge_defaults_and_token_forwarding(mock_bridge: AsyncMock) -> None:
    secured = msgspec.structs.replace(settings, host="0.0.0.0", port=8088, ssl_enabled=False, shared_token="bridge-tok")
    runner = CliRunner()
    with (
        patch("goe.cli.commands.listener.settings", secured),
        patch.dict("os.environ", {"OFFLOAD_LISTENER_SHARED_TOKEN": "env-bridge-tok"}, clear=False),
    ):
        result = runner.invoke(cli, ["listener", "mcp", "bridge"])
        assert result.exit_code == 0
        assert mock_bridge.called
        call_args = mock_bridge.call_args
        assert call_args.args[0] == "http://127.0.0.1:8088/mcp"
        assert call_args.kwargs["header_name"] == "x-goe-console-key"
        assert call_args.kwargs["token_prefix"] == ""
        token_provider = call_args.kwargs["token_provider"]
        assert callable(token_provider)
        assert token_provider() == "env-bridge-tok"
    assert token_provider() == "bridge-tok"


def test_listener_mcp_inspect_json_and_table() -> None:
    runner = CliRunner()
    json_result = runner.invoke(cli, ["listener", "mcp", "inspect", "--json"])
    assert json_result.exit_code == 0
    payload = decode_json(json_result.stdout)
    assert "check_connectivity" in payload["tools"]
    assert "preview_offload_plan" in payload["tools"]
    assert "execute_offload" in payload["tools"]
    assert "goe://system/connectivity" in payload["resources"]
    assert "goe://schemas/{schema_name}/{table_name}/status" in payload["resource_templates"]
    assert "plan_table_offload" in payload["prompts"]
    assert "skill://goe-offload-operations/SKILL.md" in payload["skills"]

    table_result = runner.invoke(cli, ["listener", "mcp", "inspect"])
    assert table_result.exit_code == 0
    assert "check_connectivity" in table_result.output
    assert "plan_table_offload" in table_result.output


def test_cli_help_lazy_imports_do_not_load_litestar() -> None:
    """Verify goe --help and goe listener --help do not eagerly import litestar or goe.listener.app."""
    script = (
        "import sys; "
        "from click.testing import CliRunner; "
        "from goe.cli.main import cli; "
        "runner = CliRunner(); "
        "assert runner.invoke(cli, ['--help']).exit_code == 0; "
        "assert runner.invoke(cli, ['listener', '--help']).exit_code == 0; "
        "assert runner.invoke(cli, ['listener', 'mcp', '--help']).exit_code == 0; "
        "loaded = [m for m in ('litestar', 'litestar_mcp', 'goe.listener.app') if m in sys.modules]; "
        "assert not loaded, f'Eagerly imported: {loaded}'"
    )
    proc = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout


@patch("goe.cli.commands.listener.subprocess.run")
@patch("goe.cli.commands.listener.verify_vertebra_runtime_gate", new_callable=AsyncMock)
def test_listener_bare_invocation_starts_server(mock_gate: AsyncMock, mock_run) -> None:
    """Verify bare goe listener starts the server by default."""
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--port", "9090", "-v"])
    assert result.exit_code == 0
    assert mock_gate.called
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--port") + 1] == "9090"


@patch("goe.cli.commands.listener.subprocess.run")
@patch("goe.cli.commands.listener.verify_vertebra_runtime_gate", new_callable=AsyncMock)
def test_listener_group_options_forwarded_to_start(mock_gate: AsyncMock, mock_run) -> None:
    """Verify server options placed before start subcommand are forwarded to start."""
    runner = CliRunner()
    result = runner.invoke(cli, ["listener", "--port", "9091", "start"])
    assert result.exit_code == 0
    assert mock_gate.called
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--port") + 1] == "9091"
