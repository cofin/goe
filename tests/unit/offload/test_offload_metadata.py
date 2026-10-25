# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for offload metadata generation, persistence, and incremental high-value decoding."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_metadata_functions import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
    decode_metadata_incremental_high_values_from_metadata,
    gen_and_save_offload_metadata,
    gen_offload_metadata,
    incremental_hv_list_from_csv,
)
from goe.offload.offload_source_table import OffloadSourceTableInterface
from goe.offload.oracle.oracle_column import OracleColumn
from goe.orchestration import orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.models import OffloadMetadata
from goe.persistence.oracle.oracle_repository import OracleRepositoryService
from tests.unit.test_functions import FAKE_ORACLE_BQ_ENV, build_mock_options


def test_gen_offload_metadata_and_save_persists_via_repository_service() -> None:
    """Verify gen_offload_metadata and gen_and_save_offload_metadata return OffloadMetadata and call set_offload_metadata."""
    execution_id = ExecutionId()
    repo_client = MagicMock(spec=OracleRepositoryService)
    messages = OffloadMessages(execution_id=execution_id, command_type=orchestration_constants.COMMAND_OFFLOAD)
    messages.setup_offload_step(repo_client=repo_client, command_type=orchestration_constants.COMMAND_OFFLOAD)
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    inc_cols = [OracleColumn("TIME_ID", "DATE")]
    inc_hv = "TO_DATE(' 2012-03-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')"

    operation = SimpleNamespace(
        owner="SH",
        table_name="SALES",
        bucket_hash_col="CUST_ID",
        offload_partition_functions=["UDF1"],
        sort_columns=["CUST_ID"],
        ipa_predicate_type=INCREMENTAL_PREDICATE_TYPE_RANGE,
        execution_id=execution_id,
        offload_type="INCREMENTAL",
        hwm_in_hybrid_view=True,
        offload_by_subpartition=False,
        execute=True,
    )
    source_table = SimpleNamespace(owner="SH", table_name="SALES")
    target_table = SimpleNamespace(db_name="sh", table_name="sales")

    generated = gen_and_save_offload_metadata(
        repo_client,
        messages,
        operation,
        config,
        source_table,
        target_table,
        inc_cols,
        [inc_hv],
        None,
        123,
        None,
    )

    assert isinstance(generated, OffloadMetadata)
    assert generated.offloaded_owner == "SH"
    assert generated.offloaded_table == "SALES"
    assert generated.backend_owner == "sh"
    assert generated.backend_table == "sales"
    assert generated.incremental_key == "TIME_ID"
    assert generated.incremental_high_value == inc_hv
    repo_client.set_offload_metadata.assert_called_once_with(generated)

    next_exec = ExecutionId()
    operation.execution_id = next_exec
    operation.sort_columns = ["CUST_ID", "PROD_ID"]
    second = gen_offload_metadata(
        repo_client,
        operation,
        "SH",
        "SALES",
        "sh",
        "sales",
        inc_cols,
        [inc_hv],
        None,
        456,
        generated,
    )
    assert isinstance(second, OffloadMetadata)
    assert second.offload_snapshot == 123
    assert second.offload_sort_columns == "CUST_ID,PROD_ID"
    assert second.command_execution == next_exec


def test_decode_metadata_incremental_high_values_from_metadata() -> None:
    """Verify decode_metadata_incremental_high_values_from_metadata accepts OffloadMetadata."""
    empty_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="FULL",
    )
    fake_source_table = MagicMock(spec=OffloadSourceTableInterface)
    assert decode_metadata_incremental_high_values_from_metadata(empty_meta, fake_source_table) == ([], [], [])

    hv_str = "('A', 'B'), ('C', 'D')"
    assert incremental_hv_list_from_csv(hv_str, INCREMENTAL_PREDICATE_TYPE_LIST) == ["'A', 'B'", "'C', 'D'"]
