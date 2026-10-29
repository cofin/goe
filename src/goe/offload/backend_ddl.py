# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Composable backend DDL, projection, high-water-mark, and synthetic partition SQL compiler."""

from collections.abc import Callable, Sequence
from typing import Any

from goe.offload.offload_constants import (
    PART_COL_DATE_GRANULARITIES,
)
from goe.offload.offload_messages import VVERBOSE
from goe.offload.schema.column_spec import ColumnSpec

__all__ = [
    "BackendDDLCompiler",
]


class BackendDDLCompiler:
    """Compiles common backend DDL clauses, projection lists, HWM queries, and synthetic partition SQL."""

    def __init__(
        self,
        enclose_identifier: Callable[[str], str],
        enclose_object_reference: Callable[[str, str], str],
        *,
        not_null_column_supported: Callable[[], bool],
        max_decimal_precision: Callable[[], int],
        generic_string_data_type: Callable[[], str],
        regexp_extract_sql: Callable[[str, str], str] | None = None,
        regexp_extract_decimal_scale_pattern: Callable[[], str] | None = None,
        length_sql: Callable[[str], str] | None = None,
        log_fn: Callable[..., None] | None = None,
        debug_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._enclose_identifier = enclose_identifier
        self._enclose_object_reference = enclose_object_reference
        self._not_null_supported = not_null_column_supported
        self._max_decimal_precision = max_decimal_precision
        self._generic_string_data_type = generic_string_data_type
        self._regexp_extract_sql = regexp_extract_sql
        self._regexp_extract_decimal_scale_pattern = regexp_extract_decimal_scale_pattern
        self._length_sql = length_sql
        self._log_fn = log_fn
        self._debug_fn = debug_fn

    def format_column_nn_clause(self, column: Any, *, external: bool = False) -> str:
        """Return NOT NULL when supported, non-external, and column.nullable is explicitly False."""
        if not self._not_null_supported() or column.nullable or column.nullable is None or external:
            return ""
        return "NOT NULL"

    def format_create_table_columns_clause(self, column_list: Sequence[Any], *, external: bool = False) -> str:
        """Format aligned column definitions for a CREATE TABLE statement."""
        sql_cols = [
            (
                self._enclose_identifier(col.name),
                col.format_data_type(),
                self.format_column_nn_clause(col, external=external),
            )
            for col in column_list
        ]
        max_name = max(len(col[0]) for col in sql_cols)
        col_template = f"%-{max_name}s %s%s"
        return "    " + "\n,   ".join(
            [col_template % (col[0], col[1], f" {col[2]}" if col[2] else "") for col in sql_cols]
        )

    def format_select_projection(self, select_expr_tuples: Sequence[tuple[str, str]]) -> str:
        """Format a list of (expr, alias) tuples into an aligned SELECT projection."""
        return "\n,      ".join(f"{expr} AS {self._enclose_identifier(alias)}" for expr, alias in select_expr_tuples)

    def extract_date_part_sql_expression(self, date_part: str, column: str | Any) -> str:
        """Return an EXTRACT(DAY|MONTH|YEAR FROM col) expression."""
        assert isinstance(date_part, str)
        assert date_part.upper() in ("DAY", "MONTH", "YEAR")
        assert isinstance(column, (str, ColumnSpec))
        column_name = column if isinstance(column, str) else column.name
        return f"EXTRACT({date_part.upper()} FROM {self._enclose_identifier(column_name)})"

    def format_column_comparison(
        self,
        left_col: Any,
        operator: str,
        right_col: Any,
        left_alias: str | None = None,
        right_alias: str | None = None,
    ) -> str:
        """Format a qualified column-operator-column comparison expression."""
        assert isinstance(left_col, ColumnSpec)
        assert isinstance(right_col, ColumnSpec)
        left_ident = self._enclose_identifier(left_col.name)
        if left_alias:
            left_ident = f"{self._enclose_identifier(left_alias)}.{left_ident}"
        right_ident = self._enclose_identifier(right_col.name)
        if right_alias:
            right_ident = f"{self._enclose_identifier(right_alias)}.{right_ident}"
        return f"{left_ident} {operator} {right_ident}"

    def decimal_scale_validation_expression(self, column_name: str, column_scale: int) -> str:
        """Return a SQL predicate that evaluates True when a staged string exceeds column_scale."""
        assert self._regexp_extract_sql is not None
        assert self._regexp_extract_decimal_scale_pattern is not None
        assert self._length_sql is not None
        extract_scale_expr = self._regexp_extract_sql(column_name, self._regexp_extract_decimal_scale_pattern())
        length_expr = self._length_sql(extract_scale_expr)
        return f"{length_expr} > {column_scale}"

    def apply_decimal_padding_digits(
        self,
        column_name: str,
        data_precision: int | None,
        data_scale: int | None,
        decimal_padding_digits: int,
    ) -> tuple[int | None, int | None]:
        """Pad decimal scale and precision up to max_decimal_precision."""
        if not decimal_padding_digits:
            return data_precision, data_scale
        if data_precision is None or data_scale is None:
            if self._log_fn:
                self._log_fn(
                    f"No padding applied to {column_name} for precision/scale: {data_precision}/{data_scale}",
                    detail=VVERBOSE,
                )
            return data_precision, data_scale
        if self._debug_fn:
            self._debug_fn(f"Aligning precision/scale for {column_name}")
        max_prec = self._max_decimal_precision()
        new_precision = data_precision
        new_scale = data_scale
        if new_precision <= max_prec - decimal_padding_digits:
            new_scale += min(decimal_padding_digits, max_prec - new_precision)
            new_precision += min(decimal_padding_digits, max_prec - new_precision)
        if new_precision < max_prec:
            new_precision += min(decimal_padding_digits, max_prec - new_precision)
        if (new_precision != data_precision or new_scale != data_scale) and self._log_fn:
            self._log_fn(
                f"Padded precision/scale for {column_name} in line with "
                f"DECIMAL_PADDING_DIGITS={decimal_padding_digits}: "
                f"{data_precision},{data_scale} -> {new_precision},{new_scale}",
                detail=VVERBOSE,
            )
        return new_precision, new_scale

    def build_max_column_values_sql(
        self,
        db_name: str,
        table_name: str,
        column_name_list: Sequence[str],
        filter_clause: str | None = None,
        columns_to_cast_to_string: Sequence[str] | None = None,
    ) -> str:
        """Build a single-column MAX(col) or multi-column GROUP BY / ORDER BY DESC LIMIT 1 query."""
        assert column_name_list and isinstance(column_name_list, (list, tuple))
        if self._debug_fn:
            self._debug_fn(f"Generate max SQL for columns: {list(column_name_list)}")
        cast_targets = set(columns_to_cast_to_string or ())

        def _add_sql_cast(col_name: str, col_expr: str | None = None, add_alias: bool = False) -> str:
            expr = col_expr or col_name
            if col_name in cast_targets:
                cast_str = f"CAST({expr} AS {self._generic_string_data_type()})"
            else:
                cast_str = expr
            if add_alias:
                cast_str += f" AS {col_name}"
            return cast_str

        if len(column_name_list) == 1:
            proj_col = _add_sql_cast(
                column_name_list[0],
                col_expr=f"MAX({self._enclose_identifier(column_name_list[0])})",
            )
            sql = f"SELECT {proj_col} FROM {self._enclose_object_reference(db_name, table_name)}"
            if filter_clause:
                sql += " WHERE " + filter_clause
            return sql

        cols = ",".join(column_name_list)
        proj_cols = ",".join(_add_sql_cast(c, add_alias=True) for c in column_name_list)
        order_by = ",".join(f"{c} DESC" for c in column_name_list)
        where = f" WHERE {filter_clause}" if filter_clause else ""
        return (
            f"SELECT {proj_cols} FROM {self._enclose_object_reference(db_name, table_name)}"
            f"{where} GROUP BY {cols} ORDER BY {order_by} LIMIT 1"
        )

    def build_select_sql(
        self,
        db_name: str,
        table_name: str,
        column_names: Sequence[str] | None = None,
        filter_clauses: Sequence[str] | None = None,
        measures: Sequence[str] | None = None,
        agg_fns: Sequence[str] | None = None,
        *,
        exc_factory: Callable[[str], Exception] = ValueError,
    ) -> str:
        """Build a backend SELECT query with optional aggregate measures, WHERE, GROUP BY, and ORDER BY."""
        assert db_name and table_name
        projection: list[str] = []
        if column_names:
            projection.extend(self._enclose_identifier(c) for c in column_names)
        if measures and agg_fns:
            projection.extend(f"{fn.upper()}({self._enclose_identifier(m)})" for m in measures for fn in agg_fns)
        if not projection:
            raise exc_factory(f"No columns have been specified for projection: {db_name}.{table_name}")
        projection_clause = "\n,      ".join(projection)
        where_clause = "\nWHERE  " + "\nAND    ".join(filter_clauses) if filter_clauses else ""
        group_by_clause = (
            "\nGROUP BY " + "\n,        ".join(self._enclose_identifier(c) for c in column_names)
            if measures and column_names
            else ""
        )
        order_by_clause = (
            "\nORDER BY " + "\n,        ".join(self._enclose_identifier(c) for c in column_names)
            if agg_fns and column_names
            else ""
        )
        return (
            f"SELECT {projection_clause}\n"
            f"FROM   {self._enclose_identifier(db_name)}.{self._enclose_identifier(table_name)}"
            f"{where_clause}{group_by_clause}{order_by_clause}"
        )

    def build_select_count_sql(
        self,
        db_name: str,
        table_name: str,
        filter_clause: str | None = None,
    ) -> str:
        """Build a SELECT COUNT(*) query for a backend table."""
        assert db_name and table_name
        where_clause = f" WHERE {filter_clause}" if filter_clause else ""
        return f"SELECT COUNT(*) FROM {self._enclose_object_reference(db_name, table_name)}{where_clause}"

    def build_insert_values_sql(
        self,
        db_name: str,
        table_name: str,
        column_names: Sequence[str],
        literal_csv_list: Sequence[str],
        *,
        split_by_cr: bool = True,
    ) -> str:
        """Build an INSERT INTO ... VALUES (...) statement."""
        join_str = "\n," if split_by_cr else ","
        cols_csv = ",".join(self._enclose_identifier(c) for c in column_names)
        insert_prefix = f"INSERT INTO {self._enclose_object_reference(db_name, table_name)} ({cols_csv}) VALUES"
        return insert_prefix + "\n " + join_str.join(f"({row})" for row in literal_csv_list)

    def build_synthetic_date_as_string_sql(
        self,
        date_value: str | None,
        granularity: str,
        source_column_cast: str,
        date_part_fn: Callable[[str, int, str], str],
    ) -> str | None:
        """Build a CONCAT(YEAR, '-', MONTH, '-', DAY) synthetic partition expression up to granularity."""
        assert granularity in PART_COL_DATE_GRANULARITIES, f"Unexpected granularity: {granularity}"
        assert source_column_cast
        if date_value is None:
            return None
        assert isinstance(date_value, str)
        components: list[tuple[str, int]] = [("YEAR", 4), ("MONTH", 2), ("DAY", 2)]
        parts: list[str] = []
        for comp_name, width in components:
            parts.append(date_part_fn(comp_name, width, source_column_cast))
            if granularity == comp_name[0]:
                break
        return "CONCAT(%s)" % ",'-',".join(parts)

    def build_synthetic_sql_cast(
        self,
        partition_column: ColumnSpec | Any,
        source_column: ColumnSpec | Any,
        source_column_cast: str,
        *,
        partition_function_sql: Callable[[Any, str], str],
        date_truncated_sql: Callable[[str, str, str, str], str],
        date_as_string_sql: Callable[[str, str, str], str | None],
        string_granularity_sql: Callable[[str, int], str],
        number_granularity_sql: Callable[[str, Any, int, int | None], str],
    ) -> str:
        """Compile the backend SQL expression that populates a synthetic partition column."""
        part_info = partition_column.partition_info
        assert part_info is not None
        source_column_name = part_info.source_column_name
        digits = part_info.digits
        granularity = part_info.granularity
        if part_info.function:
            return partition_function_sql(part_info, source_column_cast)
        assert source_column_name is not None
        assert granularity is not None
        if source_column.is_date_based() and partition_column.is_date_based():
            return date_truncated_sql(
                partition_column.name,
                source_column_name,
                str(granularity),
                source_column_cast,
            )
        if source_column.is_date_based() and partition_column.is_string_based():
            expr = date_as_string_sql(source_column_name, str(granularity), source_column_cast)
            assert expr is not None
            return expr
        if source_column.is_string_based():
            return string_granularity_sql(source_column_name, int(granularity))
        if source_column.is_number_based():
            return number_granularity_sql(source_column_cast, source_column, int(granularity), digits)
        raise NotImplementedError(f"Unsupported synthetic partition column data type: {source_column.data_type}")
