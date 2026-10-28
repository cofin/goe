# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for OffloadOperation defects and NLS_LANG concurrency safety."""

from __future__ import annotations

import inspect
import os
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from goe.offload import offload_constants
from goe.orchestration.stages import plan_resolution as operation_mod
from goe.orchestration.stages.plan_resolution import (
    OffloadOperation,
    check_and_set_nls_lang,
)


def test_validate_sort_columns_closes_created_backend_api_and_uses_cached_metadata() -> None:
    """Verify validate_sort_columns closes its constructed BackendApi and calls get_hybrid_metadata() with no args."""
    op = object.__new__(OffloadOperation)
    op.execute = True
    op.sort_columns_csv = "COL_A"
    op.sort_columns = None
    op._existing_metadata = Mock()
    op.reset_backend_table = False
    op.get_hybrid_metadata = Mock(wraps=op.get_hybrid_metadata)  # type: ignore[method-assign]

    api = MagicMock()
    api.sorted_table_supported.return_value = True

    with (
        patch.object(operation_mod, "create_backend_api", return_value=api),
        patch.object(operation_mod, "sort_columns_csv_to_sort_columns", return_value=["COL_A"]),
    ):
        op.validate_sort_columns(
            offload_source_table=Mock(),
            messages=Mock(),
            offload_options=Mock(target="bigquery"),
            backend_cols=[],
        )

    api.close.assert_called_once_with()
    op.get_hybrid_metadata.assert_called_once_with()
    assert op.sort_columns == ["COL_A"]


def test_validate_sort_columns_does_not_close_caller_supplied_backend_api() -> None:
    """Verify validate_sort_columns does not close an explicit caller-supplied backend_api."""
    op = object.__new__(OffloadOperation)
    op.execute = True
    op.sort_columns_csv = "COL_A"
    op.sort_columns = None
    op._existing_metadata = Mock()
    op.reset_backend_table = False

    api = MagicMock()
    api.sorted_table_supported.return_value = True

    with patch.object(operation_mod, "sort_columns_csv_to_sort_columns", return_value=["COL_A"]):
        op.validate_sort_columns(
            offload_source_table=Mock(),
            messages=Mock(),
            offload_options=Mock(target="bigquery"),
            backend_cols=[],
            backend_api=api,
        )

    api.close.assert_not_called()


def test_check_and_set_nls_lang_resolves_once_under_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify concurrent threads resolve and populate NLS_LANG at most once per process."""
    monkeypatch.delenv("NLS_LANG", raising=False)
    monkeypatch.setattr(operation_mod, "_NLS_LANG_INITIALIZED", False)

    barrier = threading.Barrier(4)
    opts = SimpleNamespace(db_type=offload_constants.DBTYPE_ORACLE)

    def _worker() -> None:
        barrier.wait()
        check_and_set_nls_lang(opts, messages=Mock())

    with patch.object(operation_mod, "get_db_charset", return_value="AL32UTF8") as mock_charset:
        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert mock_charset.call_count == 1
    assert os.environ["NLS_LANG"] == ".AL32UTF8"


def test_offload_operation_omits_max_hybrid_name_length() -> None:
    """Verify max_hybrid_name_length parameter is removed from OffloadOperation.__init__."""
    params = inspect.signature(OffloadOperation.__init__).parameters
    assert "max_hybrid_name_length" not in params
