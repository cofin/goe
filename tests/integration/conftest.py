# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Pytest configuration and environment preflight fixtures for GOE integration tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.nodes import Item


def pytest_collection_modifyitems(config: Config, items: list[Item]) -> None:
    """Attach integration markers and skip tests when required database/cloud env vars are absent."""
    has_oracle_env = bool(os.environ.get("ORA_CONN") and os.environ.get("ORA_ADM_USER"))
    has_gcp_env = bool(
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("BIGQUERY_DATASET_PROJECT")
        or os.environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
    )

    skip_oracle = pytest.mark.skip(
        reason="Integration test requires ORA_CONN and ORA_ADM_USER environment configuration."
    )
    skip_bigquery = pytest.mark.skip(
        reason="BigQuery integration test requires GOOGLE_CLOUD_PROJECT and ADC credentials."
    )

    for item in items:
        item.add_marker(pytest.mark.oracle)
        if "scenarios" in item.nodeid or "bigquery" in item.nodeid:
            item.add_marker(pytest.mark.bigquery)
            if not has_gcp_env:
                item.add_marker(skip_bigquery)
        if not has_oracle_env:
            item.add_marker(skip_oracle)
