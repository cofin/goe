# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Characterization tests for Offload Status Report demo-mode output."""

import hashlib
import pathlib
import re
import types

import jinja2
import pytest

from goe.offload.backend_api import (
    REPORT_ATTR_BACKEND_CLASS,
    REPORT_ATTR_BACKEND_DISPLAY_NAME,
    REPORT_ATTR_BACKEND_HOST_INFO,
    REPORT_ATTR_BACKEND_HOST_INFO_TYPE,
    REPORT_ATTR_BACKEND_TYPE,
)
from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_status_report import OffloadStatusReport
from goe.orchestration import orchestration_constants

LEVELS = ("summary", "detail")
FORMATS = ("csv", "text", "json", "raw")
GOLDEN_SHA256: dict[str, str] = {
    "detail/csv": "ba2dc85f16bd7e2491cb077d09129a240c2d9436106af66b80f82b85805009a2",
    "detail/json": "ea021abc492920f432d65385f93399de5afedbc792fc89c958da97aad0bc220f",
    "detail/raw": "df523c83bc2725a3bd7b99eb9dc6970cb57fd8c4282ffe7702443584af8b4d4a",
    "detail/text": "2edbba0dcbb5b0adee8af8a77e65e5dad14be77943babbcaeb972836e9a830d2",
    "summary/csv": "ebfb96b372e866869d17021175bafa85d2c27e48045537d1755b6e45584e8f4a",
    "summary/json": "b68ca38436f54cefd1f8e26a4af583cd005c30375f543f599a0b7624ba9e171f",
    "summary/raw": "628187f35ecbf1b05217d68e60025e05b8e0f917877186a3efd0fdad85573866",
    "summary/text": "ae72ed0620e3d9ec5c923e456f6a2b45d8570c31d74964c4fd021c86cfbe00c5",
}


def render_all(base_dir: pathlib.Path) -> dict[str, str]:
    """Render every level and format in demo mode and return normalised SHA-256 digests."""
    digests: dict[str, str] = {}
    for level in LEVELS:
        report = _demo_report()
        data = report.get_offload_status_report_data(None, None, level, True)
        for fmt in FORMATS:
            out_dir = base_dir / f"{level}_{fmt}"
            out_dir.mkdir()
            assert report.gen_offload_status_report(data, fmt, "golden", str(out_dir), ",", '"') == 0
            (out_file,) = out_dir.iterdir()
            normalised = _normalise(out_file.read_text(), out_dir)
            digests[f"{level}/{fmt}"] = hashlib.sha256(normalised.encode()).hexdigest()
    return digests


def test_demo_report_outputs_are_unchanged(tmp_path: pathlib.Path) -> None:
    """CSV, TEXT, JSON and RAW demo output stays byte-identical after normalisation."""
    assert render_all(tmp_path) == GOLDEN_SHA256


def test_html_output_fails_on_missing_template(tmp_path: pathlib.Path) -> None:
    """HTML output keeps its template lookup and still fails because the template is absent (D-2.2-A)."""
    report = _demo_report()
    data = report.get_offload_status_report_data(None, None, "summary", True)
    with pytest.raises(jinja2.TemplateNotFound):
        report.gen_offload_status_report(data, "html", "golden", str(tmp_path), ",", '"')


def _demo_report() -> OffloadStatusReport:
    """Build a report without __init__, which needs Oracle and fails at baseline (D-2.2-B)."""
    report = OffloadStatusReport.__new__(OffloadStatusReport)
    report._messages = OffloadMessages(command_type=orchestration_constants.COMMAND_OSR)
    report._execute = True
    report._backend_info = {
        REPORT_ATTR_BACKEND_CLASS: "Cloud Warehouse",
        REPORT_ATTR_BACKEND_TYPE: "bigquery",
        REPORT_ATTR_BACKEND_DISPLAY_NAME: "BigQuery",
        REPORT_ATTR_BACKEND_HOST_INFO_TYPE: "Project",
        REPORT_ATTR_BACKEND_HOST_INFO: "demo-project",
    }
    report._ora_adm_user = "DEMO_ADM"
    report._ora_conn = types.SimpleNamespace(close=lambda: None)
    report._ora_db_name = "DEMO"
    report._oracle_dsn = "demo-dsn"
    report._start_ts = "2026-01-01_00-00-00"
    report._start_time = "01 January 2026 00:00:00"
    return report


def _normalise(text: str, directory: pathlib.Path) -> str:
    """Remove environment-dependent fragments: directory, version, year, and column padding."""
    text = text.replace(str(directory), "<DIR>")
    text = re.sub(r"Offload Status Report v\S+", "Offload Status Report v<VERSION>", text)
    text = re.sub(r"Copyright 2015-\d{4}", "Copyright 2015-<YEAR>", text)
    return re.sub(r"[ \t]+", " ", text)
