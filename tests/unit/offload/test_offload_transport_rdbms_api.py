# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""TestOffloadTransportRdbmsApi: Unit tests for each Offload Transport RDBMS API."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_source_data import (
    OffloadSourcePartition,
    OffloadSourcePartitions,
)
from goe.offload.offload_transport_rdbms_api import (
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
)
from goe.offload.oracle.oracle_offload_transport_rdbms_api import LOG_SQL_STATS_QUERY_TEXT
from goe.offload.registry import create_transport_rdbms_api
from tests.unit.test_functions import (
    FAKE_MSSQL_ENV,
    FAKE_ORACLE_ENV,
    FAKE_ORACLE_LIST_RANGE_PARTITIONS,
    FAKE_ORACLE_PARTITIONS,
    build_fake_oracle_subpartitioned_table,
    build_fake_oracle_table,
    build_mock_options,
)


@pytest.fixture
def oracle_config():
    return build_mock_options(FAKE_ORACLE_ENV)


@pytest.fixture
def messages():
    return OffloadMessages()


@pytest.fixture
def fake_oracle_table(oracle_config, messages):
    return build_fake_oracle_table(oracle_config, messages)


@pytest.fixture
def fake_oracle_subpartitioned_table(oracle_config, messages):
    return build_fake_oracle_subpartitioned_table(oracle_config, messages)


def non_connecting_tests(api):
    assert isinstance(api.generate_transport_action(), str)
    assert isinstance(api.get_rdbms_canary_query(), str)
    try:
        assert isinstance(api.get_transport_row_source_query_hint_block(), str)
    except NotImplementedError:
        pass
    assert isinstance(api.jdbc_url(), str)
    assert isinstance(api.jdbc_driver_name(), (str, type(None)))


def test_mssql_ot_rdbms_api(messages):
    """Simple check that we can instantiate the MSSQL API"""
    config = build_mock_options(FAKE_MSSQL_ENV)
    rdbms_owner = "SH_TEST"
    rdbms_table = "SALES"
    api = create_transport_rdbms_api(rdbms_owner, rdbms_table, config, messages, dry_run=True)
    non_connecting_tests(api)


def test_oracle_ot_rdbms_api(oracle_config, messages):
    """Simple check that we can instantiate the Oracle API"""
    oracle_config = build_mock_options(FAKE_ORACLE_ENV)
    rdbms_owner = "SH_TEST"
    rdbms_table = "SALES"
    api = create_transport_rdbms_api(rdbms_owner, rdbms_table, oracle_config, messages, dry_run=True)
    non_connecting_tests(api)
    assert isinstance(api.get_snapshot_clause(123456, True), str)
    assert "123456" in api.get_snapshot_clause(123456, True)
    assert "123456" not in api.get_snapshot_clause(123456, False)


def offload_partitions_from_rdbms_partitions(rdbms_partitions):
    partitions = [
        OffloadSourcePartition(
            _.partition_name,
            _.high_values_csv,
            _.high_values_python,
            _.high_values_individual,
            _.partition_size,
            _.num_rows,
            None,  # common_partition_literal
            _.subpartition_names,
        )
        for _ in rdbms_partitions
    ]
    return OffloadSourcePartitions(partitions)


@pytest.mark.parametrize(
    "parallelism,partition_type,offload_by_subpartition,partition_chunk,expected_split_type,expected_parallelism",
    [
        (
            1,
            None,
            False,
            None,
            # Non-partitioned tables should always split by ROWID range.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
            1,
        ),
        (
            10,
            None,
            False,
            None,
            # Non-partitioned tables should always split by ROWID range.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
            10,
        ),
    ],
)
def test_get_transport_split_type_oracle_heap(
    oracle_config,
    messages,
    fake_oracle_table,
    parallelism,
    partition_type,
    offload_by_subpartition,
    partition_chunk,
    expected_split_type,
    expected_parallelism,
):
    api = create_transport_rdbms_api(
        fake_oracle_table.owner,
        fake_oracle_table.table_name,
        oracle_config,
        messages,
        dry_run=True,
    )
    rdbms_columns = fake_oracle_table.columns
    predicate_offload_clause = None

    split_return = api.get_transport_split_type(
        partition_chunk,
        fake_oracle_table,
        parallelism,
        partition_type,
        rdbms_columns,
        offload_by_subpartition,
        predicate_offload_clause,
    )

    assert isinstance(split_return, tuple)
    assert split_return[0] == expected_split_type
    assert split_return[1] == expected_parallelism


@pytest.mark.parametrize(
    "parallelism,partition_chunk,expected_split_type,expected_parallelism",
    [
        # Offload 2 partitions with parallelism of 2.
        (
            2,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_PARTITIONS[:2]),
            # 2 partitions with parallel 2 should split by partition.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
            2,
        ),
        # Offload 2 partitions with parallelism of 1.
        (
            1,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_PARTITIONS[:2]),
            # 2 partitions with parallel 1 should split by partition.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
            1,
        ),
        # Offload 2 partitions with parallelism of 3.
        (
            3,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_PARTITIONS[:2]),
            # 2 partitions with parallel 3 should split by ROWID range.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
            3,
        ),
        # Offload 1 partition with parallelism of 2.
        (
            2,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_PARTITIONS[:1]),
            # 1 partitions should split by ROWID range.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
            2,
        ),
    ],
)
def test_get_transport_split_type_oracle_partitioned(
    oracle_config,
    messages,
    fake_oracle_table,
    parallelism,
    partition_chunk,
    expected_split_type,
    expected_parallelism,
):
    api = create_transport_rdbms_api(
        fake_oracle_table.owner,
        fake_oracle_table.table_name,
        oracle_config,
        messages,
        dry_run=True,
    )
    predicate_offload_clause = None
    offload_by_subpartition = False

    split_return = api.get_transport_split_type(
        partition_chunk,
        fake_oracle_table,
        parallelism,
        fake_oracle_table.partition_type,
        offload_by_subpartition,
        predicate_offload_clause,
    )

    assert isinstance(split_return, tuple)
    assert split_return[0] == expected_split_type
    assert split_return[1] == expected_parallelism


@pytest.mark.parametrize(
    "parallelism,partition_chunk,offload_by_subpartition,expected_split_type,expected_parallelism",
    [
        # Offload 1 top level partition with parallelism of 2.
        (
            2,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_LIST_RANGE_PARTITIONS[:1]),
            False,
            # 4 subpartitions with parallel 2 should split by subpartition.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
            2,
        ),
        # Offload 1 top level partition with parallelism of 5, greater than 4 subpartitions.
        (
            5,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_LIST_RANGE_PARTITIONS[:1]),
            False,
            # 4 subpartitions with parallel 2 should split by subpartition.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
            5,
        ),
        # Offload 2 top level partitions with parallelism of 2.
        (
            2,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_LIST_RANGE_PARTITIONS[:2]),
            False,
            # 2 is enough for top-level partitions, no need to split by subpartition.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
            2,
        ),
        # Offload 2 top level partitions with parallelism of 2.
        (
            2,
            offload_partitions_from_rdbms_partitions(FAKE_ORACLE_LIST_RANGE_PARTITIONS[:2]),
            True,
            # 2 is enough for top-level partitions but we asked for subpartition therefore split by subpartition.
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
            2,
        ),
    ],
)
def test_get_transport_split_type_oracle_subpartitioned(
    oracle_config,
    messages,
    fake_oracle_subpartitioned_table,
    parallelism,
    partition_chunk,
    offload_by_subpartition,
    expected_split_type,
    expected_parallelism,
):
    api = create_transport_rdbms_api(
        fake_oracle_subpartitioned_table.owner,
        fake_oracle_subpartitioned_table.table_name,
        oracle_config,
        messages,
        dry_run=True,
    )
    predicate_offload_clause = None

    split_return = api.get_transport_split_type(
        partition_chunk,
        fake_oracle_subpartitioned_table,
        parallelism,
        fake_oracle_subpartitioned_table.partition_type,
        offload_by_subpartition,
        predicate_offload_clause,
    )

    assert isinstance(split_return, tuple)
    assert split_return[0] == expected_split_type
    assert split_return[1] == expected_parallelism


class FakeRegistry:
    """In-memory stand-in for OracleDatabaseRegistry in transport API tests."""

    def __init__(self, version: str = "19.3.0.0.0") -> None:
        self.version = version
        self.sessions: list[tuple[str, str, bool]] = []
        self.connection = MagicMock()
        self.connection.cursor.return_value.execute.return_value.fetchone.return_value = (1, 99)
        self.connection.cursor.return_value.execute.return_value.fetchall.return_value = [("sqlid", 0, 10, 1, 0, 1)]

    def server_version(self) -> str:
        """Return the configured Oracle server version."""
        return self.version

    @contextmanager
    def app_transport_session(self, module: str, action: str, *, isolate_session: bool = False) -> Iterator[MagicMock]:
        """Record the transport session request and yield the mock connection."""
        self.sessions.append((module, action, isolate_session))
        yield self.connection


def test_oracle_id_range_uses_transport_session(oracle_config, messages) -> None:
    """get_id_range checks out an app_transport_session and closes its cursor."""
    api = create_transport_rdbms_api("SH_TEST", "SALES", oracle_config, messages, dry_run=True)
    registry = FakeRegistry()
    api._registry = registry
    assert api.get_id_range("ID", "") == (1, 99)
    assert registry.sessions == [("GOE", "OffloadTransport", False)]
    registry.connection.cursor.return_value.close.assert_called_once_with()


def test_oracle_sql_stats_function_keeps_transport_module_and_action(oracle_config, messages) -> None:
    """get_offload_transport_sql_stats_function checks out a session per call and binds module/action."""
    api = create_transport_rdbms_api("SH_TEST", "SALES", oracle_config, messages, dry_run=True)
    registry = FakeRegistry()
    api._registry = registry
    fn = api.get_offload_transport_sql_stats_function("GOE", "A1B2_sales", "OffloadTransportSqlStatsThread")
    assert fn() == [("sqlid", 0, 10, 1, 0, 1)]
    assert registry.sessions == [("GOE", "OffloadTransportSqlStatsThread", False)]
    registry.connection.cursor.return_value.execute.assert_called_with(
        LOG_SQL_STATS_QUERY_TEXT, {"module": "GOE", "action": "A1B2_sales"}
    )
    fn()
    assert len(registry.sessions) == 2


def test_oracle_query_import_isolates_session(oracle_config, messages) -> None:
    """query_import_extraction uses isolate_session=True and runs session setup before the source query."""
    api = create_transport_rdbms_api("SH_TEST", "SALES", oracle_config, messages, dry_run=False)
    registry = FakeRegistry()
    api._registry = registry
    with api.query_import_extraction(
        [],
        "SELECT 1 FROM dual",
        None,
        100,
        False,
        ["ALTER SESSION SET TIME_ZONE='UTC'"],
    ) as cursor:
        assert registry.sessions == [("GOE", "OffloadTransport", True)]
        assert cursor.arraysize == 100
        executed = [call.args[0] for call in cursor.execute.call_args_list]
        assert executed == ["ALTER SESSION SET TIME_ZONE='UTC'", "SELECT 1 FROM dual"]


def test_fixed_goe_parameters_use_cached_server_version(oracle_config, messages) -> None:
    """_get_fixed_goe_parameters reads server_version() without opening a transport session."""
    api_12_1 = create_transport_rdbms_api("SH_TEST", "SALES", oracle_config, messages, dry_run=True)
    reg_12_1 = FakeRegistry(version="12.1.0.2.0")
    api_12_1._registry = reg_12_1
    api_12_1._fixed_goe_parameters = None
    assert api_12_1._get_fixed_goe_parameters() == {"CELL_OFFLOAD_PROCESSING": "FALSE"}
    assert reg_12_1.sessions == []

    api_19 = create_transport_rdbms_api("SH_TEST", "SALES", oracle_config, messages, dry_run=True)
    reg_19 = FakeRegistry(version="19.3.0.0.0")
    api_19._registry = reg_19
    api_19._fixed_goe_parameters = None
    assert api_19._get_fixed_goe_parameters() == {}
    assert reg_19.sessions == []
