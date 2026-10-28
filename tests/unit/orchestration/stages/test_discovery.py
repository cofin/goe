# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for SourceDiscoveryStage in goe.orchestration.stages.discovery."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from goe.config.options import OffloadOperationOptions
from goe.exceptions import OffloadException
from goe.offload.schema.column_spec import ColumnDialect, ColumnSpec
from goe.orchestration.models import DiscoveryState, SourcePartitionSlice
from goe.orchestration.stages.discovery import SourceDiscoveryStage
from goe.persistence.models import OffloadMetadata


def test_discovery_stage_hydrates_snapshot_scn_and_prior_metadata() -> None:
    """Verify SourceDiscoveryStage.run produces frozen DiscoveryState and PriorMetadataState."""
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER", nullable=False)
    part = SourcePartitionSlice(partition_name="P1", partition_position=1, high_value_raw="100")
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
        partitions=(part,),
        snapshot_scn=987654,
    )
    prior_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
        incremental_key="ID",
        incremental_high_value="100",
    )

    frontend = MagicMock()
    frontend.table_exists.return_value = True
    frontend.get_discovery_state.return_value = discovery
    frontend.unsupported_data_types.return_value = ()

    repo = MagicMock()
    repo.get_offload_metadata.return_value = prior_meta

    backend_catalog = MagicMock()
    backend_catalog.get_table_columns.return_value = (col,)
    backend_catalog.detect_synthetic_partition_digits.return_value = 6

    stage = SourceDiscoveryStage(frontend, repo, backend_catalog)
    options = OffloadOperationOptions(owner="sh", table_name="sales")
    disc_out, prior_out = stage.run(options, target_owner="sh", target_table_name="sales")

    assert disc_out == discovery
    assert disc_out.snapshot_scn == 987654
    assert prior_out.prior_metadata == prior_meta
    assert prior_out.backend_table_exists is True
    assert prior_out.existing_partition_digits == 6
    assert prior_out.is_incremental_continuation is True


def test_discovery_stage_raises_on_missing_source_table() -> None:
    """Verify OffloadException is raised when the source table does not exist."""
    frontend = MagicMock()
    frontend.table_exists.return_value = False
    stage = SourceDiscoveryStage(frontend, MagicMock(), MagicMock())
    options = OffloadOperationOptions(owner="SH", table_name="MISSING_TBL")

    with pytest.raises(OffloadException, match=r"Source table does not exist: SH\.MISSING_TBL"):
        stage.run(options, target_owner="sh", target_table_name="missing_tbl")


def test_discovery_stage_raises_on_iot_overflow_or_unsupported_columns() -> None:
    """Verify OffloadException is raised on IOT_OVERFLOW or unsupported column data types."""
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="GEOM", data_type="SDO_GEOMETRY")
    iot_discovery = DiscoveryState(
        frontend_type="ORACLE",
        source_owner="SH",
        source_table_name="IOT_TBL",
        iot_type="IOT_OVERFLOW",
        partition_type=None,
        subpartition_type=None,
        partition_columns=(),
        subpartition_columns=(),
        columns=(col,),
        partitions=(),
    )
    frontend = MagicMock()
    frontend.table_exists.return_value = True
    frontend.get_discovery_state.return_value = iot_discovery
    frontend.unsupported_data_types.return_value = ()

    stage = SourceDiscoveryStage(frontend, MagicMock(), MagicMock())
    options = OffloadOperationOptions(owner="SH", table_name="IOT_TBL")
    with pytest.raises(OffloadException, match="Unsupported index-organized table type IOT_OVERFLOW"):
        stage.run(options, target_owner="sh", target_table_name="iot_tbl")

    bad_col_discovery = DiscoveryState(
        frontend_type="ORACLE",
        source_owner="SH",
        source_table_name="GEOM_TBL",
        iot_type=None,
        partition_type=None,
        subpartition_type=None,
        partition_columns=(),
        subpartition_columns=(),
        columns=(col,),
        partitions=(),
    )
    frontend.get_discovery_state.return_value = bad_col_discovery
    frontend.unsupported_data_types.return_value = ("SDO_GEOMETRY",)
    with pytest.raises(OffloadException, match="unsupported column data types: SDO_GEOMETRY"):
        stage.run(options, target_owner="sh", target_table_name="geom_tbl")


def test_discovery_stage_respects_reset_backend_table_flag() -> None:
    """Verify is_incremental_continuation is False when reset_backend_table=True."""
    col = ColumnSpec(dialect=ColumnDialect.ORACLE, name="ID", data_type="NUMBER")
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
    prior_meta = OffloadMetadata(
        offloaded_owner="SH",
        offloaded_table="SALES",
        backend_owner="sh",
        backend_table="sales",
        offload_type="INCREMENTAL",
    )
    frontend = MagicMock()
    frontend.table_exists.return_value = True
    frontend.get_discovery_state.return_value = discovery
    frontend.unsupported_data_types.return_value = ()

    repo = MagicMock()
    repo.get_offload_metadata.return_value = prior_meta

    backend_catalog = MagicMock()
    backend_catalog.get_table_columns.return_value = (col,)
    backend_catalog.detect_synthetic_partition_digits.return_value = None

    stage = SourceDiscoveryStage(frontend, repo, backend_catalog)
    options = OffloadOperationOptions(owner="SH", table_name="SALES", reset_backend_table=True)
    _, prior_out = stage.run(options, target_owner="sh", target_table_name="sales")
    assert prior_out.reset_backend_table is True
    assert prior_out.is_incremental_continuation is False
