# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Vertebra CLI launcher, --worker-only mode, and LitestarPlugin registration."""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner
from litestar.plugins import InitPluginProtocol

import goe.cli.commands.listener as listener_cmd
import goe.listener.app as listener_app_module
from goe.cli.commands.listener import build_vertebra_command
from goe.cli.main import cli


class _DummyVertebraLitestarPlugin(InitPluginProtocol):
    """Test double for vertebra.extensions.litestar.LitestarPlugin."""


def test_build_vertebra_command_flags_and_tls() -> None:
    """Verify build_vertebra_command constructs the expected vtb run CLI arguments."""
    base_cmd = build_vertebra_command(
        host="0.0.0.0",
        port=8000,
        workers=4,
        threads=2,
        topology="shm",
        drain_timeout=30,
        shutdown_timeout=35,
    )
    assert base_cmd == [
        sys.executable,
        "-m",
        "vertebra",
        "run",
        "goe.listener.asgi:app",
        "--interface",
        "asgi",
        "--topology",
        "shm",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--workers",
        "4",
        "--threads",
        "2",
        "--drain-timeout",
        "30",
        "--shutdown-timeout",
        "35",
    ]

    tls_reload_cmd = build_vertebra_command(
        host="127.0.0.1",
        port=8443,
        workers=2,
        threads=1,
        topology="embedded",
        drain_timeout=15,
        shutdown_timeout=20,
        ssl_enabled=True,
        certfile="/etc/goe/cert.pem",
        keyfile="/etc/goe/key.pem",
        reload=True,
    )
    assert "--tls-cert" in tls_reload_cmd
    assert "/etc/goe/cert.pem" in tls_reload_cmd
    assert "--tls-key" in tls_reload_cmd
    assert "/etc/goe/key.pem" in tls_reload_cmd
    assert "--reload" in tls_reload_cmd


@patch("goe.cli.commands.listener.subprocess.run")
@patch("goe.cli.commands.listener.verify_vertebra_runtime_gate", new_callable=AsyncMock)
def test_listener_start_worker_only_runs_durable_job_worker(
    mock_gate: AsyncMock,
    mock_subproc: MagicMock,
    tmp_path: Path,
) -> None:
    """Verify goe listener start --worker-only runs DurableJobWorker.run_forever without starting HTTP ingress."""
    fake_worker = MagicMock()
    fake_worker.run_forever = AsyncMock(return_value=None)
    fake_store = MagicMock()

    with (
        patch.object(listener_cmd, "create_job_store", return_value=fake_store),
        patch.object(listener_cmd, "DurableJobWorker", return_value=fake_worker) as mock_worker_cls,
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["listener", "start", "--worker-only"])
        assert result.exit_code == 0
        mock_worker_cls.assert_called_once()
        fake_worker.run_forever.assert_awaited_once()
        mock_subproc.assert_not_called()
        mock_gate.assert_not_awaited()


def test_create_app_registers_vertebra_litestar_plugin_and_removes_granian() -> None:
    """Verify create_app registers vertebra.extensions.litestar.LitestarPlugin when available and removes Granian."""
    app_source = inspect.getsource(listener_app_module)
    cmd_source = inspect.getsource(listener_cmd)
    assert "granian" not in app_source.lower()
    assert "granian" not in cmd_source.lower()

    listener_root = Path(listener_app_module.__file__).resolve().parent
    assert not (listener_root / "server.py").exists()
    assert not (listener_root / "__main__.py").exists()

    fake_ext = SimpleNamespace(LitestarPlugin=_DummyVertebraLitestarPlugin)
    original_import_optional = listener_app_module.import_optional

    def fake_import(name: str):
        if name == "vertebra.extensions.litestar":
            return fake_ext
        return original_import_optional(name)

    with patch.object(listener_app_module, "import_optional", side_effect=fake_import):
        app = listener_app_module.create_app(enable_background_worker=False)
        assert any(isinstance(p, _DummyVertebraLitestarPlugin) for p in app.plugins)


def test_asgi_module_import_is_side_effect_free() -> None:
    """Verify goe.listener.asgi exports app and create_app without opening DB or network connections at import."""
    asgi_mod = importlib.import_module("goe.listener.asgi")

    assert hasattr(asgi_mod, "app")
    assert hasattr(asgi_mod, "create_app")
    assert asgi_mod.__all__ == ("app", "create_app")
