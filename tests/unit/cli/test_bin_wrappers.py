# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BIN_DIR = REPO_ROOT / "bin"


def test_bin_wrappers_executable():
    wrappers = ["offload", "connect", "agg_validate", "schema_sync", "logmgr", "listener", "offload_status_report"]
    for name in wrappers:
        path = BIN_DIR / name
        assert path.exists(), f"Missing wrapper {name}"
        res = subprocess.run([str(path), "--help"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "deprecated" in res.stderr.lower()
