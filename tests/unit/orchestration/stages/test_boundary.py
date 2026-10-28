# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BoundaryResolutionStage in goe.orchestration.stages.boundary."""

from __future__ import annotations

import pytest

from goe.config.options import OffloadOperationOptions
from goe.exceptions import OffloadException
from goe.offload.predicates import PredicateCompiler
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_INT64,
    ORACLE_TYPE_NUMBER,
    ColumnDialect,
    ColumnSpec,
)
from goe.orchestration.models import (
    DiscoveryState,
    PriorMetadataState,
    SourcePartitionSlice,
)
from goe.orchestration.stages.boundary import (
    IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT,
    PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT,
    BoundaryResolutionStage,
    chunk_partitions,
)
from goe.persistence.models import OffloadMetadata


def test_range_ipa_initial_90_10_and_subsequent_append() -> None:
    """Verify initial 90/10 range offload and subsequent incremental range append."""
    stage = BoundaryResolutionStage(PredicateCompiler())
    discovery = _range_discovery()
    prior_initial = PriorMetadataState()
    opts_initial = OffloadOperationOptions(owner="SH", table_name="SALES", less_than_value="2025-02-01")

    boundary, predicate = stage.run(discovery, prior_initial, opts_initial, backend_dialect="bigquery")
    assert boundary.offload_mode == "INCREMENTAL_RANGE"
    assert boundary.offload_type == "INCREMENTAL"
    assert boundary.prior_high_value_raw is None
    assert boundary.target_high_value_raw == "2025-02-01"
    assert [p.partition_name for p in boundary.partitions_to_offload] == ["P_JAN", "P_FEB"]
    assert predicate.frontend_where_clause == "TIME_ID < 2025-02-01"

    prior_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="TIME_ID",
        incremental_high_value="2025-02-01",
        incremental_predicate_type="RANGE",
    )
    prior_append = PriorMetadataState(prior_metadata=prior_meta, backend_table_exists=True)
    opts_append = OffloadOperationOptions(owner="SH", table_name="SALES", less_than_value="2025-03-01")

    boundary2, predicate2 = stage.run(discovery, prior_append, opts_append, backend_dialect="bigquery")
    assert boundary2.prior_high_value_raw == "2025-02-01"
    assert boundary2.target_high_value_raw == "2025-03-01"
    assert [p.partition_name for p in boundary2.partitions_to_offload] == ["P_MAR"]
    assert predicate2.frontend_where_clause == "TIME_ID >= 2025-02-01 AND TIME_ID < 2025-03-01"
    assert predicate2.prior_where_clause == "TIME_ID < 2025-02-01"


def test_range_ipa_100_10_transition_and_maxvalue_guard() -> None:
    """Verify 90/10 -> 100/10 incremental continuation and refusal of MAXVALUE target."""
    stage = BoundaryResolutionStage(PredicateCompiler())
    discovery = _range_discovery()
    prior_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="TIME_ID",
        incremental_high_value="2025-02-01",
        incremental_predicate_type="RANGE",
    )
    prior_state = PriorMetadataState(prior_metadata=prior_meta, backend_table_exists=True)

    opts_100_10 = OffloadOperationOptions(owner="SH", table_name="SALES")
    boundary, _ = stage.run(discovery, prior_state, opts_100_10, backend_dialect="bigquery")
    assert boundary.offload_type == "INCREMENTAL"
    assert [p.partition_name for p in boundary.partitions_to_offload] == ["P_MAR"]

    opts_maxval = OffloadOperationOptions(owner="SH", table_name="SALES", less_than_value="MAXVALUE")
    with pytest.raises(OffloadException, match=IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT):
        stage.run(discovery, prior_state, opts_maxval, backend_dialect="bigquery")


def test_list_ipa_filters_already_offloaded_values_and_rejects_default() -> None:
    """Verify INCREMENTAL_LIST excludes already offloaded values and rejects DEFAULT."""
    stage = BoundaryResolutionStage(PredicateCompiler())
    discovery = _list_discovery()
    prior_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="REGION",
        incremental_high_value="'US'",
        incremental_predicate_type="LIST",
    )
    prior_state = PriorMetadataState(prior_metadata=prior_meta, backend_table_exists=True)
    opts = OffloadOperationOptions(owner="SH", table_name="SALES", equal_to_values=["'EU'"])

    boundary, predicate = stage.run(discovery, prior_state, opts, backend_dialect="bigquery")
    assert boundary.offload_mode == "INCREMENTAL_LIST"
    assert [p.partition_name for p in boundary.partitions_to_offload] == ["P_EU"]
    assert boundary.target_high_value_literals == ("'US'", "'EU'")
    assert predicate.frontend_where_clause == "REGION IN ('EU')"

    opts_default = OffloadOperationOptions(owner="SH", table_name="SALES", equal_to_values=["DEFAULT"])
    with pytest.raises(OffloadException, match=IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT):
        stage.run(discovery, prior_state, opts_default, backend_dialect="bigquery")


def test_partition_chunking_by_size_and_count() -> None:
    """Verify chunk_partitions splits slices respecting max_chunk_size_bytes and max_chunk_count."""
    slices = tuple(
        SourcePartitionSlice(
            partition_name=f"P{i}",
            partition_position=i,
            high_value_raw=str(i),
            byte_size=1000,
            row_count=10,
        )
        for i in range(1, 6)
    )
    by_count = chunk_partitions(slices, max_chunk_count=2)
    assert len(by_count) == 3
    assert [len(c) for c in by_count] == [2, 2, 1]

    by_size = chunk_partitions(slices, max_chunk_size_bytes=2500)
    assert len(by_size) == 3
    assert [len(c) for c in by_size] == [2, 2, 1]


def test_predicate_offload_compiles_via_predicate_compiler() -> None:
    """Verify offload_predicate compiles via PredicateCompiler and checks prior ipa_predicate_type."""
    stage = BoundaryResolutionStage(PredicateCompiler())
    col = ColumnSpec(
        dialect=ColumnDialect.ORACLE,
        name="ID",
        data_type=ORACLE_TYPE_NUMBER,
        data_precision=18,
        data_scale=0,
    )
    discovery = DiscoveryState(
        frontend_type="ORACLE",
        source_owner="SH",
        source_table_name="SALES",
        iot_type=None,
        partition_type="RANGE",
        subpartition_type=None,
        partition_columns=("ID",),
        subpartition_columns=(),
        columns=(col,),
        partitions=(),
    )
    opts = OffloadOperationOptions(owner="SH", table_name="SALES", offload_predicate="column(ID) > numeric(1000)")
    boundary, predicate = stage.run(discovery, PriorMetadataState(), opts, backend_dialect="bigquery")
    assert boundary.offload_mode == "PREDICATE"
    assert boundary.offload_type == "INCREMENTAL"
    assert predicate.frontend_where_clause == '"ID" > 1000'
    assert predicate.backend_where_clause == "`ID` > 1000"

    bad_prior = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_predicate_type="RANGE",
    )
    with pytest.raises(OffloadException, match=PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT):
        stage.run(
            discovery,
            PriorMetadataState(prior_metadata=bad_prior, backend_table_exists=True),
            opts,
            backend_dialect="bigquery",
        )


def test_nothing_to_offload_returns_no_op_boundary_plan() -> None:
    """Verify nothing_to_offload is True when all qualifying partitions are <= prior_hv."""
    stage = BoundaryResolutionStage(PredicateCompiler())
    discovery = _range_discovery()
    prior_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="TIME_ID",
        incremental_high_value="2025-03-01",
        incremental_predicate_type="RANGE",
    )
    prior_state = PriorMetadataState(prior_metadata=prior_meta, backend_table_exists=True)
    opts = OffloadOperationOptions(owner="SH", table_name="SALES", less_than_value="2025-03-01")

    boundary, _ = stage.run(discovery, prior_state, opts, backend_dialect="bigquery")
    assert boundary.nothing_to_offload is True
    assert boundary.partitions_to_offload == ()


def _range_discovery() -> DiscoveryState:
    col = ColumnSpec(dialect=ColumnDialect.BIGQUERY, name="TIME_ID", data_type=BIGQUERY_TYPE_INT64)
    partitions = (
        SourcePartitionSlice(
            partition_name="P_JAN",
            partition_position=1,
            high_value_raw="2025-01-01",
            high_value_literals=("'2025-01-01'",),
            byte_size=1024,
            row_count=100,
        ),
        SourcePartitionSlice(
            partition_name="P_FEB",
            partition_position=2,
            high_value_raw="2025-02-01",
            high_value_literals=("'2025-02-01'",),
            byte_size=1024,
            row_count=100,
        ),
        SourcePartitionSlice(
            partition_name="P_MAR",
            partition_position=3,
            high_value_raw="2025-03-01",
            high_value_literals=("'2025-03-01'",),
            byte_size=1024,
            row_count=100,
        ),
        SourcePartitionSlice(
            partition_name="P_MAX",
            partition_position=4,
            high_value_raw="MAXVALUE",
            high_value_literals=("MAXVALUE",),
            byte_size=0,
            row_count=0,
            is_default=True,
        ),
    )
    return DiscoveryState(
        frontend_type="ORACLE",
        source_owner="SH",
        source_table_name="SALES",
        iot_type=None,
        partition_type="RANGE",
        subpartition_type=None,
        partition_columns=("TIME_ID",),
        subpartition_columns=(),
        columns=(col,),
        partitions=partitions,
    )


def _list_discovery() -> DiscoveryState:
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="REGION", data_type="VARCHAR2")
    partitions = (
        SourcePartitionSlice(
            partition_name="P_US",
            partition_position=1,
            high_value_raw="'US'",
            high_value_literals=("'US'",),
            byte_size=1024,
            row_count=100,
        ),
        SourcePartitionSlice(
            partition_name="P_EU",
            partition_position=2,
            high_value_raw="'EU'",
            high_value_literals=("'EU'",),
            byte_size=1024,
            row_count=100,
        ),
        SourcePartitionSlice(
            partition_name="P_DEFAULT",
            partition_position=3,
            high_value_raw="DEFAULT",
            high_value_literals=("DEFAULT",),
            byte_size=0,
            row_count=0,
            is_default=True,
        ),
    )
    return DiscoveryState(
        frontend_type="ORACLE",
        source_owner="SH",
        source_table_name="SALES",
        iot_type=None,
        partition_type="LIST",
        subpartition_type=None,
        partition_columns=("REGION",),
        subpartition_columns=(),
        columns=(col,),
        partitions=partitions,
    )
