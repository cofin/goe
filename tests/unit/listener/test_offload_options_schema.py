# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Listener OffloadOptions, ListenerConfig, and ColumnDetail schema alignment."""

from unittest.mock import AsyncMock, MagicMock, patch

from litestar.di import Provide
from litestar.testing import TestClient
from litestar_queues import QueueService

from goe.goe import EXPECTED_OFFLOAD_ARGS
from goe.listener import jobs
from goe.listener.app import create_app
from goe.listener.schemas import ColumnDetail, ListenerConfig, OffloadOptions


def test_offload_options_canonical_keys_and_older_than_days_normalization() -> None:
    """Verify OffloadOptions accepts canonical EXPECTED_OFFLOAD_ARGS fields and normalizes older_than_days to str."""
    opts = OffloadOptions(
        owner_table="SH.SALES",
        execute=False,
        reset_backend_table=True,
        target_owner_name="prod_sh.sales",
        older_than_days=30,
    )
    params = opts.to_params_dict()
    assert set(params.keys()).issubset(set(EXPECTED_OFFLOAD_ARGS))
    assert params["owner_table"] == "SH.SALES"
    assert params["execute"] is False
    assert params["reset_backend_table"] is True
    assert params["target_owner_name"] == "prod_sh.sales"
    assert params["older_than_days"] == "30"


def test_offload_options_alias_normalization() -> None:
    """Verify OffloadOptions.to_params_dict() normalizes legacy alias fields to canonical EXPECTED_OFFLOAD_ARGS keys."""
    opts = OffloadOptions(
        owner_table="SH.SALES",
        target_table_name="prod_sh.sales",
        partitions=["P1", "P2"],
        bucket_hash_column="PROD_ID",
        sort_columns=["TIME_ID", "CHANNEL_ID"],
        partition_functions=["PF1"],
        offload_chunk_count=4,
        allow_floating_point=True,
        compress_backend_table=True,
        replace_hybrid_view=True,
        quiet=True,
        verbose=True,
    )
    params = opts.to_params_dict()
    assert set(params.keys()).issubset(set(EXPECTED_OFFLOAD_ARGS))
    assert params["target_owner_name"] == "prod_sh.sales"
    assert params["partition_names_csv"] == "P1,P2"
    assert params["bucket_hash_col"] == "PROD_ID"
    assert params["sort_columns_csv"] == "TIME_ID,CHANNEL_ID"
    assert params["offload_partition_functions"] == "PF1"
    assert params["max_offload_chunk_count"] == 4
    assert params["allow_floating_point_conversions"] is True
    assert params["compress_load_table"] is True
    assert params["reset_hybrid_view"] is True
    assert "quiet" not in params
    assert "verbose" not in params


def test_offload_options_subpartitions_normalization() -> None:
    """Verify OffloadOptions.to_params_dict() maps subpartitions to partition_names_csv and offload_by_subpartition."""
    opts = OffloadOptions(
        owner_table="SH.SALES",
        subpartitions=["SP1", "SP2"],
    )
    params = opts.to_params_dict()
    assert set(params.keys()).issubset(set(EXPECTED_OFFLOAD_ARGS))
    assert params["partition_names_csv"] == "SP1,SP2"
    assert params["offload_by_subpartition"] is True


@patch("goe.listener.utils.orchestrate.check_for_running_command")
@patch.object(QueueService, "enqueue", new_callable=AsyncMock)
def test_orchestration_post_offload_passes_only_expected_offload_args(
    mock_enqueue: AsyncMock,
    mock_check: MagicMock,
) -> None:
    """Verify POST /api/orchestration/offload/ passes only EXPECTED_OFFLOAD_ARGS keys to queue_service.enqueue."""
    app = create_app()
    with TestClient(app=app) as client:
        response = client.post(
            "/api/orchestration/offload/",
            json={
                "owner_table": "SH.SALES",
                "target_table_name": "prod_sh.sales",
                "partitions": ["P1", "P2"],
                "reset_backend_table": True,
                "execute": False,
            },
        )
        assert response.status_code in (200, 201)
    mock_enqueue.assert_awaited_once()
    assert mock_enqueue.call_args.args[0] is jobs.run_offload_job
    passed_params = mock_enqueue.call_args.kwargs["params"]
    assert set(passed_params.keys()).issubset(set(EXPECTED_OFFLOAD_ARGS))
    assert passed_params["target_owner_name"] == "prod_sh.sales"
    assert passed_params["partition_names_csv"] == "P1,P2"
    assert passed_params["reset_backend_table"] is True
    assert "quiet" not in passed_params
    assert "verbose" not in passed_params


def test_listener_config_and_column_detail_optional_fields() -> None:
    """Verify ListenerConfig accepts offload/present/prepare_options and ColumnDetail accepts data_precision."""
    cfg = ListenerConfig(
        endpoint_id="ep-1",
        listener_group_id="grp-1",
        db_unique_name="ORCL",
        offload_options={"owner_table": "SH.SALES"},
        present_options={"foo": "bar"},
        prepare_options={"baz": 1},
    )
    assert cfg.offload_options == {"owner_table": "SH.SALES"}
    assert cfg.present_options == {"foo": "bar"}
    assert cfg.prepare_options == {"baz": 1}

    col = ColumnDetail(
        column_name="AMOUNT_SOLD",
        data_type="NUMBER",
        data_precision=10,
        data_scale=2,
    )
    assert col.data_precision == 10
    assert col.data_scale == 2
