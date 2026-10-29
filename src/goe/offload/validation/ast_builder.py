# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Dialect-aware cross-DB validation query builder backed by DialectSqlEngine."""

from collections.abc import Sequence
from typing import Any, Literal

from goe.offload.predicates import (
    BindStyle,
    PredicateCompiler,
    PredicateDialect,
    PredicateExpr,
)
from goe.offload.sql_ast.dialect_engine import (
    SqlDialect,
    TableRef,
    get_dialect_engine,
)
from goe.typing import FrozenBaseStruct

__all__ = (
    "MAX_AGGREGATES_PER_QUERY",
    "AggregateFunc",
    "AggregateQuestion",
    "CrossDbValidationBuilder",
    "ValidationBatchQuery",
)

MAX_AGGREGATES_PER_QUERY: int = 64

type AggregateFunc = Literal["COUNT", "MIN", "MAX", "SUM", "AVG", "STDDEV", "HASH_XOR"]

_PREDICATE_DIALECT_FALLBACK: dict[str, PredicateDialect] = {
    "oracle": "oracle",
    "bigquery": "bigquery",
    "snowflake": "snowflake",
    "tsql": "tsql",
    "hive": "hive",
    "spark": "spark",
    "impala": "hive",
    "teradata": "oracle",
    "duckdb": "duckdb",
}
_BIND_STYLE_BY_DIALECT: dict[str, BindStyle] = {
    "oracle": "named_colon",
    "bigquery": "named_at",
    "snowflake": "named_colon",
    "tsql": "named_colon",
    "hive": "named_colon",
    "spark": "named_colon",
    "impala": "named_colon",
    "teradata": "named_colon",
    "duckdb": "dollar",
}


class AggregateQuestion(FrozenBaseStruct, frozen=True):
    """Single column aggregate specification."""

    column: str | None
    func: AggregateFunc
    alias: str
    approximate: bool = False


class ValidationBatchQuery(FrozenBaseStruct, frozen=True):
    """Compiled validation SQL batch with parameter bindings and ordered aliases."""

    sql: str
    parameters: dict[str, Any]
    aliases: tuple[str, ...]
    group_bys: tuple[str, ...]


class CrossDbValidationBuilder:
    """Construct batched cross-DB aggregate and sample-hash SQL via DialectSqlEngine."""

    def __init__(self, dialect: SqlDialect) -> None:
        self._dialect = dialect
        self._engine = get_dialect_engine(dialect)

    @property
    def dialect(self) -> SqlDialect:
        """Return the target SQL dialect."""
        return self._dialect

    def build_aggregate_batches(
        self,
        *,
        schema: str,
        table: str,
        questions: Sequence[AggregateQuestion],
        group_bys: Sequence[str] = (),
        predicate: PredicateExpr | None = None,
        extra_where: Sequence[str] = (),
        as_of_scn: int | None = None,
        parallelism: int | None = None,
        bind_parameters: bool = False,
        max_aggregates: int = MAX_AGGREGATES_PER_QUERY,
    ) -> list[ValidationBatchQuery]:
        """Build 1..N batched aggregate queries chunked by max_aggregates."""
        if not questions:
            return []

        where_clauses, params = self._compile_where_clauses(
            predicate=predicate,
            extra_where=extra_where,
            as_of_scn=as_of_scn,
            bind_parameters=bind_parameters,
        )
        table_ref = TableRef(name=table, schema=schema)
        as_of_scn_bind = self._dialect == "oracle" and as_of_scn is not None
        batches: list[ValidationBatchQuery] = []
        for idx in range(0, len(questions), max_aggregates):
            chunk = questions[idx : idx + max_aggregates]
            sql = self._engine.validation_aggregate_query(
                table=table_ref,
                questions=[(q.column, q.func, q.alias) for q in chunk],
                group_bys=group_bys,
                where_clauses=where_clauses,
                as_of_scn_bind=as_of_scn_bind,
                parallelism=parallelism,
            )
            batches.append(
                ValidationBatchQuery(
                    sql=sql,
                    parameters=dict(params),
                    aliases=tuple(q.alias for q in chunk),
                    group_bys=tuple(group_bys),
                )
            )
        return batches

    def build_sample_hash_query(
        self,
        *,
        schema: str,
        table: str,
        key_columns: Sequence[str],
        value_columns: Sequence[str],
        predicate: PredicateExpr | None = None,
        extra_where: Sequence[str] = (),
        as_of_scn: int | None = None,
        bind_parameters: bool = False,
    ) -> ValidationBatchQuery:
        """Build a sample row-level hash aggregate query."""
        where_clauses, params = self._compile_where_clauses(
            predicate=predicate,
            extra_where=extra_where,
            as_of_scn=as_of_scn,
            bind_parameters=bind_parameters,
        )
        sql = self._engine.validation_sample_hash_query(
            table=TableRef(name=table, schema=schema),
            key_columns=key_columns,
            value_columns=value_columns,
            where_clauses=where_clauses,
            as_of_scn_bind=(self._dialect == "oracle" and as_of_scn is not None),
        )
        return ValidationBatchQuery(
            sql=sql,
            parameters=params,
            aliases=("ROW_HASH_AGG",),
            group_bys=(),
        )

    def parse_filter_clause(
        self,
        raw_filter: str,
        *,
        source_dialect: SqlDialect = "oracle",
        quote_identifiers: bool = False,
    ) -> str:
        """Parse and validate a raw filter clause and render it in the target dialect."""
        return self._engine.transpile_safe_filter(
            raw_filter,
            source_dialect=source_dialect,
            quote_identifiers=quote_identifiers,
        )

    def parse_filter_tuples(
        self,
        raw_filter: str,
        *,
        source_dialect: SqlDialect = "oracle",
    ) -> list[tuple[str, str, Any] | str]:
        """Parse comma-separated or single filter clauses into validated comparison tuples or clauses."""
        return self._engine.parse_filter_tuples(raw_filter, source_dialect=source_dialect)

    def _compile_where_clauses(
        self,
        *,
        predicate: PredicateExpr | None,
        extra_where: Sequence[str],
        as_of_scn: int | None,
        bind_parameters: bool,
    ) -> tuple[list[str], dict[str, Any]]:
        """Compile predicate AST and extra WHERE strings into SQL clauses and parameters."""
        params: dict[str, Any] = {}
        where_clauses: list[str] = []
        if predicate is not None:
            pred_dialect: PredicateDialect = _PREDICATE_DIALECT_FALLBACK.get(self._dialect, "oracle")
            bind_style: BindStyle | None = _BIND_STYLE_BY_DIALECT[self._dialect] if bind_parameters else None
            compiled = PredicateCompiler.render(
                predicate,
                pred_dialect,
                bind_style=bind_style,
                quote_identifiers=True,
            )
            where_clauses.append(compiled.sql)
            params.update(compiled.params)
        for clause in extra_where:
            if clause.strip():
                where_clauses.append(clause.strip())
        if self._dialect == "oracle" and as_of_scn is not None:
            params["scn"] = as_of_scn
        return where_clauses, params
