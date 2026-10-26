# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Recursive-descent predicate DSL parser, column type resolver, and safe SQL filter validator."""

import re
from collections.abc import Sequence
from functools import lru_cache
from typing import cast

import numpy as np
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from goe.exceptions import OptionValueError
from goe.offload.predicates.ast import (
    BinaryComparison,
    ColumnRef,
    ComparisonOp,
    InListPredicate,
    LiteralKind,
    LiteralValue,
    LogicalAnd,
    LogicalNot,
    LogicalOr,
    NullCheckPredicate,
    PredicateExpr,
    TypedValue,
)
from goe.offload.schema.column_spec import (
    ColumnSpec,
    get_partition_columns,
    is_synthetic_partition_column,
    match_partition_column_by_source,
)
from goe.offload.synthetic_partition_literal import SyntheticPartitionLiteral

__all__ = (
    "RULE_HINT",
    "PredicateOffloadException",
    "parse_predicate_dsl",
    "parse_safe_sql_predicate",
    "resolve_predicate_types",
)

RULE_HINT: dict[str, str] = {
    "column": "column:         column(<column_name>)",
    "integer_value": "numeric value:  numeric(<signed_integer>) or numeric(<signed_decimal>)",
    "decimal_value": "numeric value:  numeric(<signed_integer>) or numeric(<signed_decimal>)",
    "datetime_value": (
        "datetime value: datetime(<yyyy-mm-dd>) or datetime(<yyyy-mm-dd hh24:mi:ss>) "
        "or datetime(<yyyy-mm-dd hh24:mi:ss.f9>)"
    ),
    "string_value": 'string value:   string("<string_value>")',
    "value_relation": "operator:       =, !=, >, >=, <, <=",
    "value_list_relation": "list operator:  IN, NOT IN",
    "value_list": (
        "value list:     (<value_type>(<value>), <value_type>(<value>), ...) "
        "where value_type is string, numeric or datetime"
    ),
    "null_test": "null test:      IS NULL, IS NOT NULL",
    "__and_relation_group_star_0": "AND:            groups of predicates combined with AND must be surrounded by parentheses",
    "__or_relation_group_star_1": "OR:             groups of predicates combined with OR must be surrounded by parentheses",
}

_FORBIDDEN_WHERE_AST_NODES = (
    exp.Select,
    exp.Subquery,
    exp.Table,
    exp.SetOperation,
    exp.Exists,
    exp.DDL,
    exp.DML,
    exp.Command,
)

_SAFE_ANONYMOUS_FUNCTIONS: frozenset[str] = frozenset(
    {
        "TO_DATE",
        "TO_TIMESTAMP",
        "TO_TIMESTAMP_TZ",
        "TO_CHAR",
        "TO_NUMBER",
        "NVL",
        "DECODE",
        "TRUNC",
        "MOD",
        "ORA_HASH",
        "PARSE_DATE",
        "PARSE_DATETIME",
        "PARSE_TIMESTAMP",
        "DATE_TRUNC",
        "DATETIME_TRUNC",
        "TIMESTAMP_TRUNC",
        "RANGE_BUCKET",
        "GENERATE_ARRAY",
    }
)

_AND_OR_RE = re.compile(r"^(and|or)(?=\s|\(|$)", re.IGNORECASE)
_NOT_RE = re.compile(r"^not(?=\s|\()", re.IGNORECASE)
_NOT_IN_RE = re.compile(r"^(not\s+)?in(?=\s|\(|$)", re.IGNORECASE)
_IS_NULL_START_RE = re.compile(r"^is(?=\s|$)", re.IGNORECASE)
_IS_NULL_FULL_RE = re.compile(r"^is\s+(?:(not)\s+)?null\b", re.IGNORECASE)
_COLUMN_OPEN_RE = re.compile(r"^column\s*\(")
_COLUMN_BODY_RE = re.compile(r"^([a-zA-Z0-9.$#_]+)\s*\)")
_ALIAS_RE = re.compile(r"^[a-zA-Z]+$")
_COMP_OP_RE = re.compile(r"^(>=|<=|!=|=|>|<)(?!=)")
_NUMERIC_OPEN_RE = re.compile(r"^numeric\s*\(")
_NUMERIC_BODY_RE = re.compile(r"^([+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+))\s*\)")
_DATETIME_OPEN_RE = re.compile(r"^datetime\s*\(")
_DATETIME_BODY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)?)\s*\)")
_QUOTED_OPEN_RE = re.compile(r"^(string|literal)\s*\(")
_QUOTED_BODY_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*\)')


class PredicateOffloadException(Exception):
    """Exception raised when predicate rendering or SQL WHERE validation fails."""


@lru_cache(maxsize=2048)
def parse_predicate_dsl(dsl_str: str) -> PredicateExpr:
    """Parse a GOE offload predicate DSL string into an immutable ``PredicateExpr`` AST."""
    if not isinstance(dsl_str, str):
        raise OptionValueError("Encountered EOF before reaching end of valid offload predicate.")
    return _DslParser(dsl_str).parse()


def resolve_predicate_types(
    expr: PredicateExpr,
    columns: Sequence[ColumnSpec],
    *,
    include_synthetic: bool = True,
) -> PredicateExpr:
    """Validate predicate column references and attach resolved database column data types."""
    col_list = list(columns)
    col_map = {col.name.upper(): col for col in col_list}
    partition_cols = get_partition_columns(col_list) if include_synthetic else []
    return _resolve_node(expr, col_map, col_list, partition_cols, include_synthetic=include_synthetic)


def parse_safe_sql_predicate(sql_where: str, dialect: str = "bigquery") -> str:
    """Validate a raw SQL WHERE condition against an AST allowlist and return the stripped condition."""
    stripped = sql_where.strip()
    if not stripped:
        raise PredicateOffloadException("Empty SQL filter clause is not allowed")
    try:
        statements = sqlglot.parse(f"SELECT 1 WHERE {stripped}", read=dialect)
    except SqlglotError as exc:
        raise PredicateOffloadException(f"Invalid SQL filter clause: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise PredicateOffloadException("Multiple statements or set operations are not allowed in filter clauses")
    where_node = statements[0].args.get("where")
    if where_node is None:
        raise PredicateOffloadException("Missing WHERE condition in filter clause")
    for node in where_node.walk():
        if isinstance(node, _FORBIDDEN_WHERE_AST_NODES):
            raise PredicateOffloadException(f"Disallowed SQL construct in filter clause: {type(node).__name__}")
        if isinstance(node, exp.Anonymous) and node.name.upper() not in _SAFE_ANONYMOUS_FUNCTIONS:
            raise PredicateOffloadException(f"Disallowed function in filter clause: {node.name}")
    return stripped


class _DslParser:
    """Recursive-descent parser for the GOE offload predicate DSL."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._len = len(text)
        self._pos = 0

    def parse(self) -> PredicateExpr:
        """Parse the complete DSL input and ensure no trailing tokens remain."""
        self._skip_ws()
        if self._pos >= self._len:
            self._eof_error()
        expr = self._parse_relation_group()
        self._skip_ws()
        if self._pos < self._len:
            self._syntax_error(["value_relation", "__and_relation_group_star_0", "__or_relation_group_star_1"])
        return expr

    def _skip_ws(self) -> None:
        while self._pos < self._len and self._text[self._pos].isspace():
            self._pos += 1

    def _eof_error(self) -> None:
        raise OptionValueError("Encountered EOF before reaching end of valid offload predicate.")

    def _syntax_error(self, expected_rules: Sequence[str]) -> None:
        pointer = " " * self._pos + "^"
        statement_hint = f"{self._text}\n{pointer}"
        hints = [f"- {RULE_HINT[r]}" for r in dict.fromkeys(expected_rules) if r in RULE_HINT]
        expected_hint = "Expected tokens in this position:\n" + "\n".join(hints) if hints else ""
        raise OptionValueError(f"Unexpected offload predicate syntax:\n{statement_hint}\n{expected_hint}")

    def _parse_relation_group(self) -> PredicateExpr:
        first = self._parse_predicate()
        children: list[PredicateExpr] = [first]
        group_op: str | None = None
        while True:
            self._skip_ws()
            match = _AND_OR_RE.match(self._text[self._pos :])
            if not match:
                break
            kw = match.group(1).upper()
            if group_op is not None and kw != group_op:
                self._syntax_error(["__and_relation_group_star_0", "__or_relation_group_star_1"])
            group_op = kw
            self._pos += match.end()
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()
            children.append(self._parse_predicate())

        if len(children) == 1:
            return children[0]
        if group_op == "AND":
            return LogicalAnd(children=tuple(children))
        return LogicalOr(children=tuple(children))

    def _parse_predicate(self) -> PredicateExpr:
        self._skip_ws()
        if self._pos >= self._len:
            self._eof_error()

        if self._text[self._pos] == "(":
            self._pos += 1
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()
            not_match = _NOT_RE.match(self._text[self._pos :])
            if not_match and not _NOT_IN_RE.match(self._text[self._pos :]):
                self._pos += not_match.end()
                child = self._parse_predicate()
                self._skip_ws()
                if self._pos >= self._len:
                    self._eof_error()
                if self._text[self._pos] != ")":
                    self._syntax_error(["__and_relation_group_star_0", "__or_relation_group_star_1"])
                self._pos += 1
                return LogicalNot(child=child)

            inner = self._parse_relation_group()
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()
            if self._text[self._pos] != ")":
                self._syntax_error(["__and_relation_group_star_0", "__or_relation_group_star_1"])
            self._pos += 1
            return inner

        if self._text.startswith("column", self._pos):
            col_ref = self._parse_column()
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()

            tail = self._text[self._pos :]
            if _IS_NULL_START_RE.match(tail):
                null_match = _IS_NULL_FULL_RE.match(tail)
                if not null_match:
                    self._syntax_error(["null_test"])
                assert null_match is not None
                self._pos += null_match.end()
                return NullCheckPredicate(column=col_ref, is_not_null=bool(null_match.group(1)))

            in_match = _NOT_IN_RE.match(tail)
            if in_match:
                negated = bool(in_match.group(1))
                self._pos += in_match.end()
                values = self._parse_value_list()
                return InListPredicate(column=col_ref, values=values, negated=negated)

            op = self._parse_comparison_op()
            lit = self._parse_value()
            return BinaryComparison(op=op, column=col_ref, literal=lit, lhs_is_column=True)

        lit = self._parse_value()
        op = self._parse_comparison_op()
        col_ref = self._parse_column()
        return BinaryComparison(op=op, column=col_ref, literal=lit, lhs_is_column=False)

    def _parse_column(self) -> ColumnRef:
        self._skip_ws()
        if self._pos >= self._len:
            self._eof_error()
        open_match = _COLUMN_OPEN_RE.match(self._text[self._pos :])
        if not open_match:
            self._syntax_error(["column"])
        assert open_match is not None
        self._pos += open_match.end()
        self._skip_ws()
        if self._pos >= self._len:
            self._eof_error()
        body_match = _COLUMN_BODY_RE.match(self._text[self._pos :])
        if not body_match:
            self._syntax_error(["column"])
        assert body_match is not None
        raw_ident = body_match.group(1)
        self._pos += body_match.end()
        if "." in raw_ident:
            first_part, rest = raw_ident.split(".", 1)
            if not _ALIAS_RE.match(first_part) or not rest:
                self._syntax_error(["column"])
            return ColumnRef(name=rest.upper(), alias=first_part.upper())
        return ColumnRef(name=raw_ident.upper(), alias=None)

    def _parse_comparison_op(self) -> ComparisonOp:
        self._skip_ws()
        if self._pos >= self._len:
            self._eof_error()
        match = _COMP_OP_RE.match(self._text[self._pos :])
        if not match:
            self._syntax_error(["value_relation", "value_list_relation", "null_test"])
        assert match is not None
        self._pos += match.end()
        return cast(ComparisonOp, match.group(1))

    def _parse_value_list(self) -> tuple[LiteralValue, ...]:
        self._skip_ws()
        if self._pos >= self._len:
            self._eof_error()
        if self._text[self._pos] != "(":
            self._syntax_error(["value_list"])
        self._pos += 1
        items: list[LiteralValue] = [self._parse_value()]
        while True:
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()
            if self._text[self._pos] == ",":
                self._pos += 1
                items.append(self._parse_value())
            else:
                break
        if self._text[self._pos] != ")":
            self._syntax_error(["value_list"])
        self._pos += 1
        return tuple(items)

    def _parse_value(self) -> LiteralValue:
        self._skip_ws()
        if self._pos >= self._len:
            self._eof_error()
        tail = self._text[self._pos :]

        num_open = _NUMERIC_OPEN_RE.match(tail)
        if num_open:
            self._pos += num_open.end()
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()
            num_body = _NUMERIC_BODY_RE.match(self._text[self._pos :])
            if not num_body:
                self._syntax_error(["integer_value", "decimal_value"])
            assert num_body is not None
            raw_num = num_body.group(1)
            self._pos += num_body.end()
            if "." in raw_num:
                sign = "-" if raw_num.startswith("-") else ""
                unsigned = raw_num.lstrip("+-")
                if unsigned.startswith("."):
                    unsigned = f"0{unsigned}"
                if unsigned.endswith("."):
                    unsigned = f"{unsigned}0"
                return LiteralValue(value=TypedValue(kind="decimal", text=f"{sign}{unsigned}"))
            return LiteralValue(value=TypedValue(kind="integer", text=str(int(raw_num))))

        dt_open = _DATETIME_OPEN_RE.match(tail)
        if dt_open:
            self._pos += dt_open.end()
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()
            dt_body = _DATETIME_BODY_RE.match(self._text[self._pos :])
            if not dt_body:
                self._syntax_error(["datetime_value"])
            assert dt_body is not None
            dt_text = dt_body.group(1)
            try:
                np.datetime64(dt_text.replace(" ", "T"))
            except ValueError:
                self._syntax_error(["datetime_value"])
            self._pos += dt_body.end()
            return LiteralValue(value=TypedValue(kind="datetime", text=dt_text))

        quoted_open = _QUOTED_OPEN_RE.match(tail)
        if quoted_open:
            kw = quoted_open.group(1)
            self._pos += quoted_open.end()
            self._skip_ws()
            if self._pos >= self._len:
                self._eof_error()
            quoted_body = _QUOTED_BODY_RE.match(self._text[self._pos :])
            if not quoted_body:
                self._syntax_error(["string_value"])
            assert quoted_body is not None
            unescaped = quoted_body.group(1).replace('\\"', '"')
            self._pos += quoted_body.end()
            kind: LiteralKind = "string" if kw == "string" else "raw_sql"
            return LiteralValue(value=TypedValue(kind=kind, text=unescaped))

        self._syntax_error(["integer_value", "decimal_value", "datetime_value", "string_value"])
        raise AssertionError("Unreachable")


def _resolve_node(
    expr: PredicateExpr,
    col_map: dict[str, ColumnSpec],
    col_list: list[ColumnSpec],
    partition_cols: list[ColumnSpec],
    *,
    include_synthetic: bool,
) -> PredicateExpr:
    """Recursively validate column types and inject synthetic partition comparisons."""
    if isinstance(expr, BinaryComparison):
        col = _lookup_and_validate_column(expr.column, col_map, [expr.literal])
        resolved_cmp = BinaryComparison(
            op=expr.op,
            column=expr.column,
            literal=LiteralValue(value=expr.literal.value, data_type=col.data_type),
            lhs_is_column=expr.lhs_is_column,
        )
        if include_synthetic and partition_cols:
            synth_col = match_partition_column_by_source(expr.column.name, partition_cols)
            if synth_col is not None and is_synthetic_partition_column(synth_col):
                synth_val = SyntheticPartitionLiteral.gen_synthetic_literal(
                    synth_col,
                    col_list,
                    expr.literal.value.raw,
                )
                synth_kind, synth_text = _synthetic_value_to_kind_and_text(synth_col, synth_val)
                synth_cmp = BinaryComparison(
                    op=expr.op,
                    column=ColumnRef(name=synth_col.name),
                    literal=LiteralValue(
                        value=TypedValue(kind=synth_kind, text=synth_text),
                        data_type=synth_col.data_type,
                    ),
                    lhs_is_column=expr.lhs_is_column,
                )
                return LogicalAnd(children=(resolved_cmp, synth_cmp))
        return resolved_cmp

    if isinstance(expr, InListPredicate):
        col = _lookup_and_validate_column(expr.column, col_map, expr.values)
        return InListPredicate(
            column=expr.column,
            values=tuple(LiteralValue(value=v.value, data_type=col.data_type) for v in expr.values),
            negated=expr.negated,
        )

    if isinstance(expr, NullCheckPredicate):
        return expr

    if isinstance(expr, LogicalAnd):
        return LogicalAnd(
            children=tuple(
                _resolve_node(c, col_map, col_list, partition_cols, include_synthetic=include_synthetic)
                for c in expr.children
            )
        )

    if isinstance(expr, LogicalOr):
        return LogicalOr(
            children=tuple(
                _resolve_node(c, col_map, col_list, partition_cols, include_synthetic=include_synthetic)
                for c in expr.children
            )
        )

    return LogicalNot(
        child=_resolve_node(expr.child, col_map, col_list, partition_cols, include_synthetic=include_synthetic)
    )


def _lookup_and_validate_column(
    col_ref: ColumnRef,
    col_map: dict[str, ColumnSpec],
    literals: Sequence[LiteralValue],
) -> ColumnSpec:
    """Resolve ``col_ref`` against ``col_map`` and verify compatibility with ``literals``."""
    col = col_map.get(col_ref.name.upper())
    if col is None:
        raise OptionValueError(f"Unable to resolve column '{col_ref.name.upper()}' in offload predicate")
    if not col.valid_for_offload_predicate():
        raise OptionValueError(f"Data type is not supported for offload predicate: {col.data_type}")
    for lit in literals:
        kind = lit.value.kind
        if kind == "raw_sql":
            continue
        if kind in ("integer", "decimal") and not col.is_number_based():
            raise OptionValueError(f"Columns of data type {col.data_type} cannot be compared to numeric values")
        if kind in ("date", "datetime") and not col.is_date_based():
            raise OptionValueError(f"Columns of data type {col.data_type} cannot be compared to datetime values")
        if kind == "string" and not col.is_string_based():
            raise OptionValueError(f"Columns of data type {col.data_type} cannot be compared to string values")
        if kind == "bytes" and not getattr(col, "is_binary", lambda: False)():
            raise OptionValueError(f"Columns of data type {col.data_type} cannot be compared to bytes values")
    return col


def _synthetic_value_to_kind_and_text(
    synth_col: ColumnSpec,
    synth_val: object,
) -> tuple[LiteralKind, str]:
    """Convert a synthetic partition literal value into a ``(LiteralKind, text)`` pair."""
    if synth_col.is_date_based():
        return ("datetime", str(synth_val).replace("T", " "))
    if synth_col.is_number_based() and isinstance(synth_val, int):
        return ("integer", str(synth_val))
    return ("string", str(synth_val))
