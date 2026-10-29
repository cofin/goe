# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Listener OffloadOptions, ListenerConfig, and ColumnDetail schema alignment."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from litestar.di import Provide
from litestar.testing import TestClient

from goe.config.options import (
    EXPECTED_OFFLOAD_ARGS,
    LISTENER_OFFLOAD_CSV_ALIASES,
    LISTENER_OFFLOAD_RENAME_ALIASES,
    OffloadOperationOptions,
)
from goe.listener.app import create_app
from goe.listener.jobs.store import SqliteJobStore
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
def test_orchestration_post_offload_passes_only_expected_offload_args(
    mock_check: MagicMock,
    tmp_path: Path,
) -> None:
    """Verify POST /api/orchestration/offload/ passes only EXPECTED_OFFLOAD_ARGS keys to JobStore.enqueue."""
    store = SqliteJobStore(db_path=tmp_path / "jobs.sqlite3")
    app = create_app(
        dependencies={"job_store": Provide(lambda: store, sync_to_thread=False)},
        enable_background_worker=False,
    )
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
        exec_id = response.json()["execution_id"]

    job = store.get_job_by_execution_id(exec_id)
    assert job is not None
    passed_params = job.decode_payload()
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


def test_offload_options_fields_track_expected_offload_args() -> None:
    """Listener REST fields equal the canonical offload keys plus documented aliases."""
    alias_fields = set(LISTENER_OFFLOAD_RENAME_ALIASES) | set(LISTENER_OFFLOAD_CSV_ALIASES) | {"subpartitions"}
    rest_fields = set(OffloadOptions.__struct_fields__) - alias_fields - {"confirmation_token", "quiet", "verbose"}
    assert rest_fields == set(EXPECTED_OFFLOAD_ARGS) - {"operation_name"}


def test_offload_options_to_operation_options_hydrates_canonical_defaults() -> None:
    """OffloadOptions.to_operation_options() hydrates unset fields from OffloadOperationOptions while preserving REST execute=True."""
    opts = OffloadOptions(owner_table="SH.SALES", replace_hybrid_view=True)
    op_opts = opts.to_operation_options()
    assert isinstance(op_opts, OffloadOperationOptions)
    assert op_opts.owner_table == "SH.SALES"
    assert op_opts.execute is True
    assert op_opts.reset_hybrid_view is True
    assert op_opts.reset_backend_table is False
    assert op_opts.reuse_backend_table is False
    assert op_opts.force is False
