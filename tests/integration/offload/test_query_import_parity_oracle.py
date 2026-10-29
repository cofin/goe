# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Live Oracle integration parity suite for OracleArrowStreamExtractor and Arrow staging writers."""

import os
from pathlib import Path

import pytest

from goe.serializers import decode_json
from tests.unit.offload.transport.test_query_import_parity import (
    GOLDEN_MANIFEST_PATH,
    build_arrow_parity_manifest,
)


@pytest.mark.integration
def test_oracle_arrow_query_import_parity_integration(tmp_path: Path) -> None:
    """Verify end-to-end Arrow extraction and Parquet/Avro staging parity when Oracle credentials are configured."""
    if not os.environ.get("GOE_TEST_USER_PASS") and not os.environ.get("ORA_APP_PASS"):
        pytest.skip("Oracle integration credentials (GOE_TEST_USER_PASS / ORA_APP_PASS) are not configured")
    golden = decode_json(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = build_arrow_parity_manifest(tmp_path)
    assert actual["parquet_standard"] == golden["parquet_standard"]
    assert actual["avro_standard"] == golden["avro_standard"]
