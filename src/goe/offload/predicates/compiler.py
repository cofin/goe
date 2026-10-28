# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Multi-dialect PredicateExpr to sqlglot AST and parameterized SQL compiler."""

from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Literal, cast

import numpy as np
from sqlglot import exp
from sqlspec.core import NamespacedCache

from goe.exceptions import OptionValueError
from goe.offload.bigquery.bigquery_literal import BigQueryLiteral
from goe.offload.predicates.ast import (
    BinaryComparison,
    ColumnRef,
    InListPredicate,
    LiteralValue,
    LogicalAnd,
    LogicalNot,
    LogicalOr,
    NullCheckPredicate,
    PredicateExpr,
    to_dsl,
)
from goe.offload.predicates.parser import (
    PredicateOffloadException,
    parse_predicate_dsl,
    parse_safe_sql_predicate,
    resolve_predicate_types,
)
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_BIGNUMERIC,
    BIGQUERY_TYPE_NUMERIC,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_TIMESTAMP_TZ,
    SNOWFLAKE_TYPE_DATE,
    SNOWFLAKE_TYPE_TIME,
    SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
    SNOWFLAKE_TYPE_TIMESTAMP_TZ,
    SYNAPSE_TYPE_NCHAR,
    SYNAPSE_TYPE_NVARCHAR,
    ColumnSpec,
)
from goe.offload.sql_engine import PredicateDialectEngineProtocol, RenderedSQL

__all__ = (
    "BindStyle",
    "PredicateCompiler",
    "PredicateDialect",
    "PredicateSqlEngine",
    "get_predicate_dialect_engine",
    "render_predicate",
)

type BindStyle = Literal["named_colon", "named_at", "qmark", "pyformat", "dollar"]
type PredicateDialect = Literal["oracle", "bigquery", "snowflake", "tsql", "hive", "spark", "duckdb"]

_SUPPORTED_DIALECTS: frozenset[str] = frozenset({"oracle", "bigquery", "snowflake", "tsql", "hive", "spark", "duckdb"})
_DEFAULT_BIND_STYLE: dict[str, BindStyle] = {
    "oracle": "named_colon",
    "bigquery": "named_at",
    "snowflake": "named_colon",
    "tsql": "named_colon",
    "hive": "named_colon",
    "spark": "named_colon",
    "duckdb": "dollar",
}
_PREDICATE_CACHE = NamespacedCache()


class PredicateCompiler:
    """Compile immutable ``PredicateExpr`` AST trees into dialect SQL and bind dictionaries."""

    @classmethod
    def to_sqlglot(
        cls,
        expr: PredicateExpr,
        dialect: PredicateDialect,
        *,
        bind_style: BindStyle | None = None,
        quote_identifiers: bool = True,
    ) -> tuple[exp.Expr, dict[str, Any]]:
        """Compile ``expr`` into a ``(sqlglot.exp.Expr, params)`` pair with cache memoization."""
        if dialect not in _SUPPORTED_DIALECTS:
            raise PredicateOffloadException(f"Unsupported predicate dialect: {dialect}")
        cache_key = f"{dialect}:{bind_style or 'literal'}:{quote_identifiers}:{expr!r}"
        cached = _PREDICATE_CACHE.get_expression(cache_key)
        if cached is not None:
            cached_expr, cached_params = cached
            return cached_expr, dict(cached_params)
        builder = _DialectAstBuilder(
            dialect=dialect,
            bind_style=bind_style,
            quote_identifiers=quote_identifiers,
        )
        ast_node = builder.build(expr)
        params = dict(builder.binds)
        _PREDICATE_CACHE.put_expression(cache_key, (ast_node, params))
        return ast_node, dict(params)

    @classmethod
    def render(
        cls,
        expr: PredicateExpr,
        dialect: PredicateDialect,
        *,
        bind_style: BindStyle | None = None,
        quote_identifiers: bool = True,
    ) -> RenderedSQL:
        """Render ``expr`` into a dialect-specific ``RenderedSQL`` result."""
        ast_node, params = cls.to_sqlglot(
            expr,
            dialect,
            bind_style=bind_style,
            quote_identifiers=quote_identifiers,
        )
        return RenderedSQL(sql=ast_node.sql(dialect), params=params)

    @classmethod
    def compile_predicate(
        cls,
        predicate_dsl: Any,
        *,
        dialect: str,
        columns: Sequence[ColumnSpec] = (),
    ) -> str:
        """Compile a predicate DSL string or AST into a dialect WHERE clause."""
        return get_predicate_dialect_engine(dialect.lower()).render_literal_sql(predicate_dsl, columns)


def render_predicate(
    expr: PredicateExpr,
    dialect: PredicateDialect,
    *,
    bind_style: BindStyle | None = None,
    quote_identifiers: bool = True,
) -> RenderedSQL:
    """Compile and render ``expr`` for ``dialect`` using ``PredicateCompiler``."""
    return PredicateCompiler.render(
        expr,
        dialect,
        bind_style=bind_style,
        quote_identifiers=quote_identifiers,
    )


class PredicateSqlEngine(PredicateDialectEngineProtocol):
    """Dialect-specific predicate AST renderer satisfying ``PredicateDialectEngineProtocol``."""

    def __init__(self, dialect: str) -> None:
        if dialect not in _SUPPORTED_DIALECTS:
            raise PredicateOffloadException(f"Unsupported predicate dialect: {dialect}")
        self._dialect = cast(PredicateDialect, dialect)

    def render_literal_sql(
        self,
        typed_tree: Any,
        columns: Sequence[ColumnSpec],
    ) -> str:
        """Render a predicate expression into a SQL WHERE clause with inline literals."""
        expr = _ensure_resolved(typed_tree, columns)
        return render_predicate(
            expr,
            self._dialect,
            bind_style=None,
            quote_identifiers=(self._dialect != "hive"),
        ).sql

    def render_bind_sql(
        self,
        typed_tree: Any,
        columns: Sequence[ColumnSpec],
    ) -> RenderedSQL:
        """Render a predicate expression into a SQL WHERE clause with named bind parameters."""
        expr = _ensure_resolved(typed_tree, columns)
        bind_style = _DEFAULT_BIND_STYLE[self._dialect]
        return render_predicate(
            expr,
            self._dialect,
            bind_style=bind_style,
            quote_identifiers=(self._dialect != "hive"),
        )

    def validate_where_clause(self, raw_sql: str, dialect: str) -> str:
        """Validate a raw SQL WHERE condition against an AST allowlist and return normalized SQL."""
        return parse_safe_sql_predicate(raw_sql, dialect=dialect)


@lru_cache(maxsize=16)
def get_predicate_dialect_engine(dialect: str) -> PredicateDialectEngineProtocol:
    """Return a cached ``PredicateDialectEngineProtocol`` instance for ``dialect``."""
    return PredicateSqlEngine(dialect)


class _DialectAstBuilder:
    """Stateful visitor converting a ``PredicateExpr`` into a ``sqlglot`` expression tree."""

    def __init__(
        self,
        *,
        dialect: PredicateDialect,
        bind_style: BindStyle | None,
        quote_identifiers: bool,
    ) -> None:
        self._dialect = dialect
        self._bind_style = bind_style
        self._quote_identifiers = quote_identifiers
        self.binds: dict[str, Any] = {}

    def build(self, expr: PredicateExpr) -> exp.Expr:
        """Recursively build a ``sqlglot.exp.Expr`` node for ``expr``."""
        if isinstance(expr, BinaryComparison):
            col_expr = self._build_column(expr.column)
            lit_expr = self._build_literal(expr.literal)
            lhs, rhs = (col_expr, lit_expr) if expr.lhs_is_column else (lit_expr, col_expr)
            if expr.op == "=":
                return exp.EQ(this=lhs, expression=rhs)
            if expr.op == "!=":
                return exp.Var(this=f"{lhs.sql(self._dialect)} != {rhs.sql(self._dialect)}")
            if expr.op == ">":
                return exp.GT(this=lhs, expression=rhs)
            if expr.op == ">=":
                return exp.GTE(this=lhs, expression=rhs)
            if expr.op == "<":
                return exp.LT(this=lhs, expression=rhs)
            return exp.LTE(this=lhs, expression=rhs)

        if isinstance(expr, InListPredicate):
            col_expr = self._build_column(expr.column)
            val_exprs = [self._build_literal(v) for v in expr.values]
            if expr.negated:
                vals_sql = ", ".join(v.sql(self._dialect) for v in val_exprs)
                return exp.Var(this=f"{col_expr.sql(self._dialect)} NOT IN ({vals_sql})")
            return exp.In(this=col_expr, expressions=val_exprs)

        if isinstance(expr, NullCheckPredicate):
            col_expr = self._build_column(expr.column)
            if expr.is_not_null:
                return exp.Is(this=col_expr, expression=exp.Not(this=exp.Null()))
            return exp.Is(this=col_expr, expression=exp.Null())

        if isinstance(expr, LogicalAnd):
            combined = self.build(expr.children[0])
            for child in expr.children[1:]:
                combined = exp.And(this=combined, expression=self.build(child))
            return exp.Paren(this=combined)

        if isinstance(expr, LogicalOr):
            combined = self.build(expr.children[0])
            for child in expr.children[1:]:
                combined = exp.Or(this=combined, expression=self.build(child))
            return exp.Paren(this=combined)

        if isinstance(expr, LogicalNot):
            return exp.Paren(this=exp.Not(this=self.build(expr.child)))

        raise PredicateOffloadException(f"Unsupported predicate node: {to_dsl(expr)}")

    def _build_column(self, col: ColumnRef) -> exp.Column:
        if col.alias:
            return exp.Column(
                this=exp.Identifier(this=col.name, quoted=self._quote_identifiers),
                table=exp.Identifier(this=col.alias, quoted=self._quote_identifiers),
            )
        return exp.Column(this=exp.Identifier(this=col.name, quoted=self._quote_identifiers))

    def _build_literal(self, lit: LiteralValue) -> exp.Expr:
        val = lit.value
        kind = val.kind

        if kind == "raw_sql":
            return exp.Var(this=val.text)

        if kind in ("integer", "decimal"):
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(val.raw))
            if (
                self._dialect == "bigquery"
                and kind == "decimal"
                and lit.data_type in (BIGQUERY_TYPE_NUMERIC, BIGQUERY_TYPE_BIGNUMERIC)
            ):
                return exp.Var(this=f"{lit.data_type} '{val.text}'")
            return exp.Literal(this=val.text, is_string=False)

        if kind == "string":
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(val.text))
            if self._dialect == "tsql" and lit.data_type in (SYNAPSE_TYPE_NCHAR, SYNAPSE_TYPE_NVARCHAR):
                escaped = val.text.replace("'", "''")
                return exp.Var(this=f"N'{escaped}'")
            return exp.Literal.string(val.text)

        if kind == "bytes":
            raw_bytes = val.raw
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(raw_bytes))
            return exp.Literal.string(val.text)

        return self._build_datetime_literal(lit)

    def _build_datetime_literal(self, lit: LiteralValue) -> exp.Expr:
        val = lit.value
        data_type = lit.data_type
        dt64 = np.datetime64(val.text.replace(" ", "T"))

        if self._dialect == "oracle":
            if data_type == ORACLE_TYPE_DATE or (data_type is None and val.kind == "date"):
                str_val = np.datetime_as_string(dt64, unit="s").replace("T", " ")
                target_expr = (
                    self._placeholder(self._next_bind(str_val))
                    if self._bind_style is not None
                    else exp.Literal.string(str_val)
                )
                return exp.Anonymous(
                    this="TO_DATE",
                    expressions=[target_expr, exp.Literal.string("YYYY-MM-DD HH24:MI:SS")],
                )
            if data_type in (ORACLE_TYPE_TIMESTAMP, ORACLE_TYPE_TIMESTAMP_TZ) or data_type is None:
                str_val = np.datetime_as_string(dt64, unit="ns").replace("T", " ")
                if self._bind_style is not None:
                    bind_expr = self._placeholder(self._next_bind(str_val))
                    return exp.Anonymous(
                        this="TO_TIMESTAMP",
                        expressions=[bind_expr, exp.Literal.string("YYYY-MM-DD HH24:MI:SS.FF9")],
                    )
                return exp.Var(this=f"TIMESTAMP '{str_val}'")
            raise OptionValueError(f"datetime is not compatible with column data type {data_type}")

        if self._dialect == "bigquery":
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(val.text))
            return exp.Var(this=BigQueryLiteral.format_literal(dt64, data_type))

        if self._dialect == "snowflake":
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(val.text))
            if data_type == SNOWFLAKE_TYPE_DATE or (data_type is None and " " not in val.text):
                return exp.Var(this=f"'{val.text[:10]}'::{SNOWFLAKE_TYPE_DATE}")
            if data_type == SNOWFLAKE_TYPE_TIME:
                time_part = val.text[11:] if len(val.text) > 10 else "00:00:00"
                return exp.Var(this=f"'{time_part}'::{SNOWFLAKE_TYPE_TIME}")
            sf_type = (
                data_type
                if data_type in (SNOWFLAKE_TYPE_TIMESTAMP_NTZ, "TIMESTAMP_LTZ", SNOWFLAKE_TYPE_TIMESTAMP_TZ)
                else SNOWFLAKE_TYPE_TIMESTAMP_NTZ
            )
            return exp.Var(this=f"'{val.text}'::{sf_type}")

        if self._dialect == "tsql":
            ts_text = val.text[:27] if "." in val.text and len(val.text) > 27 else val.text
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(ts_text))
            return exp.Literal.string(ts_text)

        if self._dialect in ("hive", "spark"):
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(dt64))
            return exp.Literal.string(val.text)

        if self._dialect == "duckdb":
            if self._bind_style is not None:
                return self._placeholder(self._next_bind(val.text))
            if data_type == "DATE" or (data_type is None and val.kind == "date"):
                return exp.Var(this=f"DATE '{val.text[:10]}'")
            return exp.Var(this=f"TIMESTAMP '{val.text}'")

        raise PredicateOffloadException(f"Unsupported predicate dialect: {self._dialect}")

    def _next_bind(self, value: Any) -> str:
        bind_name = f"bind_{len(self.binds)}"
        self.binds[bind_name] = value
        return bind_name

    def _placeholder(self, bind_name: str) -> exp.Expr:
        if self._bind_style == "named_colon":
            return exp.Var(this=f":{bind_name}")
        if self._bind_style == "named_at":
            return exp.Parameter(this=exp.Var(this=bind_name))
        if self._bind_style == "pyformat":
            return exp.Var(this=f"%({bind_name})s")
        if self._bind_style == "dollar":
            return exp.Var(this=f"${bind_name}")
        return exp.Placeholder()


def _ensure_resolved(
    expr: Any,
    columns: Sequence[ColumnSpec],
) -> PredicateExpr:
    """Resolve column types on ``expr`` if any comparison literal lacks ``data_type``."""
    if isinstance(expr, str):
        expr = parse_predicate_dsl(expr)
    elif hasattr(expr, "ast"):
        expr = expr.ast
    if not columns or not _needs_resolution(expr):
        return expr
    return resolve_predicate_types(expr, columns, include_synthetic=False)


def _needs_resolution(expr: PredicateExpr) -> bool:
    """Return True if any comparison literal in ``expr`` has ``data_type is None``."""
    if isinstance(expr, BinaryComparison):
        return expr.literal.data_type is None and expr.literal.value.kind != "raw_sql"
    if isinstance(expr, InListPredicate):
        return any(v.data_type is None and v.value.kind != "raw_sql" for v in expr.values)
    if isinstance(expr, NullCheckPredicate):
        return False
    if isinstance(expr, (LogicalAnd, LogicalOr)):
        return any(_needs_resolution(c) for c in expr.children)
    return _needs_resolution(expr.child)
