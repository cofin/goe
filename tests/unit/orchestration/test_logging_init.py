# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe.orchestration.logging_init initialization and output helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from goe.offload.offload_messages import NORMAL, VERBOSE, VVERBOSE
from goe.orchestration import logging_init


def test_logging_init_creates_logfile_and_writes_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify init, init_log, log, and log_close create and populate the offload log file."""
    monkeypatch.setenv("OFFLOAD_LOGDIR", str(tmp_path))
    opts = SimpleNamespace(
        quiet=False,
        verbose=True,
        vverbose=False,
        suppress_stdout=False,
        ansi=False,
        dev_log_level="OFF",
        log_path=str(tmp_path),
    )
    logging_init.init(opts)
    try:
        logging_init.init_log("SH.SALES")
        log_name = logging_init.get_log_fh_name()
        assert log_name is not None
        assert Path(log_name).parent == tmp_path
        logging_init.log("normal-msg", detail=NORMAL)
        logging_init.log("verbose-msg", detail=VERBOSE)
        logging_init.log("vverbose-msg", detail=VVERBOSE)
    finally:
        logging_init.log_close()

    out = capsys.readouterr().out
    assert "normal-msg\n" in out
    assert "verbose-msg\n" in out
    assert "vverbose-msg" not in out

    assert log_name is not None
    file_contents = Path(log_name).read_text(encoding="utf-8")
    assert "normal-msg\n" in file_contents
    assert "verbose-msg\n" in file_contents
    assert "vverbose-msg\n" in file_contents


def test_logging_init_suppress_stdout_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify suppress_stdout prevents console output while still writing to the log file."""
    monkeypatch.setenv("OFFLOAD_LOGDIR", str(tmp_path))
    opts = SimpleNamespace(
        quiet=False,
        verbose=False,
        vverbose=False,
        suppress_stdout=True,
        ansi=False,
        dev_log_level="OFF",
        log_path=str(tmp_path),
    )
    logging_init.init(opts)
    try:
        logging_init.init_log("SH.SUPPRESSED")
        log_name = logging_init.get_log_fh_name()
        logging_init.log("file-only-line", detail=NORMAL)
    finally:
        logging_init.log_close()

    assert capsys.readouterr().out == ""
    assert log_name is not None
    assert "file-only-line\n" in Path(log_name).read_text(encoding="utf-8")


def test_comp_ver_check() -> None:
    """Verify semantic component version tuple and frontend_api comparison."""
    assert logging_init.comp_ver_check("3.2.0", (3, 1, 0)) is True
    assert logging_init.comp_ver_check("3.0.9", (3, 1, 0)) is False
    fake_api = SimpleNamespace(goe_db_component_version=lambda: logging_init.version())
    match, v_goe, v_ora = logging_init.comp_ver_check(fake_api)
    assert match is True
    assert v_goe == v_ora
