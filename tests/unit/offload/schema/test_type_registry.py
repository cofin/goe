# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for goe.offload.schema.type_registry."""

import pytest

from goe.offload.schema.column_spec import (
    ALL_CANONICAL_TYPES,
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_BOOLEAN,
    BIGQUERY_TYPE_BYTES,
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_FLOAT64,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    BIGQUERY_TYPE_TIME,
    BIGQUERY_TYPE_TIMESTAMP,
    GOE_TYPE_DATE,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_VARIABLE_STRING,
    HADOOP_TYPE_BIGINT,
    HADOOP_TYPE_BINARY,
    HADOOP_TYPE_BOOLEAN,
    HADOOP_TYPE_CHAR,
    HADOOP_TYPE_DATE,
    HADOOP_TYPE_DECIMAL,
    HADOOP_TYPE_DOUBLE,
    HADOOP_TYPE_DOUBLE_PRECISION,
    HADOOP_TYPE_FLOAT,
    HADOOP_TYPE_INT,
    HADOOP_TYPE_INTERVAL_DS,
    HADOOP_TYPE_INTERVAL_YM,
    HADOOP_TYPE_REAL,
    HADOOP_TYPE_SMALLINT,
    HADOOP_TYPE_STRING,
    HADOOP_TYPE_TIMESTAMP,
    HADOOP_TYPE_TINYINT,
    HADOOP_TYPE_VARCHAR,
    SNOWFLAKE_TYPE_BINARY,
    SNOWFLAKE_TYPE_DATE,
    SNOWFLAKE_TYPE_FLOAT,
    SNOWFLAKE_TYPE_NUMBER,
    SNOWFLAKE_TYPE_TEXT,
    SNOWFLAKE_TYPE_TIME,
    SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
    SNOWFLAKE_TYPE_TIMESTAMP_TZ,
    SYNAPSE_TYPE_BIGINT,
    SYNAPSE_TYPE_BINARY,
    SYNAPSE_TYPE_CHAR,
    SYNAPSE_TYPE_DATE,
    SYNAPSE_TYPE_DATETIME,
    SYNAPSE_TYPE_DATETIME2,
    SYNAPSE_TYPE_DATETIMEOFFSET,
    SYNAPSE_TYPE_DECIMAL,
    SYNAPSE_TYPE_FLOAT,
    SYNAPSE_TYPE_INT,
    SYNAPSE_TYPE_MONEY,
    SYNAPSE_TYPE_NCHAR,
    SYNAPSE_TYPE_NUMERIC,
    SYNAPSE_TYPE_NVARCHAR,
    SYNAPSE_TYPE_REAL,
    SYNAPSE_TYPE_SMALLDATETIME,
    SYNAPSE_TYPE_SMALLINT,
    SYNAPSE_TYPE_SMALLMONEY,
    SYNAPSE_TYPE_TIME,
    SYNAPSE_TYPE_TINYINT,
    SYNAPSE_TYPE_UNIQUEIDENTIFIER,
    SYNAPSE_TYPE_VARBINARY,
    SYNAPSE_TYPE_VARCHAR,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
    ColumnSpecError,
)
from goe.offload.schema.type_registry import (
    FROM_CANONICAL_RULES,
    TYPE_REGISTRY,
    MappingContext,
    MappingTarget,
    TypeMappingLimits,
)
from tests.unit.offload.schema.type_mapping_cases import (
    CANONICAL_INPUTS,
    EXPECTED_FIELDS,
    EXPECTED_FROM_CANONICAL,
    EXPECTED_LIMITS,
    EXPECTED_OVERRIDES,
    EXPECTED_TO_CANONICAL,
    SOURCE_INPUTS,
    UNKNOWN_CANONICAL_TYPE,
    ColumnCase,
)

SUPPORTED_BACKEND_TYPES: dict[str, frozenset[str]] = {
    "bigquery": frozenset(
        {
            BIGQUERY_TYPE_BIGNUMERIC,
            BIGQUERY_TYPE_BOOLEAN,
            BIGQUERY_TYPE_BYTES,
            BIGQUERY_TYPE_DATE,
            BIGQUERY_TYPE_DATETIME,
            BIGQUERY_TYPE_FLOAT64,
            BIGQUERY_TYPE_INT64,
            BIGQUERY_TYPE_NUMERIC,
            BIGQUERY_TYPE_STRING,
            BIGQUERY_TYPE_TIME,
            BIGQUERY_TYPE_TIMESTAMP,
        }
    ),
    "snowflake": frozenset(
        {
            SNOWFLAKE_TYPE_BINARY,
            SNOWFLAKE_TYPE_DATE,
            SNOWFLAKE_TYPE_FLOAT,
            SNOWFLAKE_TYPE_NUMBER,
            SNOWFLAKE_TYPE_TEXT,
            SNOWFLAKE_TYPE_TIME,
            SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
            SNOWFLAKE_TYPE_TIMESTAMP_TZ,
        }
    ),
    "synapse": frozenset(
        {
            SYNAPSE_TYPE_BIGINT,
            SYNAPSE_TYPE_DECIMAL,
            SYNAPSE_TYPE_FLOAT,
            SYNAPSE_TYPE_INT,
            SYNAPSE_TYPE_MONEY,
            SYNAPSE_TYPE_NUMERIC,
            SYNAPSE_TYPE_REAL,
            SYNAPSE_TYPE_SMALLINT,
            SYNAPSE_TYPE_SMALLMONEY,
            SYNAPSE_TYPE_TINYINT,
            SYNAPSE_TYPE_DATE,
            SYNAPSE_TYPE_DATETIME,
            SYNAPSE_TYPE_DATETIME2,
            SYNAPSE_TYPE_SMALLDATETIME,
            SYNAPSE_TYPE_DATETIMEOFFSET,
            SYNAPSE_TYPE_TIME,
            SYNAPSE_TYPE_CHAR,
            SYNAPSE_TYPE_VARCHAR,
            SYNAPSE_TYPE_NCHAR,
            SYNAPSE_TYPE_NVARCHAR,
            SYNAPSE_TYPE_BINARY,
            SYNAPSE_TYPE_UNIQUEIDENTIFIER,
            SYNAPSE_TYPE_VARBINARY,
        }
    ),
    "hive": frozenset(
        {
            HADOOP_TYPE_BOOLEAN,
            HADOOP_TYPE_BIGINT,
            HADOOP_TYPE_BINARY,
            HADOOP_TYPE_CHAR,
            HADOOP_TYPE_DATE,
            HADOOP_TYPE_DECIMAL,
            HADOOP_TYPE_DOUBLE,
            HADOOP_TYPE_DOUBLE_PRECISION,
            HADOOP_TYPE_FLOAT,
            HADOOP_TYPE_INT,
            HADOOP_TYPE_INTERVAL_DS,
            HADOOP_TYPE_INTERVAL_YM,
            HADOOP_TYPE_REAL,
            HADOOP_TYPE_STRING,
            HADOOP_TYPE_SMALLINT,
            HADOOP_TYPE_TIMESTAMP,
            HADOOP_TYPE_TINYINT,
            HADOOP_TYPE_VARCHAR,
        }
    ),
    "impala": frozenset(
        {
            HADOOP_TYPE_BOOLEAN,
            HADOOP_TYPE_BIGINT,
            HADOOP_TYPE_CHAR,
            HADOOP_TYPE_DECIMAL,
            HADOOP_TYPE_DOUBLE,
            HADOOP_TYPE_FLOAT,
            HADOOP_TYPE_INT,
            HADOOP_TYPE_REAL,
            HADOOP_TYPE_STRING,
            HADOOP_TYPE_SMALLINT,
            HADOOP_TYPE_TIMESTAMP,
            HADOOP_TYPE_TINYINT,
            HADOOP_TYPE_VARCHAR,
        }
    ),
}

CANONICAL_CASES_BY_NAME: dict[str, ColumnCase] = {case[0]: case for case in CANONICAL_INPUTS}
SOURCE_CASES_BY_KEY: dict[tuple[str, str], ColumnCase] = {
    (dialect_key, case[0]): case for dialect_key, cases in SOURCE_INPUTS.items() for case in cases
}


@pytest.mark.parametrize(
    ("source_key", "name"),
    [(sk, n) for sk, by_name in EXPECTED_TO_CANONICAL.items() for n in by_name],
)
def test_to_canonical_matches_golden(source_key: str, name: str) -> None:
    expected = EXPECTED_TO_CANONICAL[source_key][name]
    base_dialect = source_key.removesuffix("_base64")
    owner_key = "hive" if base_dialect == "hadoop" else base_dialect
    col = _build(base_dialect, SOURCE_CASES_BY_KEY[(base_dialect, name)])
    ctx = MappingContext(
        limits=_limits(owner_key),
        binary_as_base64=source_key.endswith("_base64"),
    )
    if base_dialect in ("parquet", "avro"):
        actual = _snap_to_canonical(lambda: TYPE_REGISTRY.staging_to_canonical(col, ctx), expected)
    else:
        actual = _snap_to_canonical(lambda: TYPE_REGISTRY.to_canonical(col, ctx), expected)
    assert actual == expected


@pytest.mark.parametrize(
    ("target_key", "name"),
    [(tk, n) for tk, by_name in EXPECTED_FROM_CANONICAL.items() for n in by_name],
)
def test_from_canonical_matches_golden(target_key: str, name: str) -> None:
    expected = EXPECTED_FROM_CANONICAL[target_key][name]
    col = _build("canonical", CANONICAL_CASES_BY_NAME[name])
    target, ctx = _resolve_target_and_context(target_key)
    actual = _snap_from_canonical(lambda: TYPE_REGISTRY.from_canonical(col, target, ctx), expected)
    assert actual == expected


@pytest.mark.parametrize(
    ("source_key", "data_type"),
    [(sk, dt) for sk, by_dt in EXPECTED_OVERRIDES.items() for dt in by_dt],
)
def test_overrides_match_golden(source_key: str, data_type: str) -> None:
    expected_allowed = EXPECTED_OVERRIDES[source_key][data_type]
    dialect_key = "hadoop" if source_key in ("hive", "impala") else source_key
    col = ColumnSpec(ColumnDialect(dialect_key), f"COL_{data_type}", data_type)
    ctx = MappingContext(limits=_limits(source_key))
    actual_allowed = tuple(
        sorted(
            cand
            for cand in (*ALL_CANONICAL_TYPES, UNKNOWN_CANONICAL_TYPE)
            if TYPE_REGISTRY.valid_canonical_override(col, cand, ctx)
        )
    )
    assert actual_allowed == expected_allowed


def test_synthetic_partition_column_types() -> None:
    part_info = ColumnPartitionSpec(position=0, source_column_name="SRC_COL", granularity="M")
    date_col = ColumnSpec(ColumnDialect.CANONICAL, "SRC_COL", GOE_TYPE_DATE, partition_info=part_info)
    num_col = ColumnSpec(ColumnDialect.CANONICAL, "SRC_COL", GOE_TYPE_INTEGER_8, partition_info=part_info)
    str_col = ColumnSpec(ColumnDialect.CANONICAL, "SRC_COL", GOE_TYPE_VARIABLE_STRING, partition_info=part_info)

    bq_date = TYPE_REGISTRY.synthetic_partition_column(date_col, "GOE_PART_M_SRC_COL", MappingTarget.BIGQUERY)
    assert bq_date.dialect is ColumnDialect.BIGQUERY
    assert bq_date.data_type == BIGQUERY_TYPE_DATE
    assert bq_date.partition_info == part_info

    bq_num = TYPE_REGISTRY.synthetic_partition_column(num_col, "GOE_PART_10_SRC_COL", MappingTarget.BIGQUERY)
    assert bq_num.dialect is ColumnDialect.BIGQUERY
    assert bq_num.data_type == BIGQUERY_TYPE_INT64
    assert bq_num.partition_info == part_info

    with pytest.raises(ColumnSpecError):
        TYPE_REGISTRY.synthetic_partition_column(str_col, "GOE_PART_1_SRC_COL", MappingTarget.BIGQUERY)

    for src in (date_col, num_col, str_col):
        hive_synth = TYPE_REGISTRY.synthetic_partition_column(src, "GOE_PART_X_SRC_COL", MappingTarget.HIVE)
        assert hive_synth.dialect is ColumnDialect.HADOOP
        assert hive_synth.data_type == HADOOP_TYPE_STRING
        assert hive_synth.partition_info == part_info

    for unsupported_target in (MappingTarget.SNOWFLAKE, MappingTarget.SYNAPSE):
        with pytest.raises(ColumnSpecError):
            TYPE_REGISTRY.synthetic_partition_column(date_col, "GOE_PART_M_SRC_COL", unsupported_target)


def test_default_numeric_columns() -> None:
    sf_ctx = MappingContext(limits=_limits("snowflake"))
    sf_col = TYPE_REGISTRY.default_numeric_column("AVG_COL", MappingTarget.SNOWFLAKE, sf_ctx)
    assert sf_col.dialect is ColumnDialect.SNOWFLAKE
    assert sf_col.format_data_type() == "NUMBER(38,18)"
    assert sf_col.nullable is True
    assert sf_col.safe_mapping is False

    syn_ctx = MappingContext(limits=_limits("synapse"))
    syn_col = TYPE_REGISTRY.default_numeric_column("AVG_COL", MappingTarget.SYNAPSE, syn_ctx)
    assert syn_col.dialect is ColumnDialect.SYNAPSE
    assert syn_col.format_data_type() == "numeric(38,18)"
    assert syn_col.nullable is True
    assert syn_col.safe_mapping is False

    hive_ctx = MappingContext(limits=_limits("hive"))
    hive_col = TYPE_REGISTRY.default_numeric_column("AVG_COL", MappingTarget.HIVE, hive_ctx)
    assert hive_col.dialect is ColumnDialect.HADOOP
    assert hive_col.format_data_type() == "DECIMAL(38,18)"
    assert hive_col.nullable is True
    assert hive_col.safe_mapping is False

    bq_ctx = MappingContext(limits=_limits("bigquery"))
    bq_int = TYPE_REGISTRY.default_numeric_column("AVG_COL", MappingTarget.BIGQUERY, bq_ctx, data_scale=0)
    assert bq_int.data_type == BIGQUERY_TYPE_INT64
    assert bq_int.nullable is True
    assert bq_int.safe_mapping is False

    bq_num = TYPE_REGISTRY.default_numeric_column("AVG_COL", MappingTarget.BIGQUERY, bq_ctx, data_scale=9)
    assert bq_num.format_data_type() == "NUMERIC(38,9)"
    assert bq_num.nullable is True
    assert bq_num.safe_mapping is False

    bq_bignum = TYPE_REGISTRY.default_numeric_column("AVG_COL", MappingTarget.BIGQUERY, bq_ctx)
    assert bq_bignum.format_data_type() == "BIGNUMERIC(76,38)"
    assert bq_bignum.nullable is True
    assert bq_bignum.safe_mapping is False


def test_log_callback_receives_unsafe_switch() -> None:
    logged: list[tuple[str, int]] = []
    col = ColumnSpec(
        ColumnDialect.CANONICAL,
        "COL_DEC_10_2_UNSAFE",
        GOE_TYPE_DECIMAL,
        data_precision=10,
        data_scale=2,
        safe_mapping=False,
    )
    ctx = MappingContext(
        limits=_limits("bigquery"),
        log=lambda msg, level: logged.append((msg, level)),
    )
    mapped = TYPE_REGISTRY.from_canonical(col, MappingTarget.BIGQUERY, ctx)
    assert mapped.data_type == BIGQUERY_TYPE_BIGNUMERIC
    assert any(msg == "Switching unsafe NUMERIC mapping to BIGNUMERIC: COL_DEC_10_2_UNSAFE" for msg, _ in logged)


def test_rule_tables_cover_every_canonical_type() -> None:
    for target in MappingTarget:
        if target is MappingTarget.MSSQL:
            continue
        rules = FROM_CANONICAL_RULES[target]
        covered = {dt for rule in rules for dt in rule.source_types}
        golden_key = target.value
        non_raising_types = {
            CANONICAL_CASES_BY_NAME[name][1]
            for name, exp in EXPECTED_FROM_CANONICAL[golden_key].items()
            if not (isinstance(exp, str) and exp.startswith("raises:"))
        }
        assert non_raising_types <= covered


def _build(dialect_key: str, case: ColumnCase) -> ColumnSpec:
    name, data_type, attrs = case
    kwargs = dict(attrs)
    if "partition_info" in kwargs and kwargs["partition_info"] is not None:
        raw_part = kwargs["partition_info"]
        if not isinstance(raw_part, ColumnPartitionSpec):
            kwargs["partition_info"] = ColumnPartitionSpec(**dict(raw_part))
    return ColumnSpec(ColumnDialect(dialect_key), name, data_type, **kwargs)


def _limits(owner_key: str) -> TypeMappingLimits:
    if owner_key not in EXPECTED_LIMITS:
        return TypeMappingLimits()
    (
        max_dt_scale,
        max_dec_prec,
        max_dec_scale,
        max_dec_int_mag,
        canon_date,
        canon_time,
    ) = EXPECTED_LIMITS[owner_key]
    return TypeMappingLimits(
        max_datetime_scale=max_dt_scale,
        max_decimal_precision=max_dec_prec,
        max_decimal_scale=max_dec_scale,
        max_decimal_integral_magnitude=max_dec_int_mag,
        canonical_date_supported=True if canon_date is None else bool(canon_date),
        canonical_time_supported=True if canon_time is None else bool(canon_time),
        supported_data_types=SUPPORTED_BACKEND_TYPES.get(owner_key, frozenset()),
    )


def _resolve_target_and_context(target_key: str) -> tuple[MappingTarget, MappingContext]:
    padding = 2 if target_key.endswith("_pad2") else 0
    base_key = target_key.removesuffix("_pad2")
    base64 = base_key.endswith("_base64")
    base_target_str = base_key.removesuffix("_base64")
    target = MappingTarget(base_target_str)
    owner_key = "impala" if target is MappingTarget.AVRO_IMPALA else base_target_str
    return (
        target,
        MappingContext(
            limits=_limits(owner_key),
            decimal_padding_digits=padding,
            binary_as_base64=base64,
        ),
    )


def _snap_to_canonical(fn, expected: object) -> object:
    try:
        col = fn()
        return tuple(getattr(col, f) for f in EXPECTED_FIELDS)
    except ColumnSpecError:
        if expected == "raises:NotImplementedError":
            return "raises:NotImplementedError"
        return "raises:ColumnSpecError"
    except Exception as exc:
        return f"raises:{type(exc).__name__}"


def _snap_from_canonical(fn, expected: object) -> object:
    try:
        col = fn()
        return (*tuple(getattr(col, f) for f in EXPECTED_FIELDS), col.format_data_type())
    except ColumnSpecError:
        if expected == "raises:NotImplementedError":
            return "raises:NotImplementedError"
        return "raises:ColumnSpecError"
    except Exception as exc:
        return f"raises:{type(exc).__name__}"
