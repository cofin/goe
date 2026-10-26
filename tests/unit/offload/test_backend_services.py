# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for BackendSessionManager, BackendDDLCompiler, StagingLoadService, and FinalTableMerger."""

from types import SimpleNamespace

import pytest

from goe.offload.backend_ddl import BackendDDLCompiler
from goe.offload.backend_load import (
    CAST_VALIDATION_EXCEPTION_TEXT,
    DATA_VALIDATION_NOT_NULL_EXCEPTION_TEXT,
    DATA_VALIDATION_SCALE_EXCEPTION_TEXT,
    FinalTableMerger,
    StagingLoadService,
)
from goe.offload.backend_session import BackendSessionManager, LogRedactionRule
from goe.offload.offload_constants import DBTYPE_IMPALA
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_NUMERIC,
    BIGQUERY_TYPE_STRING,
    HADOOP_TYPE_STRING,
    ORACLE_TYPE_BINARY_FLOAT,
    ORACLE_TYPE_NUMBER,
    PARQUET_TYPE_STRING,
    ColumnDialect,
    ColumnPartitionSpec,
    ColumnSpec,
)
from goe.persistence.models import INCREMENTAL_PREDICATE_TYPE_RANGE


class _DummyMessages:
    """In-memory OffloadMessages test double."""

    def __init__(self) -> None:
        self.logs: list[tuple[str, int | None, str | None]] = []
        self.warnings: list[tuple[str, str | None]] = []

    def log(self, msg: str, detail: int | None = None, ansi_code: str | None = None) -> None:
        self.logs.append((msg, detail, ansi_code))

    def warning(self, msg: str, ansi_code: str | None = None) -> None:
        self.warnings.append((msg, ansi_code))


def test_session_manager_merges_parameters_and_redacts_logs() -> None:
    """Verify session parameter clash removal, option validation, and sensitive log redaction."""
    messages = _DummyMessages()
    options = SimpleNamespace(
        backend_session_parameters={"MEM_LIMIT": "4G", "QUERY_TIMEOUT_S": 60},
        password_key_file=None,
        existing_attr="ok",
    )
    mgr = BackendSessionManager(
        options,
        "Impala",
        messages,
        fixed_parameters={"mem_limit": "8G"},
        do_not_connect=False,
    )
    assert mgr.global_session_parameters == {"QUERY_TIMEOUT_S": 60, "mem_limit": "8G"}
    assert any("MEM_LIMIT" in entry[0] for entry in messages.logs)

    mgr.validate_connection_options(["existing_attr"], RuntimeError)
    with pytest.raises(RuntimeError, match="Missing connection options: missing_one"):
        mgr.validate_connection_options(["existing_attr", "missing_one"], RuntimeError)

    assert mgr.decrypt_password("plain-secret") == "plain-secret"
    rule = LogRedactionRule(item="s3cr3t", sub="***")
    assert rule.item == "s3cr3t"
    assert mgr.redact_message("CONNECT PW=s3cr3t", {"item": "s3cr3t", "sub": "***"}) == "CONNECT PW=***"
    assert mgr.redact_message("TOKEN=abc", [{"item": "abc"}]) == "TOKEN=?"

    mgr.log_or_not("Query with secret_val", log_level=1, no_log_items={"item": "secret_val", "sub": "[REDACTED]"})
    assert messages.logs[-1][0] == "Query with [REDACTED]"


def test_ddl_compiler_clauses_and_synthetic_casts() -> None:
    """Verify DDL column clauses, decimal padding, HWM SQL, SELECT/INSERT SQL, and synthetic casts."""
    logs: list[str] = []
    compiler = BackendDDLCompiler(
        enclose_identifier=lambda ident: f"`{ident}`",
        enclose_object_reference=lambda db, tbl: f"`{db}`.`{tbl}`",
        not_null_column_supported=lambda: True,
        max_decimal_precision=lambda: 38,
        generic_string_data_type=lambda: "STRING",
        regexp_extract_sql=lambda col, pat: f"REGEXP_EXTRACT({col}, '{pat}')",
        regexp_extract_decimal_scale_pattern=lambda: r"\.([0-9]+)$",
        length_sql=lambda expr: f"LENGTH({expr})",
        log_fn=lambda msg, detail=None: logs.append(msg),
    )

    cols = [
        ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64, nullable=False),
        ColumnSpec(ColumnDialect.BIGQUERY, "NAME", BIGQUERY_TYPE_STRING, nullable=True),
    ]
    internal_ddl = compiler.format_create_table_columns_clause(cols, external=False)
    assert "`ID`" in internal_ddl and "NOT NULL" in internal_ddl
    external_ddl = compiler.format_create_table_columns_clause(cols, external=True)
    assert "NOT NULL" not in external_ddl

    prec, scale = compiler.apply_decimal_padding_digits("AMT", 10, 2, 4)
    assert (prec, scale) == (18, 6)
    prec_clamped, scale_clamped = compiler.apply_decimal_padding_digits("BIG_AMT", 36, 4, 5)
    assert (prec_clamped, scale_clamped) == (38, 4)

    single_max = compiler.build_max_column_values_sql("prod", "sales", ["ID"], filter_clause="ID > 0")
    assert single_max == "SELECT MAX(`ID`) FROM `prod`.`sales` WHERE ID > 0"
    multi_max = compiler.build_max_column_values_sql(
        "prod",
        "sales",
        ["YR", "MO"],
        columns_to_cast_to_string=["YR"],
    )
    assert "GROUP BY YR,MO ORDER BY YR DESC,MO DESC LIMIT 1" in multi_max
    assert "CAST(YR AS STRING) AS YR" in multi_max

    select_sql = compiler.build_select_sql(
        "prod",
        "sales",
        column_names=["ID"],
        filter_clauses=["ID > 10"],
        measures=["AMT"],
        agg_fns=["sum"],
    )
    assert "SUM(`AMT`)" in select_sql
    assert "GROUP BY `ID`" in select_sql
    assert "ORDER BY `ID`" in select_sql

    count_sql = compiler.build_select_count_sql("prod", "sales", filter_clause="1=1")
    assert count_sql == "SELECT COUNT(*) FROM `prod`.`sales` WHERE 1=1"

    insert_sql = compiler.build_insert_values_sql("prod", "sales", ["ID", "NAME"], ["1,'a'", "2,'b'"])
    assert "INSERT INTO `prod`.`sales` (`ID`,`NAME`) VALUES" in insert_sql

    assert compiler.extract_date_part_sql_expression("month", cols[0]) == "EXTRACT(MONTH FROM `ID`)"
    assert compiler.format_column_comparison(cols[0], "=", cols[0], "l", "r") == "`l`.`ID` = `r`.`ID`"
    assert (
        compiler.decimal_scale_validation_expression("STAGE_COL", 4)
        == r"LENGTH(REGEXP_EXTRACT(STAGE_COL, '\.([0-9]+)$')) > 4"
    )

    date_concat = compiler.build_synthetic_date_as_string_sql(
        "DT",
        "M",
        "CAST(DT AS DATE)",
        lambda part, pad, expr: f"{part}({expr},{pad})",
    )
    assert date_concat == "CONCAT(YEAR(CAST(DT AS DATE),4),'-',MONTH(CAST(DT AS DATE),2))"

    synth_date_col = ColumnSpec(
        ColumnDialect.BIGQUERY,
        "GOE_PART_M_DT",
        BIGQUERY_TYPE_DATE,
        partition_info=ColumnPartitionSpec(position=0, source_column_name="DT", granularity="M"),
    )
    src_date_col = ColumnSpec(ColumnDialect.BIGQUERY, "DT", BIGQUERY_TYPE_DATE)
    trunc_sql = compiler.build_synthetic_sql_cast(
        synth_date_col,
        src_date_col,
        "CAST(DT AS DATE)",
        partition_function_sql=lambda info, expr: f"UDF({expr})",
        date_truncated_sql=lambda p, s, g, expr: f"DATE_TRUNC({expr}, {g})",
        date_as_string_sql=lambda s, g, expr: f"STR_DATE({expr},{g})",
        string_granularity_sql=lambda s, g: f"SUBSTR({s},1,{g})",
        number_granularity_sql=lambda expr, col, g, d: f"FLOOR({expr}/{g})",
    )
    assert trunc_sql == "DATE_TRUNC(CAST(DT AS DATE), M)"


def test_staging_load_service_cast_and_staged_validation() -> None:
    """Verify staging cast resolution, cast overflow checks, and staged data validation rules."""
    service = StagingLoadService()
    backend_cols = [
        ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64, nullable=False),
        ColumnSpec(
            ColumnDialect.BIGQUERY,
            "AMT",
            BIGQUERY_TYPE_NUMERIC,
            data_precision=10,
            data_scale=2,
            nullable=True,
        ),
        ColumnSpec(ColumnDialect.BIGQUERY, "FLT", BIGQUERY_TYPE_NUMERIC, nullable=True),
        ColumnSpec(
            ColumnDialect.BIGQUERY,
            "GOE_PART_ID",
            BIGQUERY_TYPE_STRING,
            partition_info=ColumnPartitionSpec(
                position=0,
                source_column_name="ID",
                granularity=100,
                digits=6,
            ),
        ),
    ]
    rdbms_cols = [
        ColumnSpec(ColumnDialect.ORACLE, "ID", ORACLE_TYPE_NUMBER, data_precision=10, data_scale=0, nullable=False),
        ColumnSpec(ColumnDialect.ORACLE, "AMT", ORACLE_TYPE_NUMBER, data_precision=12, data_scale=4, nullable=True),
        ColumnSpec(ColumnDialect.ORACLE, "FLT", ORACLE_TYPE_BINARY_FLOAT, nullable=True),
    ]
    staging_cols = [
        ColumnSpec(ColumnDialect.PARQUET, "ID", PARQUET_TYPE_STRING, nullable=False),
        ColumnSpec(ColumnDialect.PARQUET, "AMT", PARQUET_TYPE_STRING, nullable=True),
        ColumnSpec(ColumnDialect.PARQUET, "FLT", PARQUET_TYPE_STRING, nullable=True),
    ]

    col_lookup = {c.name.upper(): c for c in backend_cols}
    casts = service.build_final_table_casts(
        backend_cols,
        rdbms_cols,
        staging_cols,
        is_synthetic_partition_column=lambda col: col.name.startswith("GOE_PART_"),
        get_column=lambda name: col_lookup[name.upper()],
        staging_to_backend_cast=lambda r, b, s: (
            f"CAST({s.name} AS {b.data_type})",
            b.data_type,
            f"SAFE_CAST({s.name})",
        ),
        gen_synthetic_sql_cast=lambda p, expr: f"SYNTH({expr})",
    )
    assert casts["ID"]["cast"] == "CAST(ID AS INT64)"
    assert casts["GOE_PART_ID"]["cast"] == "SYNTH(CAST(ID AS INT64))"

    logged: list[str] = []
    responses = iter([(2,), (0,)])
    with pytest.raises(RuntimeError, match=CAST_VALIDATION_EXCEPTION_TEXT):
        service.validate_final_table_casts(
            [("ID", "SAFE_CAST(ID AS INT64)")],
            staging_object_name="`stage`.`load_t`",
            staging_col_is_not_null_expr=lambda c: f"`{c}` IS NOT NULL",
            format_staging_col_name=lambda c: f"`{c}`",
            execute_query_fetch_one=lambda sql, **kw: next(responses),
            query_options=None,
            log_fn=lambda msg, **kw: logged.append(msg),
            exc_factory=RuntimeError,
        )
    assert any("assist identification" in line for line in logged)

    rules = service.build_staged_validation_rules(
        backend_columns=backend_cols,
        non_synthetic_columns=backend_cols[:3],
        partition_columns=[backend_cols[3]],
        rdbms_part_cols=[],
        rdbms_columns=rdbms_cols,
        staging_columns=staging_cols,
        not_null_supported=True,
        nan_supported=True,
        allow_decimal_scale_rounding=False,
        backend_display_name="BigQuery",
        format_staging_col_name=lambda c: f"`{c.name}`",
        max_decimal_scale=lambda _dt: 9,
        decimal_scale_validation_expr=lambda col, scale: f"SCALE({col}) > {scale}",
        is_nan_sql_expr=lambda col: f"IS_NAN({col})",
        is_synthetic_partition_column=lambda name: name.startswith("GOE_PART_"),
        get_column=lambda name: col_lookup[name.upper()],
        get_verification_cast=lambda name: f"VCAST({name})",
        gen_synthetic_part_number_granularity_sql_expr=lambda expr, col, gran, dig, with_padding=True: f"GRAN({expr})",
        length_sql_expr=lambda expr: f"LEN({expr})",
        partition_key_out_of_range_message=lambda col: f"OUT_OF_RANGE({col.name})",
    )
    assert any(DATA_VALIDATION_NOT_NULL_EXCEPTION_TEXT in r.message and r.fatal for r in rules)
    assert any(DATA_VALIDATION_SCALE_EXCEPTION_TEXT in r.message and r.fatal for r in rules)
    assert any("NaN" in r.message and not r.fatal for r in rules)
    assert any("Synthetic value for ID exceeds digits" in r.message and r.fatal for r in rules)

    warnings: list[str] = []
    with pytest.raises(RuntimeError, match=DATA_VALIDATION_NOT_NULL_EXCEPTION_TEXT):
        service.validate_staged_data(
            rules,
            staging_object_name="`stage`.`load_t`",
            expected_rows=10,
            execute_query_fetch_one=lambda sql, **kw: (0, None, None, None, 10),
            query_options=None,
            log_fn=lambda msg, **kw: None,
            warning_fn=lambda msg, **kw: warnings.append(msg),
            exc_factory=RuntimeError,
        )
    assert any(DATA_VALIDATION_NOT_NULL_EXCEPTION_TEXT in w for w in warnings)


def test_final_table_merger_insert_and_materialized_join_plans() -> None:
    """Verify subchunk discovery, final insert plan generation, and materialized join threshold plans."""
    merger = FinalTableMerger()
    part_col = ColumnSpec(
        ColumnDialect.HADOOP,
        "GOE_PART_ID",
        HADOOP_TYPE_STRING,
        partition_info=ColumnPartitionSpec(position=0, source_column_name="ID", granularity=10, digits=4),
    )
    clauses = merger.build_subchunk_filter_clauses(
        requested_chunk_column="id",
        partition_columns=[part_col],
        get_final_table_cast=lambda c: f"CAST({c.name} AS STRING)",
        enclose_identifier=lambda i: f"`{i}`",
        load_db_name="load_db",
        load_table_name="load_tbl",
        backend_type=DBTYPE_IMPALA,
        dry_run=False,
        execute_query_fetch_all=lambda sql, **kw: [("0010", 50), ("0020", 30)],
        log_fn=lambda msg, **kw: None,
        warning_fn=lambda msg: None,
    )
    assert clauses == [
        "CAST(GOE_PART_ID AS STRING) = '0010'",
        "CAST(GOE_PART_ID AS STRING) = '0020'",
    ]

    insert_plan = merger.build_final_insert_plan(
        [("`ID`", "ID")],
        threshold_clauses=["`ID` < 100"],
        subchunk_clauses=clauses,
        query_options={"SYNC_DDL": 1},
        format_insert_sql=lambda proj, filters, sorts, for_materialized_join=False: (
            f"INSERT WHERE {' AND '.join(filters)}"
        ),
    )
    assert len(insert_plan.sql_statements) == 2
    assert insert_plan.sql_statements[0] == "INSERT WHERE `ID` < 100 AND CAST(GOE_PART_ID AS STRING) = '0010'"
    assert insert_plan.query_options == {"SYNC_DDL": 1}

    threshold_col = ColumnSpec(ColumnDialect.BIGQUERY, "ID", BIGQUERY_TYPE_INT64)
    mat_plan = merger.build_materialized_join_plan(
        [("`ID`", "ID")],
        threshold_cols=[threshold_col],
        gte_threshold_vals=[10],
        lt_threshold_vals=[20],
        ipa_predicate_type=INCREMENTAL_PREDICATE_TYPE_RANGE,
        to_backend_literal=lambda val, data_type=None: str(val),
        enclose_identifier=lambda i: f"`{i}`",
        format_insert_sql=lambda proj, filters, sorts, for_materialized_join=False: (
            f"MAT_INSERT({for_materialized_join}): {' AND '.join(filters)}"
        ),
    )
    assert len(mat_plan.sql_statements) == 1
    assert "MAT_INSERT(True):" in mat_plan.sql_statements[0]
    assert "`ID` < 20" in mat_plan.sql_statements[0]
    assert "`ID` >= 10" in mat_plan.sql_statements[0]
