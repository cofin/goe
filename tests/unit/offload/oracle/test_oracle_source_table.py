# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OracleSourceTable snapshot hydration and Arrow batch sampling."""

from __future__ import annotations

import datetime
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import numpy as np

from goe.offload.oracle.catalog import (
    OracleColumnMeta,
    OracleConstraintMeta,
    OraclePartitionMeta,
    OracleSessionContext,
    OracleStorageStats,
    OracleSubpartitionMeta,
    OracleTableSnapshot,
)
from goe.offload.oracle.oracle_offload_source_table import OracleSourceTable
from goe.offload.schema.column_spec import ORACLE_TYPE_NUMBER, ColumnDialect, ColumnSpec


class _DummyMessages:
    def log(self, *args: Any, **kwargs: Any) -> None:
        pass

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def notice(self, *args: Any, **kwargs: Any) -> None:
        pass


class _StubFrontendApi:
    def __init__(self, snapshot: OracleTableSnapshot, arrow_driver: Any = None) -> None:
        self._snapshot = snapshot
        self._arrow_driver = arrow_driver
        self.snapshot_calls = 0

    def get_session_context(self) -> OracleSessionContext:
        return OracleSessionContext(
            version="23.4.0.24.05",
            db_unique_name="FREE",
            current_scn=99999,
            compatible="23.0.0",
            db_block_size=8192,
            max_string_size="STANDARD",
            cell_offload_processing=False,
            current_user="GOE_ADM",
        )

    def get_table_snapshot(self, owner: str, table_name: str, *, force_refresh: bool = False) -> OracleTableSnapshot:
        self.snapshot_calls += 1
        return self._snapshot

    def frontend_version(self) -> str:
        return "23.4.0.24.05"

    def get_session_option(self, name: str) -> str:
        if name.lower() == "db_block_size":
            return "8192"
        return "23.0.0"

    def enclose_identifier(self, val: str) -> str:
        return f'"{val}"'

    def generic_string_data_type(self) -> str:
        return "VARCHAR2"

    def max_datetime_scale(self) -> int:
        return 9

    def min_datetime_value(self) -> np.datetime64:
        return np.datetime64("-4712-01-01")

    def max_datetime_value(self) -> np.datetime64:
        return np.datetime64("9999-12-31")

    def parallel_query_hint(self, query_parallelism: Any) -> str:
        return f"PARALLEL({query_parallelism})" if query_parallelism and query_parallelism > 1 else ""

    def enclose_query_hints(self, hint_contents: Any) -> str:
        return f"/*+ {hint_contents} */" if hint_contents else ""

    def split_partition_high_value_string(self, hv_string: str) -> list[str]:
        return [hv_string] if hv_string else []

    def close(self) -> None:
        pass

    @property
    def registry(self) -> Any:
        driver = self._arrow_driver

        class _Reg:
            @contextmanager
            def adm_session(self) -> Any:
                yield driver

        return _Reg()


def test_oracle_source_table_hydrates_from_snapshot() -> None:
    snap = _sample_snapshot()
    api = _StubFrontendApi(snap)
    table = OracleSourceTable(
        "sh",
        "sales",
        _dummy_options(),
        _DummyMessages(),
        db_api=api,
    )

    assert table.size_in_bytes == 163840
    assert table.stats_num_rows == 500
    assert len(table.columns) == 3
    assert table.get_primary_key_columns() == ["ID"]
    assert table.is_partitioned() is True
    assert table.partition_type == "RANGE"
    assert [c.name for c in table.partition_columns] == ["SALE_DATE"]
    assert len(table.get_partitions()) == 1
    assert table.get_partitions()[0].partition_name == "P_2025"
    assert table.get_subpartitions()[0].subpartition_name == "P_2025_US"
    assert api.snapshot_calls == 1


def test_oracle_source_table_literal_parsers_handle_decimals_and_timestamps() -> None:
    assert OracleSourceTable.numeric_literal_to_python("42.5") == Decimal("42.5")
    assert OracleSourceTable.datetime_literal_to_python(
        "TO_DATE(' 2026-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')"
    ) == np.datetime64(datetime.datetime(2026, 1, 1, 0, 0, 0))


def test_oracle_source_table_arrow_batch_sampling_for_unknown_number() -> None:
    class _ArrowDriver:
        def select_to_arrow(self, sql: str, params: Any = None, **kwargs: Any) -> list[Any]:
            assert kwargs.get("return_format") == "batches"
            return [{"AMOUNT": [Decimal("12.34"), Decimal("-9999.5"), None, Decimal("0")]}]

    snap = _sample_snapshot()
    api = _StubFrontendApi(snap, arrow_driver=_ArrowDriver())
    table = OracleSourceTable(
        "sh",
        "sales",
        _dummy_options(),
        _DummyMessages(),
        db_api=api,
    )

    amount_col = ColumnSpec(ColumnDialect.ORACLE, "AMOUNT", ORACLE_TYPE_NUMBER, nullable="Y")
    sampled = table.sample_rdbms_data_types(
        [amount_col],
        data_sample_pct=10,
        data_sample_parallelism=2,
        backend_min_possible_date=datetime.date(1, 1, 1),
        backend_max_decimal_integral_magnitude=38,
        backend_max_decimal_scale=18,
        allow_decimal_scale_rounding=True,
    )
    assert len(sampled) == 1
    assert sampled[0].data_precision == 6
    assert sampled[0].data_scale == 2


def _sample_snapshot() -> OracleTableSnapshot:
    return OracleTableSnapshot(
        owner="SH",
        table_name="SALES",
        iot_type=None,
        partitioned=True,
        partitioning_type="RANGE",
        subpartitioning_type="LIST",
        degree="4",
        compression="ENABLED",
        compress_for="QUERY HIGH",
        stats=OracleStorageStats(num_rows=500, blocks=20, avg_row_len=40, size_in_bytes=163840),
        columns=(
            OracleColumnMeta(
                column_id=1,
                name="ID",
                data_type="NUMBER",
                data_length=22,
                data_precision=10,
                data_scale=0,
                nullable=False,
                low_value=Decimal(1),
                high_value=Decimal(500),
            ),
            OracleColumnMeta(
                column_id=2,
                name="SALE_DATE",
                data_type="DATE",
                data_length=7,
                nullable=False,
                partition_position=1,
                low_value=datetime.datetime(2025, 1, 1, 0, 0, 0),
                high_value=datetime.datetime(2025, 12, 31, 0, 0, 0),
            ),
            OracleColumnMeta(
                column_id=3,
                name="REGION",
                data_type="VARCHAR2",
                data_length=10,
                char_length=10,
                char_used="B",
                nullable=True,
                subpartition_position=1,
            ),
        ),
        constraints=(
            OracleConstraintMeta(
                constraint_name="PK_SALES",
                constraint_type="P",
                status="ENABLED",
                validated="VALIDATED",
                column_names=("ID",),
            ),
        ),
        indexes=(),
        partitions=(
            OraclePartitionMeta(
                partition_name="P_2025",
                partition_position=1,
                high_value_csv="TO_DATE(' 2026-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')",
                high_value_literals=(datetime.datetime(2026, 1, 1, 0, 0, 0),),
                subpartition_count=1,
                num_rows=500,
                blocks=20,
                avg_row_len=40,
                size_in_bytes=163840,
                subpartitions=(
                    OracleSubpartitionMeta(
                        partition_name="P_2025",
                        partition_position=1,
                        subpartition_name="P_2025_US",
                        subpartition_position=1,
                        high_value_csv="'US'",
                        high_value_literals=("US",),
                        num_rows=500,
                        blocks=20,
                        avg_row_len=40,
                        size_in_bytes=163840,
                    ),
                ),
            ),
        ),
        subpartitions=(
            OracleSubpartitionMeta(
                partition_name="P_2025",
                partition_position=1,
                subpartition_name="P_2025_US",
                subpartition_position=1,
                high_value_csv="'US'",
                high_value_literals=("US",),
                num_rows=500,
                blocks=20,
                avg_row_len=40,
                size_in_bytes=163840,
            ),
        ),
    )


def _dummy_options() -> Any:
    return SimpleNamespace(
        db_type="oracle",
        ora_adm_user="GOE_ADM",
        ora_adm_pass="secret",
        ora_app_user="GOE_APP",
        ora_app_pass="secret",
        rdbms_dsn="ora-dsn",
        use_oracle_wallet=False,
    )
