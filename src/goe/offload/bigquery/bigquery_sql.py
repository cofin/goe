# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Encapsulated sqlglot implementation of BigQueryDialectEngineProtocol."""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import sqlglot
from sqlglot import exp
from sqlglot.dialects.bigquery import BigQuery
from sqlglot.tokenizer_core import TokenType

from goe.offload.bigquery.bigquery_column import (
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_TIMESTAMP,
)
from goe.offload.offload_constants import (
    PART_COL_GRANULARITY_DAY,
    PART_COL_GRANULARITY_MONTH,
    PART_COL_GRANULARITY_YEAR,
)
from goe.offload.sql_engine import BigQueryDialectEngineProtocol

if TYPE_CHECKING:
    from goe.offload.column_metadata import ColumnMetadataInterface

__all__ = [
    "BigQuerySqlEngine",
    "get_bigquery_dialect_engine",
]

_GRANULARITY_UNITS: dict[str, str] = {
    PART_COL_GRANULARITY_YEAR: "YEAR",
    PART_COL_GRANULARITY_MONTH: "MONTH",
    PART_COL_GRANULARITY_DAY: "DAY",
}

_TRUNC_FUNCTIONS: dict[str, str] = {
    BIGQUERY_TYPE_DATE: "DATE_TRUNC",
    BIGQUERY_TYPE_DATETIME: "DATETIME_TRUNC",
    BIGQUERY_TYPE_TIMESTAMP: "TIMESTAMP_TRUNC",
}


class BigQuerySqlEngine(BigQueryDialectEngineProtocol):
    """BigQuery DDL/DML SQL generator backed by sqlglot AST nodes."""

    def partition_by_clause(self, partition_column: "ColumnMetadataInterface") -> str:
        """Render the BigQuery PARTITION BY expression for a partition column."""
        pinfo = partition_column.partition_info
        assert pinfo is not None
        col_ident = exp.Column(this=exp.Identifier(this=partition_column.name, quoted=True))
        if partition_column.data_type in _TRUNC_FUNCTIONS:
            if pinfo.granularity not in _GRANULARITY_UNITS:
                raise NotImplementedError(
                    f"BigQuery table partitioning not implemented for data type/granularity: "
                    f"{partition_column.data_type}/{pinfo.granularity}"
                )
            if pinfo.granularity == PART_COL_GRANULARITY_DAY and partition_column.data_type == BIGQUERY_TYPE_DATE:
                return col_ident.sql("bigquery")
            unit = _GRANULARITY_UNITS[pinfo.granularity]
            func_node = exp.Anonymous(
                this=_TRUNC_FUNCTIONS[partition_column.data_type],
                expressions=[col_ident, exp.Var(this=unit)],
            )
            return func_node.sql("bigquery")
        if partition_column.data_type == BIGQUERY_TYPE_INT64:
            assert pinfo.range_start is not None
            assert pinfo.range_end is not None
            assert pinfo.granularity is not None
            gen_array = exp.Anonymous(
                this="GENERATE_ARRAY",
                expressions=[
                    exp.Literal.number(pinfo.range_start),
                    exp.Literal.number(pinfo.range_end),
                    exp.Literal.number(pinfo.granularity),
                ],
            )
            bucket_node = exp.Anonymous(this="RANGE_BUCKET", expressions=[col_ident, gen_array])
            return bucket_node.sql("bigquery")
        raise NotImplementedError(
            f"BigQuery table partitioning not implemented for data type:{partition_column.data_type}"
        )

    def properties_clause(
        self,
        *,
        partition_expr_sql: str | None = None,
        cluster_cols: Sequence[str] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> str:
        """Render the BigQuery PARTITION BY / CLUSTER BY / OPTIONS clause."""
        props = self._build_properties(
            partition_expr_sql=partition_expr_sql,
            cluster_cols=cluster_cols,
            options=options,
        )
        if not props:
            return ""
        return exp.Properties(expressions=props).sql("bigquery")

    def create_table(
        self,
        *,
        project: str | None,
        db_name: str,
        table_name: str,
        columns: Sequence["ColumnMetadataInterface"],
        partition_expr_sql: str | None = None,
        cluster_cols: Sequence[str] | None = None,
        options: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> str:
        """Render a BigQuery CREATE [OR REPLACE] TABLE statement."""
        table_node = self._table(project, db_name, table_name)
        col_defs = [self._column_def(col) for col in columns]
        props = self._build_properties(
            partition_expr_sql=partition_expr_sql,
            cluster_cols=cluster_cols,
            options=options,
        )
        create_node = exp.Create(
            this=exp.Schema(this=table_node, expressions=col_defs),
            kind="TABLE",
            replace=replace,
            properties=exp.Properties(expressions=props) if props else None,
        )
        return create_node.sql("bigquery")

    def create_external_table(
        self,
        *,
        project: str | None,
        db_name: str,
        table_name: str,
        columns: Sequence["ColumnMetadataInterface"] | None = None,
        storage_format: str = "PARQUET",
        uris: Sequence[str] = (),
        extra_options: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> str:
        """Render a BigQuery CREATE [OR REPLACE] EXTERNAL TABLE statement."""
        merged_options: dict[str, Any] = {"format": storage_format}
        if extra_options:
            merged_options.update(extra_options)
        merged_options["uris"] = list(uris)
        table_node = self._table(project, db_name, table_name)
        this_node: exp.Expr = (
            exp.Schema(this=table_node, expressions=[self._column_def(col) for col in columns])
            if columns
            else table_node
        )
        props = self._build_properties(options=merged_options)
        create_node = exp.Create(
            this=this_node,
            kind="EXTERNAL TABLE",
            replace=replace,
            properties=exp.Properties(expressions=props),
        )
        return create_node.sql("bigquery")

    def create_or_replace_ddl(self, ddl: str) -> str:
        """Rewrite a BigQuery CREATE TABLE DDL string to CREATE OR REPLACE TABLE via lexical tokenization."""
        tokens = BigQuery().tokenize(ddl)
        if len(tokens) >= 2 and tokens[0].token_type == TokenType.CREATE and tokens[1].token_type == TokenType.TABLE:
            return f"CREATE OR REPLACE TABLE{ddl[tokens[1].end + 1 :]}"
        return ddl

    def ctas(
        self,
        *,
        project: str | None,
        db_name: str,
        table_name: str,
        from_project: str | None = None,
        from_db_name: str | None = None,
        from_table_name: str | None = None,
        select_expr_tuples: Sequence[tuple[Any, str]] | None = None,
        options: Mapping[str, Any] | None = None,
        row_limit: int | None = None,
        replace: bool = False,
    ) -> str:
        """Render a BigQuery CREATE [OR REPLACE] TABLE ... AS SELECT statement."""
        target_table = self._table(project, db_name, table_name)
        if select_expr_tuples:
            projections: list[exp.Expr] = [
                exp.alias_(exp.Var(this=str(expr_sql)), alias_name, quoted=True, copy=False)
                for expr_sql, alias_name in select_expr_tuples
            ]
        else:
            projections = [exp.Star()]
        select_node = exp.select(*projections, copy=False)
        if from_db_name and from_table_name:
            source_table = self._table(from_project, from_db_name, from_table_name)
            select_node = select_node.from_(source_table, copy=False)
        if row_limit is not None:
            select_node = select_node.limit(int(row_limit), copy=False)
        props = self._build_properties(options=options)
        create_node = exp.Create(
            this=target_table,
            kind="TABLE",
            replace=replace,
            properties=exp.Properties(expressions=props) if props else None,
            expression=select_node,
        )
        return create_node.sql("bigquery")

    def insert_select(
        self,
        *,
        project: str | None,
        db_name: str,
        table_name: str,
        select_expr_tuples: Sequence[tuple[Any, str]],
        insert_col_names: Sequence[str] | None = None,
        from_project: str | None = None,
        from_db_name: str | None = None,
        from_table_name: str | None = None,
        from_object_override: str | None = None,
        where_clauses: Sequence[str] | None = None,
    ) -> str:
        """Render a BigQuery INSERT INTO ... SELECT statement."""
        target_table = self._table(project, db_name, table_name)
        this_node: exp.Expr = (
            exp.Schema(this=target_table, expressions=[exp.Identifier(this=c, quoted=True) for c in insert_col_names])
            if insert_col_names
            else target_table
        )
        projections: list[exp.Expr] = [
            exp.alias_(exp.Var(this=str(expr_sql)), alias_name, quoted=True, copy=False)
            for expr_sql, alias_name in select_expr_tuples
        ]
        from_expr: exp.Expr
        if from_object_override:
            from_expr = exp.Var(this=from_object_override)
        else:
            assert from_db_name is not None and from_table_name is not None
            from_expr = self._table(from_project, from_db_name, from_table_name)
        select_node = exp.select(*projections, copy=False).from_(from_expr, copy=False)
        if where_clauses:
            combined_where: exp.Expr | None = None
            for clause in where_clauses:
                wrapped = exp.Paren(this=exp.Var(this=clause))
                combined_where = wrapped if combined_where is None else exp.And(this=combined_where, expression=wrapped)
            if combined_where is not None:
                select_node = select_node.where(combined_where, copy=False)
        insert_node = exp.Insert(
            this=this_node,
            expression=select_node,
        )
        return insert_node.sql("bigquery")

    def alter_add_columns(
        self,
        *,
        project: str | None,
        db_name: str,
        table_name: str,
        column_name_type_pairs: Sequence[tuple[str, str]],
    ) -> str:
        """Render a BigQuery ALTER TABLE ... ADD COLUMN IF NOT EXISTS statement."""
        target_table = self._table(project, db_name, table_name)
        actions = [
            exp.ColumnDef(
                this=exp.Identifier(this=col_name, quoted=True),
                kind=exp.DataType.build(col_type, dialect="bigquery"),
                exists=True,
            )
            for col_name, col_type in column_name_type_pairs
        ]
        alter_node = exp.Alter(this=target_table, kind="TABLE", actions=actions)
        return alter_node.sql("bigquery")

    def create_view(
        self,
        *,
        project: str | None,
        db_name: str,
        view_name: str,
        select_expr_tuples: Sequence[tuple[Any, str]],
        from_tables: str,
        where_clauses: Sequence[str] | None = None,
        replace: bool = False,
    ) -> str:
        """Render a BigQuery CREATE [OR REPLACE] VIEW statement."""
        view_table = self._table(project, db_name, view_name)
        projections: list[exp.Expr] = [
            exp.alias_(exp.Var(this=str(expr_sql)), alias_name, quoted=True, copy=False)
            for expr_sql, alias_name in select_expr_tuples
        ]
        select_node = exp.select(*projections, copy=False).from_(exp.Var(this=from_tables), copy=False)
        if where_clauses:
            combined_where: exp.Expr | None = None
            for clause in where_clauses:
                wrapped = exp.Paren(this=exp.Var(this=clause))
                combined_where = wrapped if combined_where is None else exp.And(this=combined_where, expression=wrapped)
            if combined_where is not None:
                select_node = select_node.where(combined_where, copy=False)
        create_node = exp.Create(
            this=view_table,
            kind="VIEW",
            replace=replace,
            expression=select_node,
        )
        return create_node.sql("bigquery")

    @staticmethod
    def _table(project: str | None, db_name: str, table_name: str) -> exp.Table:
        """Build a backtick-quoted BigQuery table AST node."""
        return exp.Table(
            this=exp.Identifier(this=table_name, quoted=True),
            db=exp.Identifier(this=db_name, quoted=True),
            catalog=exp.Identifier(this=project, quoted=True) if project else None,
        )

    @staticmethod
    def _column_def(col: "ColumnMetadataInterface") -> exp.ColumnDef:
        """Build a BigQuery ColumnDef AST node from a GOE column metadata object."""
        constraints = [exp.ColumnConstraint(kind=exp.NotNullColumnConstraint())] if col.nullable is False else None
        return exp.ColumnDef(
            this=exp.Identifier(this=col.name, quoted=True),
            kind=exp.DataType.build(col.format_data_type(), dialect="bigquery"),
            constraints=constraints,
        )

    @staticmethod
    def _option_value(val: Any) -> exp.Expr:
        """Convert a Python option value into a safe BigQuery literal or array AST node."""
        if isinstance(val, bool):
            return exp.Boolean(this=val)
        if isinstance(val, int):
            return exp.Literal.number(val)
        if isinstance(val, str):
            unquoted = val[1:-1] if len(val) >= 2 and val.startswith("'") and val.endswith("'") else val
            return exp.Literal.string(unquoted)
        if isinstance(val, Sequence):
            return exp.Array(expressions=[BigQuerySqlEngine._option_value(item) for item in val])
        return exp.Literal.string(str(val))

    @classmethod
    def _build_properties(
        cls,
        *,
        partition_expr_sql: str | None = None,
        cluster_cols: Sequence[str] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> list[exp.Expr]:
        """Construct PartitionedByProperty, Cluster, and Property AST nodes."""
        props: list[exp.Expr] = []
        if partition_expr_sql:
            props.append(
                exp.PartitionedByProperty(
                    this=sqlglot.parse_one(partition_expr_sql, read="bigquery"),
                )
            )
        if cluster_cols:
            props.append(
                exp.Cluster(
                    expressions=[exp.Column(this=exp.Identifier(this=c, quoted=True)) for c in cluster_cols],
                )
            )
        if options:
            for key, val in options.items():
                props.append(exp.Property(this=exp.Var(this=key), value=cls._option_value(val)))
        return props


@lru_cache(maxsize=1)
def get_bigquery_dialect_engine() -> BigQueryDialectEngineProtocol:
    """Return the singleton BigQueryDialectEngineProtocol instance."""
    return BigQuerySqlEngine()
