# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""GCP AUTO transport ordering and Query Import modernization."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from goe.offload.offload_constants import DBTYPE_BIGQUERY, DBTYPE_SNOWFLAKE
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_GCP_METHODS,
    OFFLOAD_TRANSPORT_GOE_METHODS,
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_SQOOP_METHODS,
    VALID_OFFLOAD_TRANSPORT_METHODS,
)
from goe.offload.transport.factory import choose_offload_transport_method
from goe.offload.transport.query_import import OffloadTransportQueryImport, query_import_fetch_size
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, FAKE_ORACLE_HIVE_ENV, build_mock_options


def test_gcp_auto_prefers_query_import_then_dataproc_and_skips_sqoop() -> None:
    """GCP AUTO evaluates QI, Dataproc, Batches, Submit, Thrift, Livy and never Sqoop."""
    chosen, evaluated = _choose(FAKE_ORACLE_BQ_ENV, OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY)
    assert chosen == OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY
    assert evaluated == [
        OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    ]


def test_non_gcp_auto_order_is_unchanged() -> None:
    """Hadoop AUTO keeps GOE, then Sqoop, then GCP rule order."""
    chosen, evaluated = _choose(FAKE_ORACLE_HIVE_ENV, OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD)
    assert chosen == OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD
    assert evaluated == OFFLOAD_TRANSPORT_GOE_METHODS + OFFLOAD_TRANSPORT_SQOOP_METHODS + OFFLOAD_TRANSPORT_GCP_METHODS


@pytest.mark.parametrize(
    ("requested", "target", "expected"),
    [(5000, DBTYPE_BIGQUERY, 5000), ("20000", DBTYPE_BIGQUERY, 10000), (5000, DBTYPE_SNOWFLAKE, 1000)],
)
def test_query_import_fetch_size_cap(requested: int | str, target: str, expected: int) -> None:
    """BigQuery targets allow up to 10000 rows per fetch; other targets keep 1000."""
    assert query_import_fetch_size(requested, target) == expected


def test_copy_to_dfs_always_removes_local_file(tmp_path: Path) -> None:
    """The local staging file is removed with Path.unlink even when the upload fails."""
    local_file = tmp_path / "part-m-00000.parquet"
    local_file.write_bytes(b"PAR1")
    transport = object.__new__(OffloadTransportQueryImport)
    transport._dry_run = False
    transport._messages = MagicMock()
    transport._backend_dfs = "GCS"
    transport._run_os_cmd = MagicMock()
    transport._dfs_client = MagicMock()
    transport._dfs_client.copy_from_local.side_effect = RuntimeError("upload failed")
    with pytest.raises(RuntimeError):
        transport._query_import_copy_to_dfs(str(local_file), "gs://b/stage/part-m-00000.parquet")
    assert not local_file.exists()
    transport._run_os_cmd.assert_not_called()


def _choose(env: dict, accepted: str) -> tuple[str, list[str]]:
    """Run AUTO selection where only `accepted` validates; return the choice and evaluation order."""
    evaluated: list[str] = []

    def fake_validation_fns(*_args: object, **_kwargs: object) -> dict:
        return {
            method: (lambda m=method: evaluated.append(m) or m == accepted)
            for method in VALID_OFFLOAD_TRANSPORT_METHODS
        }

    operation = MagicMock(offload_transport_method=None)
    with patch(
        "goe.offload.transport.factory.get_offload_transport_method_validation_fns", side_effect=fake_validation_fns
    ):
        chosen = choose_offload_transport_method(operation, MagicMock(), build_mock_options(env), MagicMock())
    return chosen, evaluated
