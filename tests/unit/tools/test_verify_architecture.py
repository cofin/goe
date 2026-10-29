# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the AST and token architecture boundary verifier."""

from __future__ import annotations

from pathlib import Path

from tools.verify_architecture import BaselineConfig, scan_paths


def test_detects_raw_json_outside_serializers(tmp_path: Path) -> None:
    """scan_paths flags raw json/msgspec.json calls outside src/goe/serializers.py."""
    src_goe = tmp_path / "src" / "goe"
    src_goe.mkdir(parents=True)
    foo_py = src_goe / "foo.py"
    foo_py.write_text("import json\n\ndef dump_it() -> str:\n    return json.dumps({})\n", encoding="utf-8")
    serializers_py = src_goe / "serializers.py"
    serializers_py.write_text(
        "import msgspec\n\ndef encode_it() -> bytes:\n    return msgspec.json.encode({})\n",
        encoding="utf-8",
    )

    violations = scan_paths([foo_py, serializers_py], repo_root=tmp_path)
    assert len(violations) == 1
    assert violations[0].rule == "raw-json"
    assert violations[0].path == "src/goe/foo.py"


def test_detects_sqlglot_and_oracledb_boundary_violations(tmp_path: Path) -> None:
    """scan_paths enforces sqlglot and oracledb package boundaries."""
    bad_py = tmp_path / "src" / "goe" / "report" / "bad.py"
    bad_py.parent.mkdir(parents=True)
    bad_py.write_text("import oracledb\nimport sqlglot\n", encoding="utf-8")

    sql_ok_py = tmp_path / "src" / "goe" / "offload" / "sql_ast" / "ok.py"
    sql_ok_py.parent.mkdir(parents=True)
    sql_ok_py.write_text("import sqlglot\n", encoding="utf-8")

    ora_ok_py = tmp_path / "src" / "goe" / "persistence" / "oracle" / "ok.py"
    ora_ok_py.parent.mkdir(parents=True)
    ora_ok_py.write_text("import oracledb\n", encoding="utf-8")

    violations = scan_paths([bad_py, sql_ok_py, ora_ok_py], repo_root=tmp_path)
    rules_by_path = {(v.path, v.rule) for v in violations}
    assert rules_by_path == {
        ("src/goe/report/bad.py", "sqlglot-boundary"),
        ("src/goe/report/bad.py", "oracledb-boundary"),
    }


def test_detects_nested_imports_member_ordering_and_inline_comments(tmp_path: Path) -> None:
    """scan_paths detects member-ordering, nested-import, and inline-comment violations."""
    mod_py = tmp_path / "src" / "goe" / "sample.py"
    mod_py.parent.mkdir(parents=True)
    mod_py.write_text(
        "def _helper() -> int:\n"
        "    return 1\n\n"
        "def public_fn() -> int:\n"
        "    import os\n"
        "    # inline note inside function\n"
        "    _ = os.name\n"
        "    return _helper()\n",
        encoding="utf-8",
    )

    violations = scan_paths([mod_py], repo_root=tmp_path)
    rules = {v.rule for v in violations}
    assert rules == {"member-ordering", "nested-import", "inline-comment"}


def test_baseline_suppresses_known_file_and_flags_stale_entry(tmp_path: Path) -> None:
    """Baselined (rule, path) pairs are suppressed when active and flagged as stale-baseline when fixed."""
    mod_py = tmp_path / "src" / "goe" / "legacy.py"
    mod_py.parent.mkdir(parents=True)
    mod_py.write_text("import json\n\ndef dump_it() -> str:\n    return json.dumps({})\n", encoding="utf-8")

    baseline = BaselineConfig(entries={"raw-json": frozenset({"src/goe/legacy.py"})})
    active_violations = scan_paths([mod_py], repo_root=tmp_path, baseline=baseline)
    assert active_violations == []

    mod_py.write_text("def dump_it() -> str:\n    return '{}'\n", encoding="utf-8")
    stale_violations = scan_paths([mod_py], repo_root=tmp_path, baseline=baseline)
    assert len(stale_violations) == 1
    assert stale_violations[0].rule == "stale-baseline"
    assert stale_violations[0].path == "src/goe/legacy.py"
