# SPDX-FileCopyrightText: 2024 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from typing import TYPE_CHECKING
from unittest import mock

import pytest

from goe.offload.offload_messages import OffloadMessages
from goe.offload.operation import table_structure_checks as module_under_test
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    BIGQUERY_TYPE_TIME,
    BIGQUERY_TYPE_TIMESTAMP,
    GOE_TYPE_INTEGER_1,
    ORACLE_TYPE_CLOB,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_NVARCHAR2,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_VARCHAR2,
    ColumnDialect,
    ColumnSpec,
)
from tests.unit.test_functions import (
    FAKE_ORACLE_BQ_ENV,
    build_fake_backend_table,
    build_fake_oracle_table,
    build_mock_options,
)

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig


@pytest.fixture(scope="module")
def ora_bq_config() -> "OrchestrationConfig":
    return build_mock_options(FAKE_ORACLE_BQ_ENV)


@pytest.fixture(scope="module")
def messages():
    return OffloadMessages()


@pytest.fixture
def bigquery_table(ora_bq_config, messages):
    return build_fake_backend_table(ora_bq_config, messages)


@pytest.fixture
def oracle_table(ora_bq_config, messages):
    return build_fake_oracle_table(ora_bq_config, messages)


@pytest.mark.parametrize(
    "frontend_columns,backend_columns,expected_extra_frontend_names,expected_missing_frontend_names",
    [
        # Happy path, no expected mismatches.
        (
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "col_2", GOE_TYPE_INTEGER_1),
            ],
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "col_2", GOE_TYPE_INTEGER_1),
            ],
            [],
            [],
        ),
        # Happy path with different case, no expected mismatches.
        (
            [
                ColumnSpec(ColumnDialect.CANONICAL, "Col_1", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "COL_2", GOE_TYPE_INTEGER_1),
            ],
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "cOl_2", GOE_TYPE_INTEGER_1),
            ],
            [],
            [],
        ),
        # Missing backend column.
        (
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "col_2", GOE_TYPE_INTEGER_1),
            ],
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
            ],
            ["COL_2"],
            [],
        ),
        # Missing frontend column.
        (
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
            ],
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "col_2", GOE_TYPE_INTEGER_1),
            ],
            [],
            ["COL_2"],
        ),
        # Missing backend columns.
        (
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "col_2", GOE_TYPE_INTEGER_1),
                ColumnSpec(ColumnDialect.CANONICAL, "col_3", GOE_TYPE_INTEGER_1),
            ],
            [
                ColumnSpec(ColumnDialect.CANONICAL, "col_1", GOE_TYPE_INTEGER_1),
            ],
            ["COL_2", "COL_3"],
            [],
        ),
    ],
)
def test_check_table_columns_by_name(
    frontend_columns: list,
    backend_columns: list,
    expected_extra_frontend_names: list,
    expected_missing_frontend_names: list,
):
    extra_frontend_names, missing_frontend_names = module_under_test.check_table_columns_by_name(
        frontend_columns, backend_columns
    )
    assert extra_frontend_names == expected_extra_frontend_names
    assert missing_frontend_names == expected_missing_frontend_names


@pytest.mark.parametrize(
    "extra_frontend_names,missing_frontend_names",
    [
        (
            [],
            [],
        ),
        # Missing backend column.
        (
            ["COL_2"],
            [],
        ),
        # Missing frontend column.
        (
            [],
            ["COL_2"],
        ),
        # Missing backend columns.
        (
            ["COL_2", "COL_3"],
            [],
        ),
    ],
)
def test_check_table_columns_by_name_logging(extra_frontend_names: list, missing_frontend_names: list, messages):
    fake_table = mock.MagicMock()
    fake_table.frontend_db_name = lambda: "System A"
    fake_table.backend_db_name = lambda: "System B"
    module_under_test.check_table_columns_by_name_logging(
        fake_table, fake_table, extra_frontend_names, missing_frontend_names, messages
    )


@pytest.mark.parametrize(
    "frontend_columns,backend_columns,expected_return_dict",
    [
        # Happy path, no expected mismatches.
        (
            [
                ColumnSpec(ColumnDialect.ORACLE, "COL_N1", ORACLE_TYPE_NUMBER),
                ColumnSpec(ColumnDialect.ORACLE, "COL_N2", ORACLE_TYPE_NUMBER),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S1", ORACLE_TYPE_VARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_D1", ORACLE_TYPE_DATE),
                ColumnSpec(ColumnDialect.ORACLE, "COL_D2", ORACLE_TYPE_DATE),
                ColumnSpec(ColumnDialect.ORACLE, "COL_D3", ORACLE_TYPE_DATE),
                ColumnSpec(ColumnDialect.ORACLE, "COL_T1", ORACLE_TYPE_TIMESTAMP),
                ColumnSpec(ColumnDialect.ORACLE, "COL_T2", ORACLE_TYPE_TIMESTAMP),
                ColumnSpec(ColumnDialect.ORACLE, "COL_T3", ORACLE_TYPE_TIMESTAMP),
            ],
            [
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_N1", BIGQUERY_TYPE_NUMERIC),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_N2", BIGQUERY_TYPE_INT64),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S1", BIGQUERY_TYPE_STRING),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_D1", BIGQUERY_TYPE_DATE),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_D2", BIGQUERY_TYPE_DATETIME),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_D3", BIGQUERY_TYPE_TIMESTAMP),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_T1", BIGQUERY_TYPE_DATE),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_T2", BIGQUERY_TYPE_DATETIME),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_T3", BIGQUERY_TYPE_TIMESTAMP),
            ],
            {},
        ),
        # Dates to strings.
        (
            [
                ColumnSpec(ColumnDialect.ORACLE, "COL_D1", ORACLE_TYPE_DATE),
                ColumnSpec(ColumnDialect.ORACLE, "COL_T1", ORACLE_TYPE_TIMESTAMP),
            ],
            [
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_D1", BIGQUERY_TYPE_STRING),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_T1", BIGQUERY_TYPE_STRING),
            ],
            {},
        ),
        # Numbers to strings is not currently supported.
        (
            [
                ColumnSpec(ColumnDialect.ORACLE, "COL_N1", ORACLE_TYPE_NUMBER),
                ColumnSpec(ColumnDialect.ORACLE, "COL_N2", ORACLE_TYPE_NUMBER),
            ],
            [
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_N1", BIGQUERY_TYPE_NUMERIC),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_N2", BIGQUERY_TYPE_STRING),
            ],
            {
                "COL_N2": BIGQUERY_TYPE_STRING,
            },
        ),
        # Strings to numbers is not currently supported.
        (
            [
                ColumnSpec(ColumnDialect.ORACLE, "COL_S1", ORACLE_TYPE_VARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S2", ORACLE_TYPE_VARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S3", ORACLE_TYPE_NVARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S4", ORACLE_TYPE_CLOB),
            ],
            [
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S1", BIGQUERY_TYPE_STRING),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S2", BIGQUERY_TYPE_NUMERIC),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S3", BIGQUERY_TYPE_BIGNUMERIC),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S4", BIGQUERY_TYPE_NUMERIC),
            ],
            {
                "COL_S2": BIGQUERY_TYPE_NUMERIC,
                "COL_S3": BIGQUERY_TYPE_BIGNUMERIC,
                "COL_S4": BIGQUERY_TYPE_NUMERIC,
            },
        ),
        # Strings to dates is not currently supported.
        (
            [
                ColumnSpec(ColumnDialect.ORACLE, "COL_S1", ORACLE_TYPE_VARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S2", ORACLE_TYPE_VARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S3", ORACLE_TYPE_NVARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S4", ORACLE_TYPE_CLOB),
            ],
            [
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S1", BIGQUERY_TYPE_STRING),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S2", BIGQUERY_TYPE_DATE),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S3", BIGQUERY_TYPE_DATETIME),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S4", BIGQUERY_TYPE_TIMESTAMP),
            ],
            {
                "COL_S2": BIGQUERY_TYPE_DATE,
                "COL_S3": BIGQUERY_TYPE_DATETIME,
                "COL_S4": BIGQUERY_TYPE_TIMESTAMP,
            },
        ),
        # Backend TIME is not supported.
        (
            [
                ColumnSpec(ColumnDialect.ORACLE, "COL_N1", ORACLE_TYPE_NUMBER),
                ColumnSpec(ColumnDialect.ORACLE, "COL_N2", ORACLE_TYPE_NUMBER),
                ColumnSpec(ColumnDialect.ORACLE, "COL_S1", ORACLE_TYPE_VARCHAR2),
                ColumnSpec(ColumnDialect.ORACLE, "COL_D1", ORACLE_TYPE_DATE),
                ColumnSpec(ColumnDialect.ORACLE, "COL_T1", ORACLE_TYPE_TIMESTAMP),
            ],
            [
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_N1", BIGQUERY_TYPE_NUMERIC),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_N2", BIGQUERY_TYPE_TIME),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_S1", BIGQUERY_TYPE_TIME),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_D1", BIGQUERY_TYPE_TIME),
                ColumnSpec(ColumnDialect.BIGQUERY, "COL_T1", BIGQUERY_TYPE_TIME),
            ],
            {
                "COL_N2": BIGQUERY_TYPE_TIME,
                "COL_S1": BIGQUERY_TYPE_TIME,
                "COL_D1": BIGQUERY_TYPE_TIME,
                "COL_T1": BIGQUERY_TYPE_TIME,
            },
        ),
    ],
)
def test_check_table_columns_by_type_oracle_to_bigquery(
    frontend_columns: list,
    backend_columns: list,
    expected_return_dict: dict,
    oracle_table,
    bigquery_table,
):
    oracle_table._columns = frontend_columns
    oracle_table._columns_with_partition_info = frontend_columns
    bigquery_table._columns = backend_columns
    result = module_under_test.check_table_columns_by_type(oracle_table, bigquery_table)
    assert result == expected_return_dict


@pytest.mark.parametrize(
    "invalid_combinations",
    [
        {},
        {
            "COL_N2": BIGQUERY_TYPE_TIME,
            "COL_S1": BIGQUERY_TYPE_TIME,
            "COL_D1": BIGQUERY_TYPE_TIME,
            "COL_T1": BIGQUERY_TYPE_TIME,
        },
    ],
)
def test_check_table_columns_by_type_logging(invalid_combinations: dict, messages):
    fake_table = mock.MagicMock()
    fake_table.frontend_db_name = lambda: "System A"
    fake_table.backend_db_name = lambda: "System B"
    fake_table.get_column = lambda x: ColumnSpec(ColumnDialect.CANONICAL, "COL-NAME", GOE_TYPE_INTEGER_1)
    module_under_test.check_table_columns_by_type_logging(fake_table, fake_table, invalid_combinations, messages)
