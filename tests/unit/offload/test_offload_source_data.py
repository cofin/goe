# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from goe.offload.bigquery.bigquery_backend_table import BackendBigQueryTable
from goe.offload.offload_constants import DBTYPE_BIGQUERY, PART_OUT_OF_LIST
from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_metadata_functions import OFFLOAD_TYPE_FULL, OFFLOAD_TYPE_INCREMENTAL
from goe.offload.offload_source_data import (
    OFFLOAD_SOURCE_CLIENT_OFFLOAD,
    OffloadSourceDataIpaRange,
    OffloadSourcePartitions,
    get_offload_type_for_config,
    is_default_partition,
)
from tests.unit.test_functions import (
    FAKE_ORACLE_BQ_ENV,
    build_fake_oracle_table,
    build_mock_offload_operation,
    build_mock_options,
)


@pytest.fixture(scope="module")
def config():
    return build_mock_options(FAKE_ORACLE_BQ_ENV)


@pytest.fixture(scope="module")
def messages():
    return OffloadMessages()


@pytest.fixture
def oracle_table(config, messages):
    return build_fake_oracle_table(config, messages)


@pytest.fixture(scope="module")
def bigquery_table(config, messages):
    fake_operation = build_mock_offload_operation()
    test_table_object = BackendBigQueryTable(
        "no_user",
        "no_table",
        DBTYPE_BIGQUERY,
        config,
        messages,
        fake_operation,
        None,
        dry_run=True,
        do_not_connect=True,
    )
    return test_table_object


@pytest.mark.parametrize(
    "max_offload_chunk_count,max_offload_chunk_size,expected_chunks",
    [
        (1, 1_000_000_000, 4),
        (3, 1_000_000_000, 2),
        (4, 1_000_000_000, 1),
        (100, 1_000, 4),
        (100, 1_100_000, 4),
        (100, 2_000_001, 2),
        (100, 2_100_000, 2),
        (100, 4_000_001, 1),
    ],
)
def test_partition_chunking(
    messages,
    oracle_table,
    bigquery_table,
    max_offload_chunk_count,
    max_offload_chunk_size,
    expected_chunks,
):
    """Simulate partition chunking across partition count and size limits for 4 x 1MB input partitions."""
    fake_operation = build_mock_offload_operation()
    fake_operation.max_offload_chunk_count = max_offload_chunk_count
    fake_operation.max_offload_chunk_size = max_offload_chunk_size

    client = OffloadSourceDataIpaRange(
        oracle_table,
        bigquery_table,
        fake_operation,
        {},
        messages,
        OFFLOAD_SOURCE_CLIENT_OFFLOAD,
    )
    partitions_to_offload = OffloadSourcePartitions.from_source_table(oracle_table, True)
    client._override_partitions_to_offload(partitions_to_offload)
    chunks = list(client.get_partitions_to_offload_chunks())
    assert len(chunks) == expected_chunks, f"Partition chunk count should be {expected_chunks}, not {len(chunks)}"
    total_p_count = sum(_[0].count() for _ in chunks)
    assert total_p_count == 4, f"Total partition count should be 4, not {total_p_count}"
    assert chunks[0][0].get_partitions()[-1].partition_name == "P1"
    assert chunks[-1][0].get_partitions()[0].partition_name == "P4"


def test_get_offload_type_for_config_downgrades_incapable_incremental() -> None:
    """A requested INCREMENTAL offload on a non-append-capable table becomes FULL."""
    result = get_offload_type_for_config("SH", "SALES", OFFLOAD_TYPE_INCREMENTAL, False, [], None, Mock())
    assert result == (OFFLOAD_TYPE_FULL, False)


def test_get_offload_type_for_config_inherits_hybrid_metadata() -> None:
    """Existing metadata with a high value keeps INCREMENTAL and the hybrid-view predicate."""
    metadata = SimpleNamespace(
        offload_type=OFFLOAD_TYPE_INCREMENTAL, incremental_high_value="2020-01-01", incremental_predicate_value=None
    )
    result = get_offload_type_for_config("SH", "SALES", None, True, [], metadata, Mock())
    assert result == (OFFLOAD_TYPE_INCREMENTAL, True)


def test_get_offload_type_for_config_implies_incremental_from_options() -> None:
    """Partition-append options on a capable table imply INCREMENTAL."""
    result = get_offload_type_for_config("SH", "SALES", None, True, ["older_than_date"], None, Mock())
    assert result == (OFFLOAD_TYPE_INCREMENTAL, True)


def test_is_default_partition() -> None:
    """Only the out-of-list sentinel marks a DEFAULT partition."""
    assert is_default_partition(SimpleNamespace(partition_values_python=[PART_OUT_OF_LIST.lower()])) is True
    assert is_default_partition(SimpleNamespace(partition_values_python=["P1"])) is False
