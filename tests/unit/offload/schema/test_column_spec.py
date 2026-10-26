# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe.offload.schema.column_spec."""

import pytest

from goe.offload.schema.column_spec import (
    GOE_TYPE_BINARY,
    GOE_TYPE_BOOLEAN,
    GOE_TYPE_DATE,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_FLOAT,
    GOE_TYPE_INTEGER_2,
    GOE_TYPE_TIME,
    GOE_TYPE_VARIABLE_STRING,
    SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
    ColumnSpecError,
    get_column_names,
    get_partition_columns,
    is_synthetic_partition_column,
    match_partition_column_by_source,
    match_table_column,
    match_table_column_position,
    regex_real_column_from_part_column,
    valid_column_list,
)
from tests.unit.offload.schema.type_mapping_cases import (
    EXPECTED_FIELDS,
    EXPECTED_NORMALIZED,
    EXPECTED_TRAITS,
    SYNTHETIC_NAME_CASES,
    TRAIT_INPUTS,
    TRAIT_METHODS,
    ColumnCase,
)

TRAIT_CASES_BY_KEY: dict[tuple[str, str], ColumnCase] = {
    (dialect_key, case[0]): case for dialect_key, cases in TRAIT_INPUTS.items() for case in cases
}

SYNTHETIC_CASES_BY_ID = {case[0]: case for case in SYNTHETIC_NAME_CASES}


@pytest.mark.parametrize(
    ("dialect_key", "name"),
    [(d, n) for d, by_name in EXPECTED_TRAITS.items() for n in by_name],
)
def test_traits_match_golden(dialect_key: str, name: str) -> None:
    spec = _build(dialect_key, TRAIT_CASES_BY_KEY[(dialect_key, name)])
    expected = EXPECTED_TRAITS[dialect_key][name]
    actual = tuple(_call(spec, m, exp) for m, exp in zip(TRAIT_METHODS, expected, strict=True))
    assert actual == expected


@pytest.mark.parametrize(
    ("dialect_key", "name"),
    [(d, n) for d, by_name in EXPECTED_NORMALIZED.items() for n in by_name],
)
def test_normalization_matches_golden(dialect_key: str, name: str) -> None:
    spec = _build(dialect_key, TRAIT_CASES_BY_KEY[(dialect_key, name)])
    expected = EXPECTED_NORMALIZED[dialect_key][name]
    actual = tuple(getattr(spec, f) for f in EXPECTED_FIELDS) + (
        spec.hidden,
        spec.collation,
        spec.from_override,
    )
    assert actual == expected


@pytest.mark.parametrize("case_id", [c[0] for c in SYNTHETIC_NAME_CASES])
def test_synthetic_name_matches_golden(case_id: str) -> None:
    _, part_attrs, col_cases, kw_attrs, expected = SYNTHETIC_CASES_BY_ID[case_id]
    part_spec = ColumnPartitionSpec(**dict(part_attrs))
    cols = [_build("canonical", c) for c in col_cases]
    kwargs = dict(kw_attrs)
    assert part_spec.synthetic_name(cols, **kwargs) == expected


def test_column_spec_is_frozen() -> None:
    spec = ColumnSpec(ColumnDialect.CANONICAL, "C", GOE_TYPE_VARIABLE_STRING)
    with pytest.raises(AttributeError):
        spec.nullable = False


def test_replace_preserves_explicit_values() -> None:
    base = ColumnSpec(ColumnDialect.BIGQUERY, "C", "STRING")
    assert base.replace(char_semantics="UNICODE").char_semantics == "UNICODE"
    replaced = base.replace(nullable=False)
    assert replaced.nullable is False
    assert replaced.name == base.name
    assert replaced.data_type == base.data_type
    assert replaced.char_semantics == base.char_semantics


def test_replace_is_idempotent_for_normalized_types() -> None:
    spec = ColumnSpec(ColumnDialect.ORACLE, "TS", "TIMESTAMP(3)", data_scale=3)
    renamed = spec.replace(name="TS_NEW")
    assert renamed.name == "TS_NEW"
    assert renamed.data_type == "TIMESTAMP"
    assert renamed.data_scale == 3


def test_with_simplified_staging_column_name() -> None:
    special = ColumnSpec(ColumnDialect.PARQUET, "COL WITH SPACE", "STRING")
    updated = special.with_simplified_staging_column_name(4)
    assert updated.staging_file_column_name == "_GOE_SPECIAL_CHAR_COLUMN_4"
    assert special.staging_file_column_name is None

    plain = ColumnSpec(ColumnDialect.PARQUET, "PLAIN_COL", "STRING")
    updated_plain = plain.with_simplified_staging_column_name(2)
    assert updated_plain.staging_file_column_name == "PLAIN_COL"
    assert plain.staging_file_column_name is None


def test_invalid_char_semantics_raises() -> None:
    with pytest.raises(ColumnSpecError):
        ColumnSpec(ColumnDialect.CANONICAL, "C", "VARIABLE_STRING", char_semantics="WORD")


def test_invalid_boolean_raises() -> None:
    with pytest.raises(ColumnSpecError):
        ColumnSpec(ColumnDialect.CANONICAL, "C", "VARIABLE_STRING", nullable="MAYBE")


def test_get_column_names() -> None:
    cols = _sample_canonical_columns()
    names = get_column_names(cols)
    assert isinstance(names, list)
    assert isinstance(names[0], str)
    assert get_column_names(cols, conv_fn=str.upper)[0] == names[0].upper()
    assert get_column_names(cols, conv_fn=str.lower)[0] == names[0].lower()


def test_get_partition_columns() -> None:
    cols = _sample_canonical_columns()
    part_cols = get_partition_columns(cols)
    assert isinstance(part_cols, list)
    assert isinstance(match_table_column("NATIVE_PART_COL", part_cols), ColumnSpec)
    assert match_table_column("COL_COST", part_cols) is None


def test_is_synthetic_partition_column() -> None:
    valid_Pairs = [
        ("goe_part_y_time_id", "time_id"),
        ("goe_part_m_time_id", "time_id"),
        ("goe_part_d_time_id", "time_id"),
        ("goe_part_m_h1_time_id", "h1_time_id"),
        ("goe_part_000000000000001_time_year", "time_year"),
        ("goe_part_000000000000001_time_month", "time_month"),
        ("goe_part_1_yrmon", "yrmon"),
        ("goe_part_6_yrmon", "yrmon"),
        ("goe_part_000000000000001_yrmon", "yrmon"),
        ("GOE_PART_0000000100_TIME_ID", "TIME_ID"),
        ("GOE_PART_100_TIME_ID", "TIME_ID"),
        ("GOE_PART_1000_PROD_LIST_PRICE", "PROD_LIST_PRICE"),
        ("goe_part_00001000_prod_list_price", "PROD_LIST_PRICE"),
        ("goe_part_000000000001000_id", "id"),
        (
            "goe_part_000000000000001_this_part_column_name_is_long_100_123456789012345678901234567890123456789012345678901234567890123456",
            "this_part_column_name_is_long_100_123456789012345678901234567890123456789012345678901234567890123456",
        ),
        ("goe_part_000000000100000_id", "id"),
        ("goe_part_00000010_prod_id", "prod_id"),
        ("goe_part_1_prod_category_desc", "prod_category_desc"),
        ("goe_part_m_dt", "dt"),
        ("goe_part_y_dt", "dt"),
        ("GOE_PART_100000000000000000_PART_COL", "PART_COL"),
        ("goe_part_u0_time_id", "time_id"),
        ("goe_part_u3_time_id", "time_id"),
    ]
    for synth_name, expected_source_name in valid_Pairs:
        assert is_synthetic_partition_column(synth_name.upper())
        assert is_synthetic_partition_column(synth_name.lower())
        match = regex_real_column_from_part_column(synth_name)
        assert match is not None
        assert match.group(3).upper() == expected_source_name.upper()

    for invalid_name in [
        "time_id",
        "goe_part_p_time_id",
        "goe_part_-1_time_idgoe_part_year_time_id",
        "goe_part_month_time_id",
        "goe_part_day_time_id",
        "goe_part_U_time_id",
        "goe_part_1U_time_id",
        "goe_part_U__time_id",
    ]:
        assert not is_synthetic_partition_column(invalid_name)


def test_match_table_column() -> None:
    cols = _sample_canonical_columns()
    assert isinstance(match_table_column("iD", cols), ColumnSpec)
    assert match_table_column("not_a_column", cols) is None


def test_match_partition_column_by_source() -> None:
    cols = _sample_canonical_columns()
    part_col = match_partition_column_by_source("col_name", cols)
    assert isinstance(part_col, ColumnSpec)
    assert part_col.name == SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE % ("1", "COL_NAME")
    assert match_partition_column_by_source("not_a_column", cols) is None
    assert match_partition_column_by_source("COL_BOOL", cols) is None


def test_match_table_column_position() -> None:
    cols = _sample_canonical_columns()
    assert match_table_column_position("iD", cols) == 0
    assert match_table_column_position("not_a_column", cols) is None


def test_valid_column_list() -> None:
    cols = _sample_canonical_columns()
    assert valid_column_list(cols)
    assert not valid_column_list(None)
    assert not valid_column_list([1, 2, 3])
    assert not valid_column_list(object())


def _build(dialect_key: str, case: ColumnCase) -> ColumnSpec:
    name, data_type, attrs = case
    kwargs = dict(attrs)
    if "partition_info" in kwargs and kwargs["partition_info"] is not None:
        raw_part = kwargs["partition_info"]
        if not isinstance(raw_part, ColumnPartitionSpec):
            kwargs["partition_info"] = ColumnPartitionSpec(**dict(raw_part))
    return ColumnSpec(ColumnDialect(dialect_key), name, data_type, **kwargs)


def _call(obj: ColumnSpec, method: str, expected: object) -> object:
    try:
        return getattr(obj, method)()
    except ColumnSpecError:
        if expected == "raises:NotImplementedError":
            return "raises:NotImplementedError"
        return "raises:ColumnSpecError"
    except Exception as exc:
        return f"raises:{type(exc).__name__}"


def _sample_canonical_columns() -> list[ColumnSpec]:
    return [
        ColumnSpec(ColumnDialect.CANONICAL, "ID", GOE_TYPE_INTEGER_2),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_NAME", GOE_TYPE_VARIABLE_STRING),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_DATA", GOE_TYPE_BINARY),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_OTHER_ID", GOE_TYPE_INTEGER_2),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_COST", GOE_TYPE_DECIMAL, data_precision=10, data_scale=2),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_RATE", GOE_TYPE_FLOAT),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_DATE", GOE_TYPE_DATE),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_TIME", GOE_TYPE_TIME),
        ColumnSpec(ColumnDialect.CANONICAL, "COL_BOOL", GOE_TYPE_BOOLEAN),
        ColumnSpec(
            ColumnDialect.CANONICAL,
            SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE % ("M", "COL_DATE"),
            GOE_TYPE_VARIABLE_STRING,
            partition_info=ColumnPartitionSpec(0, source_column_name="COL_DATE", granularity="M"),
        ),
        ColumnSpec(
            ColumnDialect.CANONICAL,
            SYNTHETIC_PARTITION_COLUMN_NAME_TEMPLATE % ("1", "COL_NAME"),
            GOE_TYPE_VARIABLE_STRING,
            partition_info=ColumnPartitionSpec(1, source_column_name="COL_NAME", granularity="1"),
        ),
        ColumnSpec(
            ColumnDialect.CANONICAL,
            "NATIVE_PART_COL",
            GOE_TYPE_INTEGER_2,
            partition_info=ColumnPartitionSpec(2),
        ),
    ]
