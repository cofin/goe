# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Composable staging table cast validation and final table merge services."""

from collections.abc import Callable, Sequence
from typing import Any

from goe.offload.offload_constants import DBTYPE_IMPALA
from goe.offload.offload_functions import (
    get_hybrid_threshold_clauses,
    hvs_to_backend_sql_literals,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.schema.column_spec import (
    HADOOP_TYPE_STRING,
    get_column_names,
    match_table_column,
    str_list_of_columns,
    valid_column_list,
)
from goe.typing import FrozenBaseStruct

__all__ = [
    "CAST_VALIDATION_EXCEPTION_TEXT",
    "DATA_VALIDATION_NOT_NULL_EXCEPTION_TEXT",
    "DATA_VALIDATION_SCALE_EXCEPTION_TEXT",
    "NULL_BACKEND_PARTITION_VALUE_WARNING_TEXT",
    "OFFLOAD_CHUNK_COLUMN_MESSAGE_PATTERN",
    "CastPlanEntry",
    "FinalInsertPlan",
    "FinalTableMerger",
    "StagedValidationRule",
    "StagingLoadService",
]

CAST_VALIDATION_EXCEPTION_TEXT = "Data type conversion issue in load data"
DATA_VALIDATION_SCALE_EXCEPTION_TEXT = "Include --allow-decimal-scale-rounding option to proceed with the offload"
DATA_VALIDATION_NOT_NULL_EXCEPTION_TEXT = "NOT NULL column has NULL values"
NULL_BACKEND_PARTITION_VALUE_WARNING_TEXT = "Backend partition column has NULL values"
OFFLOAD_CHUNK_COLUMN_MESSAGE_PATTERN = "Identified %s sub-chunks"


class CastPlanEntry(FrozenBaseStruct, frozen=True):
    """Staging-to-final cast specification for a single target column."""

    column_name: str
    cast_expr: str
    cast_type: str | None
    verify_cast_expr: str | None

    def to_legacy_dict(self) -> dict[str, str | None]:
        """Return the legacy dictionary representation expected by BackendTableInterface._final_table_casts."""
        return {
            "cast": self.cast_expr,
            "cast_type": self.cast_type,
            "verify_cast": self.verify_cast_expr,
        }


class StagedValidationRule(FrozenBaseStruct, frozen=True):
    """Single predicate rule evaluated against the staged load table prior to final merge."""

    column_name: str
    expression: str
    fatal: bool
    message: str


class FinalInsertPlan(FrozenBaseStruct, frozen=True):
    """Compiled SQL statements and session query options for final table or materialized join load."""

    sql_statements: tuple[str, ...]
    query_options: dict[str, Any] | None = None


class StagingLoadService:
    """Compiles and executes staged load table cast verification and data quality checks."""

    def build_final_table_casts(
        self,
        backend_columns: Sequence[Any],
        rdbms_columns: Sequence[Any],
        staging_columns: Sequence[Any],
        *,
        is_synthetic_partition_column: Callable[[Any], bool],
        get_column: Callable[[str], Any],
        staging_to_backend_cast: Callable[[Any, Any, Any], tuple[str, str | None, str | None]],
        gen_synthetic_sql_cast: Callable[[Any, str], str],
        log_fn: Callable[..., None] | None = None,
    ) -> dict[str, dict[str, str | None]]:
        """Build the per-column cast dictionary mapping staged columns to target table expressions."""
        if not rdbms_columns or not staging_columns:
            return {}
        final_table_casts: dict[str, dict[str, str | None]] = {}
        for backend_col in backend_columns:
            source_backend_col = backend_col
            if backend_col.partition_info and is_synthetic_partition_column(backend_col):
                if log_fn:
                    log_fn(
                        f"Picking up source column for partition column {backend_col.name}: "
                        f"{backend_col.partition_info.source_column_name}",
                        detail=VVERBOSE,
                    )
                source_backend_col = get_column(backend_col.partition_info.source_column_name)
            rdbms_col = match_table_column(source_backend_col.name, rdbms_columns)
            staging_col = match_table_column(source_backend_col.name, staging_columns)
            cast_expr, cast_type, vcast_expr = staging_to_backend_cast(rdbms_col, source_backend_col, staging_col)
            if backend_col.partition_info and is_synthetic_partition_column(backend_col):
                partition_expr = gen_synthetic_sql_cast(backend_col, cast_expr)
                partition_vexpr = gen_synthetic_sql_cast(backend_col, vcast_expr or cast_expr)
                entry = CastPlanEntry(
                    column_name=backend_col.name.upper(),
                    cast_expr=partition_expr,
                    cast_type=backend_col.data_type,
                    verify_cast_expr=partition_vexpr,
                )
            else:
                entry = CastPlanEntry(
                    column_name=backend_col.name.upper(),
                    cast_expr=cast_expr,
                    cast_type=cast_type,
                    verify_cast_expr=vcast_expr,
                )
            final_table_casts[entry.column_name] = entry.to_legacy_dict()
        return final_table_casts

    @staticmethod
    def build_cast_verification_sql(
        staging_object_name: str,
        projection_list: Sequence[str],
        predicate_or_list: Sequence[str],
        limit: int | None = None,
    ) -> str:
        """Format the SELECT query used to count or sample rows failing staging-to-final casts."""
        limit_clause = f"\nLIMIT {limit}" if limit else ""
        return (
            "SELECT " + "\n,      ".join(projection_list) + "\n"
            f"FROM   {staging_object_name}\n"
            "WHERE  " + "\nOR     ".join(predicate_or_list) + limit_clause
        )

    def validate_final_table_casts(
        self,
        cast_validation_cols: Sequence[tuple[str, str]],
        *,
        staging_object_name: str,
        staging_col_is_not_null_expr: Callable[[str], str],
        format_staging_col_name: Callable[[str], str],
        execute_query_fetch_one: Callable[..., Any],
        query_options: dict[str, Any] | None,
        log_fn: Callable[..., None],
        exc_factory: Callable[[str], Exception],
        log_profile: Any = None,
    ) -> None:
        """Verify that no non-null staged value turns NULL when cast to its target column type."""
        if not cast_validation_cols:
            return
        cast_check_preds = [
            f"({staging_col_is_not_null_expr(cname)} AND {ccast} IS NULL)" for cname, ccast in cast_validation_cols
        ]
        verify_sql = self.build_cast_verification_sql(staging_object_name, ["COUNT(*)"], cast_check_preds)
        verify_set = execute_query_fetch_one(
            verify_sql,
            query_options=query_options,
            log_level=VERBOSE,
            not_when_dry_running=True,
            profile=log_profile,
        )
        if verify_set and verify_set[0] > 0:
            cast_check_cols = [format_staging_col_name(cname) for cname, _ in cast_validation_cols]
            identify_proj = [f"MAX(CASE WHEN {pred} THEN {i} END)" for i, pred in enumerate(cast_check_preds)]
            identify_sql = self.build_cast_verification_sql(
                staging_object_name,
                identify_proj,
                cast_check_preds,
            )
            identify_set = execute_query_fetch_one(identify_sql, query_options=query_options)
            failing_casts = [cast_check_preds[idx] for idx in identify_set if idx is not None]
            failing_cols = [cast_check_cols[idx] for idx in identify_set if idx is not None]
            log_fn(
                f"CAST() of load data will cause data loss due to lack of precision "
                f"in target data type in {verify_set[0]} rows",
                ansi_code="red",
            )
            log_fn("Failing casts are:\n%s" % "\n".join(failing_casts), ansi_code="red")
            if failing_casts:
                suggest_sql = self.build_cast_verification_sql(
                    staging_object_name,
                    failing_cols,
                    failing_casts,
                    limit=min(verify_set[0], 50),
                )
                log_fn(f"The SQL below will assist identification of problem data:\n{suggest_sql}")
            raise exc_factory(CAST_VALIDATION_EXCEPTION_TEXT)

    def build_staged_validation_rules(
        self,
        *,
        backend_columns: Sequence[Any],
        non_synthetic_columns: Sequence[Any],
        partition_columns: Sequence[Any],
        rdbms_part_cols: Sequence[Any],
        rdbms_columns: Sequence[Any],
        staging_columns: Sequence[Any],
        not_null_supported: bool,
        nan_supported: bool,
        allow_decimal_scale_rounding: bool,
        backend_display_name: str,
        format_staging_col_name: Callable[[Any], str],
        max_decimal_scale: Callable[[str], int],
        decimal_scale_validation_expr: Callable[[str, int], str],
        is_nan_sql_expr: Callable[[str], str],
        is_synthetic_partition_column: Callable[[str], bool],
        get_column: Callable[[str], Any],
        get_verification_cast: Callable[[str], str],
        gen_synthetic_part_number_granularity_sql_expr: Callable[..., str],
        length_sql_expr: Callable[[str], str],
        partition_key_out_of_range_message: Callable[[Any], str],
        debug_fn: Callable[[str], None] | None = None,
    ) -> list[StagedValidationRule]:
        """Assemble the list of StagedValidationRule predicates for staged table verification."""
        rules: list[StagedValidationRule] = []
        checked_cols: list[str] = []

        if not_null_supported:
            nn_cols = get_column_names([c for c in backend_columns if c.nullable is False], str.upper)
            for col_name in nn_cols:
                staging_col = match_table_column(col_name, staging_columns)
                rules.append(
                    StagedValidationRule(
                        column_name=col_name,
                        expression=f"{format_staging_col_name(staging_col)} IS NULL",
                        fatal=True,
                        message=f"{DATA_VALIDATION_NOT_NULL_EXCEPTION_TEXT}: {col_name}",
                    )
                )
            checked_cols.extend(nn_cols)

        if rdbms_part_cols and len(rdbms_part_cols) > 1:
            extra_rdbms = set(get_column_names(rdbms_part_cols, str.upper)).difference(checked_cols)
            for col_name in extra_rdbms:
                staging_col = match_table_column(col_name, staging_columns)
                rules.append(
                    StagedValidationRule(
                        column_name=col_name,
                        expression=f"{format_staging_col_name(staging_col)} IS NULL",
                        fatal=False,
                        message=f"Source RDBMS partition key {col_name} has NULL values",
                    )
                )
            checked_cols.extend(extra_rdbms)

        if partition_columns:
            source_names = [
                c.partition_info.source_column_name.upper()
                for c in partition_columns
                if c.partition_info and c.partition_info.source_column_name
            ]
            for col_name in set(source_names).difference(checked_cols):
                staging_col = match_table_column(col_name, staging_columns)
                rules.append(
                    StagedValidationRule(
                        column_name=col_name.upper(),
                        expression=f"{format_staging_col_name(staging_col)} IS NULL",
                        fatal=False,
                        message=f"{NULL_BACKEND_PARTITION_VALUE_WARNING_TEXT}: {col_name}",
                    )
                )

        nan_cols = [c.name for c in rdbms_columns if c.is_nan_capable()]
        if nan_cols and nan_supported:
            for col_name in nan_cols:
                staging_col = match_table_column(col_name, staging_columns)
                rules.append(
                    StagedValidationRule(
                        column_name=col_name.upper(),
                        expression=is_nan_sql_expr(format_staging_col_name(staging_col)),
                        fatal=False,
                        message=(
                            f'Column "{col_name.upper()}" has NaN values, RDBMS and '
                            f"{backend_display_name} predicate comparisons may not be consistent"
                        ),
                    )
                )

        if not allow_decimal_scale_rounding:
            for scale_col in [c for c in non_synthetic_columns if c.is_number_based()]:
                staging_col = match_table_column(scale_col.name, staging_columns)
                assert staging_col is not None
                if not staging_col.is_string_based():
                    continue
                rdbms_col = match_table_column(scale_col.name, rdbms_columns)
                assert rdbms_col is not None
                if rdbms_col.data_scale == 0:
                    if debug_fn:
                        debug_fn("RDBMS column has integral data so no need to check data")
                    continue
                backend_scale = scale_col.data_scale
                if backend_scale is None:
                    backend_scale = max_decimal_scale(scale_col.data_type)
                if rdbms_col.data_scale and 0 < rdbms_col.data_scale < backend_scale:
                    if debug_fn:
                        debug_fn(
                            f"RDBMS column scale is safely below the backend so no need to check it: "
                            f"{rdbms_col.data_scale} < {backend_scale}"
                        )
                    continue
                invalid_scale_expr = decimal_scale_validation_expr(
                    format_staging_col_name(staging_col),
                    backend_scale,
                )
                rules.append(
                    StagedValidationRule(
                        column_name=scale_col.name.upper(),
                        expression=invalid_scale_expr,
                        fatal=True,
                        message=(
                            f"Scale for column {scale_col.name.upper()} exceeds column maximum: "
                            f"{backend_scale}\n{DATA_VALIDATION_SCALE_EXCEPTION_TEXT}"
                        ),
                    )
                )

        for part_col in partition_columns:
            if (
                is_synthetic_partition_column(part_col.name)
                and part_col.is_string_based()
                and part_col.partition_info
                and not part_col.partition_info.function
            ):
                source_col = get_column(part_col.partition_info.source_column_name)
                if source_col.is_number_based():
                    gran_expr = gen_synthetic_part_number_granularity_sql_expr(
                        get_verification_cast(source_col.name.upper()),
                        source_col,
                        part_col.partition_info.granularity,
                        part_col.partition_info.digits,
                        with_padding=False,
                    )
                    len_expr = length_sql_expr(gran_expr)
                    src_upper = part_col.partition_info.source_column_name.upper()
                    rules.append(
                        StagedValidationRule(
                            column_name=src_upper,
                            expression=f"{len_expr} > {part_col.partition_info.digits}",
                            fatal=True,
                            message=(
                                f"Synthetic value for {src_upper} exceeds digits "
                                f"{part_col.partition_info.digits}, re-offload with larger value "
                                "for --partition-digits"
                            ),
                        )
                    )
            elif not is_synthetic_partition_column(part_col.name):
                if (
                    part_col.partition_info
                    and part_col.partition_info.range_start is not None
                    and part_col.partition_info.range_end is not None
                ):
                    vcast = get_verification_cast(part_col.name)
                    rules.append(
                        StagedValidationRule(
                            column_name=part_col.name.upper(),
                            expression=(
                                f"{vcast} < {part_col.partition_info.range_start} "
                                f"OR {vcast} > {part_col.partition_info.range_end}"
                            ),
                            fatal=False,
                            message=partition_key_out_of_range_message(part_col),
                        )
                    )

        return rules

    def validate_staged_data(
        self,
        rules: Sequence[StagedValidationRule],
        *,
        staging_object_name: str,
        expected_rows: int | None,
        execute_query_fetch_one: Callable[..., Any],
        query_options: dict[str, Any] | None,
        log_fn: Callable[..., None],
        warning_fn: Callable[..., None],
        exc_factory: Callable[[str], Exception],
        log_profile: Any = None,
    ) -> None:
        """Execute the combined staged data validation query and enforce row counts and fatal rules."""
        projection = [f"MAX(CASE WHEN {r.expression} THEN {i} END)" for i, r in enumerate(rules)] + ["COUNT(*)"]
        pred_messages = "\n,      ".join(projection)
        sql = f"SELECT {pred_messages}\nFROM   {staging_object_name}"
        validation_set = execute_query_fetch_one(
            sql,
            query_options=query_options,
            log_level=VERBOSE,
            not_when_dry_running=True,
            profile=log_profile,
        )
        if validation_set:
            row_values = list(validation_set)
            count_star = row_values.pop()
            if expected_rows is None:
                log_fn(f"Load table row count: {count_star}", detail=VERBOSE)
            elif expected_rows == count_star:
                log_fn(
                    f"Offload row count matches load table row count ({expected_rows} == {count_star})",
                    detail=VERBOSE,
                )
            else:
                log_fn(
                    f"Offload row count != load table row count ({expected_rows} != {count_star})",
                    detail=VVERBOSE,
                )
                raise exc_factory(
                    f"Offload row count does not match load table row count ({expected_rows} != {count_star})"
                )
            for msg_code in row_values:
                if msg_code is not None:
                    warning_fn(rules[msg_code].message, ansi_code="red")
            errors = [
                rules[msg_code].message for msg_code in row_values if msg_code is not None and rules[msg_code].fatal
            ]
            if errors:
                raise exc_factory("\n".join(errors))
        else:
            log_fn("Staged data validation returned an empty set", detail=VERBOSE)


class FinalTableMerger:
    """Compiles final INSERT INTO ... SELECT and materialized join statements from staged data."""

    def build_subchunk_filter_clauses(
        self,
        *,
        requested_chunk_column: str | None,
        partition_columns: Sequence[Any],
        get_final_table_cast: Callable[[Any], str],
        enclose_identifier: Callable[[str], str],
        load_db_name: str,
        load_table_name: str,
        backend_type: str,
        dry_run: bool,
        execute_query_fetch_all: Callable[..., Any],
        log_fn: Callable[..., None],
        warning_fn: Callable[[str], None],
        debug_fn: Callable[[str], None] | None = None,
    ) -> list[str] | None:
        """Discover distinct partition subchunks when --offload-chunk-column is active."""
        if not requested_chunk_column:
            return None
        chunk_cols = [
            c
            for c in partition_columns
            if c.partition_info
            and c.partition_info.source_column_name
            and c.partition_info.source_column_name.upper() == requested_chunk_column.upper()
        ]
        chunk_col = chunk_cols[0] if chunk_cols else None
        if not chunk_col:
            warning_fn(f"Unknown partition column, ignoring --offload-chunk-column: {requested_chunk_column}")
            return None
        subchunk_expr = get_final_table_cast(chunk_col)
        if debug_fn:
            debug_fn(f"Subchunk expression: {subchunk_expr}")
        order_by = "\nORDER BY COUNT(*) DESC" if backend_type == DBTYPE_IMPALA else ""
        subchunk_sql = (
            f"SELECT {subchunk_expr}, COUNT(*)\n"
            f"FROM {enclose_identifier(load_db_name)}.{enclose_identifier(load_table_name)}\n"
            f"GROUP BY {subchunk_expr}{order_by}"
        )
        log_fn(subchunk_sql, detail=VERBOSE)
        if not dry_run:
            subchunks = execute_query_fetch_all(subchunk_sql, log_level=VERBOSE, not_when_dry_running=True)
            log_fn(OFFLOAD_CHUNK_COLUMN_MESSAGE_PATTERN % len(subchunks), detail=VERBOSE)
        else:
            subchunks = [("?", -1)]
        clauses: list[str] = []
        for subchunk_id, _ in subchunks:
            formatted_id = f"'{subchunk_id}'" if chunk_col.data_type == HADOOP_TYPE_STRING else str(subchunk_id)
            clauses.append(f"{subchunk_expr} = {formatted_id}")
        return clauses

    def build_final_insert_plan(
        self,
        select_expr_tuples: Sequence[tuple[str, str]],
        *,
        threshold_clauses: Sequence[str] | None = None,
        sort_expr_list: Sequence[str] | None = None,
        for_materialized_join: bool = False,
        subchunk_clauses: Sequence[str] | None = None,
        query_options: dict[str, Any] | None = None,
        format_insert_sql: Callable[..., str],
        debug_fn: Callable[[str], None] | None = None,
    ) -> FinalInsertPlan:
        """Build the sequence of INSERT INTO ... SELECT SQL statements and session options."""
        base_thresholds = list(threshold_clauses or ())
        sqls: list[str] = []
        if subchunk_clauses:
            if debug_fn:
                debug_fn(f"Subchunk clauses: {list(subchunk_clauses)}")
            for chunk_clause in subchunk_clauses:
                sqls.append(
                    format_insert_sql(
                        list(select_expr_tuples),
                        base_thresholds + [chunk_clause],
                        sort_expr_list,
                        for_materialized_join=for_materialized_join,
                    )
                )
        else:
            sqls.append(
                format_insert_sql(
                    list(select_expr_tuples),
                    base_thresholds,
                    sort_expr_list,
                    for_materialized_join=for_materialized_join,
                )
            )
        return FinalInsertPlan(sql_statements=tuple(sqls), query_options=query_options)

    def build_materialized_join_plan(
        self,
        select_expr_tuples: Sequence[tuple[str, str]],
        *,
        threshold_cols: Sequence[Any] | None = None,
        gte_threshold_vals: Sequence[Any] | None = None,
        lt_threshold_vals: Sequence[Any] | None = None,
        insert_predicates: Sequence[str] | None = None,
        sort_expr_list: Sequence[str] | None = None,
        ipa_predicate_type: str | None = None,
        to_backend_literal: Callable[..., str],
        enclose_identifier: Callable[[str], str],
        subchunk_clauses: Sequence[str] | None = None,
        query_options: dict[str, Any] | None = None,
        format_insert_sql: Callable[..., str],
        debug_fn: Callable[[str], None] | None = None,
    ) -> FinalInsertPlan:
        """Build the INSERT INTO ... SELECT plan for a materialized join pushdown."""
        if threshold_cols:
            assert valid_column_list(threshold_cols)
        if insert_predicates:
            threshold_clauses = list(insert_predicates)
        else:
            if debug_fn:
                debug_fn(f"Incremental insert columns: {str_list_of_columns(threshold_cols)}")
                debug_fn(f"Incremental insert lt: {lt_threshold_vals}")
                debug_fn(f"Incremental insert gte: {gte_threshold_vals}")
            threshold_clauses = []
            if threshold_cols and lt_threshold_vals:
                lt_literals = hvs_to_backend_sql_literals(
                    threshold_cols,
                    lt_threshold_vals,
                    ipa_predicate_type,
                    to_backend_literal,
                )
                lt_clause, _ = get_hybrid_threshold_clauses(
                    threshold_cols,
                    threshold_cols,
                    ipa_predicate_type,
                    lt_literals,
                    col_enclosure_fn=enclose_identifier,
                )
                threshold_clauses.append(lt_clause)
                if gte_threshold_vals:
                    gte_literals = hvs_to_backend_sql_literals(
                        threshold_cols,
                        gte_threshold_vals,
                        ipa_predicate_type,
                        to_backend_literal,
                    )
                    _, gte_clause = get_hybrid_threshold_clauses(
                        threshold_cols,
                        threshold_cols,
                        ipa_predicate_type,
                        gte_literals,
                        col_enclosure_fn=enclose_identifier,
                    )
                    threshold_clauses.append(gte_clause)

        return self.build_final_insert_plan(
            select_expr_tuples,
            threshold_clauses=threshold_clauses,
            sort_expr_list=sort_expr_list,
            for_materialized_join=True,
            subchunk_clauses=subchunk_clauses,
            query_options=query_options,
            format_insert_sql=format_insert_sql,
            debug_fn=debug_fn,
        )
