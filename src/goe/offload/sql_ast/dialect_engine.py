# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Dialect-aware SQL AST builders backed by native sqlglot generation."""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

import sqlglot
from sqlglot import exp
from sqlglot.dialects.bigquery import BigQuery
from sqlglot.tokenizer_core import TokenType

from goe.exceptions import GOEError, ValidationError
from goe.offload.offload_constants import (
    PART_COL_GRANULARITY_DAY,
    PART_COL_GRANULARITY_MONTH,
    PART_COL_GRANULARITY_YEAR,
)
from goe.offload.schema.column_spec import (
    BIGQUERY_TYPE_DATE,
    BIGQUERY_TYPE_DATETIME,
    BIGQUERY_TYPE_INT64,
    BIGQUERY_TYPE_TIMESTAMP,
)
from goe.typing import FrozenBaseStruct

if TYPE_CHECKING:
    from goe.offload.schema.column_spec import ColumnSpec

__all__ = (
    "DialectNotSupportedError",
    "DialectSqlEngine",
    "SqlDialect",
    "TableRef",
    "get_dialect_engine",
)

type SqlDialect = Literal["oracle", "bigquery", "snowflake", "tsql", "hive", "spark", "impala", "teradata", "duckdb"]

_ALTER_DIALECTS: frozenset[str] = frozenset({"bigquery", "snowflake", "tsql"})
_ALTER_COLUMN_DIALECTS: frozenset[str] = frozenset({"bigquery", "snowflake"})
_IF_NOT_EXISTS_DIALECTS: frozenset[str] = frozenset({"bigquery", "snowflake"})
_FORBIDDEN_FILTER_NODES: tuple[type[exp.Expr], ...] = (
    exp.Select,
    exp.Subquery,
    exp.Table,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.Exists,
    exp.DDL,
    exp.DML,
    exp.Command,
)
_ALLOWED_FILTER_ANONYMOUS: frozenset[str] = frozenset(
    {
        "TO_DATE",
        "TO_TIMESTAMP",
        "TO_CHAR",
        "TO_NUMBER",
        "NVL",
        "COALESCE",
        "TRUNC",
        "UPPER",
        "LOWER",
        "SUBSTR",
        "LENGTH",
    }
)


class DialectNotSupportedError(GOEError):
    """Raised when a SQL builder is called for a dialect it does not support."""


class TableRef(FrozenBaseStruct, frozen=True):
    """Qualified table reference whose parts are always rendered as quoted identifiers."""

    name: str
    schema: str | None = None
    catalog: str | None = None


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


class DialectSqlEngine:
    """Dialect-aware SQL AST builder backed by native sqlglot generation."""

    def __init__(self, dialect: SqlDialect) -> None:
        """Initialize the SQL AST engine for a target dialect."""
        self._dialect: SqlDialect = dialect

    @property
    def dialect(self) -> SqlDialect:
        """Return the dialect configured for this engine."""
        return self._dialect

    def snapshot_scn_clause(self, transport_scn: int | None) -> str:
        """Render an Oracle AS OF SCN clause from an integer SCN."""
        self._require("snapshot_scn_clause", "oracle")
        version = self._version_node(transport_scn)
        return version.sql(self._dialect) if version is not None else ""

    def iot_partition_clause(self, partition_name: str | None) -> str:
        """Render an Oracle PARTITION("name") clause for an index-organized table."""
        self._require("iot_partition_clause", "oracle")
        if not partition_name:
            return ""
        part = self._partition_node([partition_name], is_subpartition=False, quoted=True)
        assert part is not None
        return part.sql(self._dialect)

    def table_from_clause(
        self,
        *,
        owner: str,
        table_name: str,
        alias: str | None = "g",
        partition_names: Sequence[str] | None = None,
        is_subpartition: bool = False,
        transport_scn: int | None = None,
    ) -> str:
        """Render an Oracle table reference with optional PARTITION/SUBPARTITION and AS OF SCN clauses."""
        self._require("table_from_clause", "oracle")
        return self._oracle_table_node(
            owner=owner,
            table_name=table_name,
            alias=alias,
            partition_names=partition_names,
            is_subpartition=is_subpartition,
            transport_scn=transport_scn,
        ).sql(self._dialect)

    def id_range_query(
        self,
        *,
        owner: str,
        table_name: str,
        id_col_name: str,
        iot_partition_name: str | None = None,
        where_clause: str = "",
    ) -> str:
        """Render an Oracle MIN/MAX ID range query structured for index full scan (min/max)."""
        self._require("id_range_query", "oracle")
        base_table = self._oracle_table_node(
            owner=owner,
            table_name=table_name,
            alias=None,
            partition_names=[iot_partition_name] if iot_partition_name else None,
        )
        min_select = exp.select(
            exp.alias_(exp.Min(this=exp.Var(this=id_col_name)), "val", copy=False),
            copy=False,
        ).from_(base_table.copy(), copy=False)
        max_select = exp.select(
            exp.alias_(exp.Max(this=exp.Var(this=id_col_name)), "val", copy=False),
            copy=False,
        ).from_(base_table.copy(), copy=False)
        if where_clause:
            min_select = min_select.where(exp.Var(this=where_clause), copy=False)
            max_select = max_select.where(exp.Var(this=where_clause), copy=False)
        outer = (
            exp.select(exp.Var(this="min_v.val"), exp.Var(this="max_v.val"), copy=False)
            .from_(exp.Subquery(this=min_select, alias=exp.TableAlias(this=exp.Var(this="min_v"))), copy=False)
            .join(
                exp.Subquery(this=max_select, alias=exp.TableAlias(this=exp.Var(this="max_v"))),
                join_type="CROSS",
                copy=False,
            )
        )
        return outer.sql(self._dialect).replace(" CROSS JOIN ", ", ")

    def partition_split_branch_query(
        self,
        *,
        owner: str,
        table_name: str,
        partition_name: str,
        is_subpartition: bool,
        transport_scn: int | None,
        batch: int,
        batch_col: str,
    ) -> str:
        """Render a single UNION ALL branch for SPLIT_BY_PARTITION or SPLIT_BY_SUBPARTITION."""
        self._require("partition_split_branch_query", "oracle")
        table_node = self._oracle_table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[partition_name],
            is_subpartition=is_subpartition,
            transport_scn=transport_scn,
        )
        select_node = exp.select(
            exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
            exp.alias_(exp.Literal.number(batch), batch_col, copy=False),
            copy=False,
        ).from_(table_node, copy=False)
        return select_node.sql(self._dialect)

    def extent_split_branch_query(
        self,
        *,
        owner: str,
        table_name: str,
        transport_scn: int | None,
        partition_param: str,
        subpartition_param: str,
        degree: int,
        batch: int,
        batch_col: str,
        where_clause: str = "",
    ) -> str:
        """Render a single UNION ALL branch for SPLIT_BY_EXTENT using offload.offload_rowid_ranges."""
        self._require("extent_split_branch_query", "oracle")
        from_table = self.table_from_clause(
            owner=owner,
            table_name=table_name,
            alias="g",
            transport_scn=transport_scn,
        )
        rowid_fn = (
            f"TABLE(offload.offload_rowid_ranges('{owner.upper()}', '{table_name.upper()}', "
            f"{partition_param}, {subpartition_param}, {degree}, {batch})) r"
        )
        where_sql = "g.rowid BETWEEN CHARTOROWID(r.min_rowid_vc) and CHARTOROWID(r.max_rowid_vc)"
        if where_clause:
            where_sql = f"{where_sql} AND ({where_clause})"
        return (
            f"SELECT /*+ NO_INDEX(g) USE_NL(g) LEADING(r) */ g.*, {batch} AS {batch_col} "
            f"FROM {from_table}, {rowid_fn} WHERE {where_sql}"
        )

    def mod_split_query(
        self,
        *,
        owner: str,
        table_name: str,
        mod_column: str,
        degree: int,
        batch_col: str,
        iot_partition_name: str | None = None,
        transport_scn: int | None = None,
        where_clause: str = "",
    ) -> str:
        """Render an Oracle SPLIT_BY_MOD extraction query using MOD(ORA_HASH(col), degree)."""
        self._require("mod_split_query", "oracle")
        table_node = self._oracle_table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[iot_partition_name] if iot_partition_name else None,
            transport_scn=transport_scn,
        )
        mod_expr = exp.Anonymous(
            this="MOD",
            expressions=[
                exp.Anonymous(this="ORA_HASH", expressions=[exp.Var(this=mod_column)]),
                exp.Literal.number(degree),
            ],
        )
        select_node = exp.select(
            exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
            exp.alias_(mod_expr, batch_col, copy=False),
            copy=False,
        ).from_(table_node, copy=False)
        if where_clause:
            select_node = select_node.where(exp.Paren(this=exp.Var(this=where_clause)), copy=False)
        return select_node.sql(self._dialect)

    def native_range_split_query(
        self,
        *,
        owner: str,
        table_name: str,
        id_col_sql: str,
        batch_col: str,
        iot_partition_name: str | None = None,
        transport_scn: int | None = None,
        where_clause: str = "",
    ) -> str:
        """Render an Oracle SPLIT_BY_NATIVE_RANGE extraction query."""
        self._require("native_range_split_query", "oracle")
        table_node = self._oracle_table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[iot_partition_name] if iot_partition_name else None,
            transport_scn=transport_scn,
        )
        select_node = exp.select(
            exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
            exp.alias_(exp.Var(this=id_col_sql), batch_col, copy=False),
            copy=False,
        ).from_(table_node, copy=False)
        if where_clause:
            select_node = select_node.where(exp.Paren(this=exp.Var(this=where_clause)), copy=False)
        return select_node.sql(self._dialect)

    def id_range_split_branch_query(
        self,
        *,
        owner: str,
        table_name: str,
        id_col_name: str,
        low_val: Any,
        high_val: Any,
        batch: int,
        batch_col: str,
        iot_partition_name: str | None = None,
        transport_scn: int | None = None,
        where_clause: str = "",
    ) -> str:
        """Render a single UNION ALL branch for SPLIT_BY_ID_RANGE."""
        self._require("id_range_split_branch_query", "oracle")
        table_node = self._oracle_table_node(
            owner=owner,
            table_name=table_name,
            alias="g",
            partition_names=[iot_partition_name] if iot_partition_name else None,
            transport_scn=transport_scn,
        )
        range_cond: exp.Expr = exp.And(
            this=exp.GTE(this=exp.Var(this=id_col_name), expression=exp.Var(this=str(low_val))),
            expression=exp.LT(this=exp.Var(this=id_col_name), expression=exp.Var(this=str(high_val))),
        )
        if where_clause:
            range_cond = exp.And(this=range_cond, expression=exp.Paren(this=exp.Var(this=where_clause)))
        select_node = (
            exp.select(
                exp.Column(this=exp.Star(), table=exp.Identifier(this="g")),
                exp.alias_(exp.Literal.number(batch), batch_col, copy=False),
                copy=False,
            )
            .from_(table_node, copy=False)
            .where(range_cond, copy=False)
        )
        return select_node.sql(self._dialect)

    def parse_and_render(self, sql: str) -> str:
        """Parse a SQL query and render back to SQL for this dialect."""
        return sqlglot.parse_one(sql, read=self._dialect).sql(self._dialect)

    def partition_by_clause(self, partition_column: "ColumnSpec") -> str:
        """Render the BigQuery PARTITION BY expression for a partition column."""
        self._require("partition_by_clause", "bigquery")
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
        self._require("properties_clause", "bigquery")
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
        columns: "Sequence[ColumnSpec]",
        partition_expr_sql: str | None = None,
        cluster_cols: Sequence[str] | None = None,
        options: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> str:
        """Render a BigQuery CREATE [OR REPLACE] TABLE statement."""
        self._require("create_table", "bigquery")
        table_node = self._table_node(TableRef(name=table_name, schema=db_name, catalog=project))
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
        columns: "Sequence[ColumnSpec] | None" = None,
        storage_format: str = "PARQUET",
        uris: Sequence[str] = (),
        extra_options: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> str:
        """Render a BigQuery CREATE [OR REPLACE] EXTERNAL TABLE statement."""
        self._require("create_external_table", "bigquery")
        merged_options: dict[str, Any] = {"format": storage_format}
        if extra_options:
            merged_options.update(extra_options)
        merged_options["uris"] = list(uris)
        table_node = self._table_node(TableRef(name=table_name, schema=db_name, catalog=project))
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
        self._require("create_or_replace_ddl", "bigquery")
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
        self._require("ctas", "bigquery")
        target_table = self._table_node(TableRef(name=table_name, schema=db_name, catalog=project))
        if select_expr_tuples:
            projections: list[exp.Expr] = [
                exp.alias_(exp.Var(this=str(expr_sql)), alias_name, quoted=True, copy=False)
                for expr_sql, alias_name in select_expr_tuples
            ]
        else:
            projections = [exp.Star()]
        select_node = exp.select(*projections, copy=False)
        if from_db_name and from_table_name:
            source_table = self._table_node(TableRef(name=from_table_name, schema=from_db_name, catalog=from_project))
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
        self._require("insert_select", "bigquery")
        target_table = self._table_node(TableRef(name=table_name, schema=db_name, catalog=project))
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
            from_expr = self._table_node(TableRef(name=from_table_name, schema=from_db_name, catalog=from_project))
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
        self._require("create_view", "bigquery")
        view_table = self._table_node(TableRef(name=view_name, schema=db_name, catalog=project))
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

    def alter_add_columns(
        self,
        *,
        table: TableRef,
        columns: Sequence[tuple[str, str]],
        if_not_exists: bool = False,
    ) -> str:
        """Render ALTER TABLE ... ADD for one or more (name, type) pairs in this dialect."""
        self._require("alter_add_columns", *_ALTER_DIALECTS)
        if if_not_exists and self._dialect not in _IF_NOT_EXISTS_DIALECTS:
            raise DialectNotSupportedError(
                f"alter_add_columns with if_not_exists is not supported for dialect {self._dialect}"
            )
        actions = [
            exp.ColumnDef(
                this=exp.Identifier(this=name, quoted=True),
                kind=exp.DataType.build(data_type, dialect=self._dialect),
                exists=if_not_exists,
            )
            for name, data_type in columns
        ]
        return exp.Alter(this=self._table_node(table), kind="TABLE", actions=actions).sql(self._dialect)

    def alter_column_set_data_type(
        self,
        *,
        table: TableRef,
        column: str,
        data_type: str,
    ) -> str:
        """Render ALTER TABLE ... ALTER COLUMN ... SET DATA TYPE in this dialect."""
        self._require("alter_column_set_data_type", *_ALTER_COLUMN_DIALECTS)
        action = exp.AlterColumn(
            this=exp.Identifier(this=column, quoted=True),
            dtype=exp.DataType.build(data_type, dialect=self._dialect),
        )
        return exp.Alter(this=self._table_node(table), kind="TABLE", actions=[action]).sql(self._dialect)

    def alter_column_drop_not_null(
        self,
        *,
        table: TableRef,
        column: str,
    ) -> str:
        """Render ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL in this dialect."""
        self._require("alter_column_drop_not_null", *_ALTER_COLUMN_DIALECTS)
        action = exp.AlterColumn(this=exp.Identifier(this=column, quoted=True), drop=True, allow_null=True)
        return exp.Alter(this=self._table_node(table), kind="TABLE", actions=[action]).sql(self._dialect)

    def schema_sync_add_column(self, *, table: TableRef, column: str, data_type: str, nullable: bool = True) -> str:
        """Render an ALTER TABLE ADD COLUMN statement for schema synchronization across dialects."""
        table_sql = self._table_node(table).sql(self._dialect)
        col_sql = exp.Identifier(this=column, quoted=True).sql(self._dialect)
        type_sql = exp.DataType.build(data_type, dialect=self._dialect).sql(self._dialect)
        null_suffix = "" if nullable else " NOT NULL"
        if self._dialect == "oracle":
            return f"ALTER TABLE {table_sql} ADD ({col_sql} {type_sql}{null_suffix})"
        return f"ALTER TABLE {table_sql} ADD COLUMN {col_sql} {type_sql}{null_suffix}"

    def schema_sync_widen_column(self, *, table: TableRef, column: str, data_type: str) -> str:
        """Render an ALTER TABLE column type widening statement for schema synchronization."""
        if self._dialect in _ALTER_COLUMN_DIALECTS:
            return self.alter_column_set_data_type(table=table, column=column, data_type=data_type)
        table_sql = self._table_node(table).sql(self._dialect)
        col_sql = exp.Identifier(this=column, quoted=True).sql(self._dialect)
        type_sql = exp.DataType.build(data_type, dialect=self._dialect).sql(self._dialect)
        if self._dialect == "oracle":
            return f"ALTER TABLE {table_sql} MODIFY ({col_sql} {type_sql})"
        return f"ALTER TABLE {table_sql} ALTER COLUMN {col_sql} {type_sql}"

    def schema_sync_relax_nullability(self, *, table: TableRef, column: str) -> str:
        """Render an ALTER TABLE statement relaxing NOT NULL on a column."""
        if self._dialect in _ALTER_COLUMN_DIALECTS:
            return self.alter_column_drop_not_null(table=table, column=column)
        table_sql = self._table_node(table).sql(self._dialect)
        col_sql = exp.Identifier(this=column, quoted=True).sql(self._dialect)
        if self._dialect == "oracle":
            return f"ALTER TABLE {table_sql} MODIFY ({col_sql} NULL)"
        return f"ALTER TABLE {table_sql} ALTER COLUMN {col_sql} DROP NOT NULL"

    def schema_sync_drop_partition(self, *, table: TableRef, partition_name: str) -> str:
        """Render an ALTER TABLE DROP PARTITION statement for schema synchronization."""
        table_sql = self._table_node(table).sql(self._dialect)
        part_sql = exp.Identifier(this=partition_name, quoted=True).sql(self._dialect)
        return f"ALTER TABLE {table_sql} DROP PARTITION {part_sql}"

    def validation_aggregate_query(
        self,
        *,
        table: TableRef,
        questions: Sequence[tuple[str | None, str, str]],
        group_bys: Sequence[str] = (),
        where_clauses: Sequence[str] = (),
        as_of_scn_bind: bool = False,
        parallelism: int | None = None,
    ) -> str:
        """Render a batched cross-DB aggregate validation query."""
        projections: list[exp.Expr] = [
            exp.alias_(
                exp.Column(this=exp.Identifier(this=col, quoted=True)),
                col,
                quoted=True,
                copy=False,
            )
            for col in group_bys
        ]
        for col_name, func_name, alias_name in questions:
            agg_expr = self._build_validation_agg_expr(col_name, func_name)
            projections.append(exp.alias_(agg_expr, alias_name, quoted=True, copy=False))

        table_node = self._table_node(table)
        if self._dialect == "oracle":
            table_node.set("alias", exp.TableAlias(this=exp.Identifier(this="t", quoted=False)))
            if as_of_scn_bind:
                table_node.set(
                    "version",
                    exp.Version(this="SCN", kind="AS OF", expression=exp.Placeholder(this="scn")),
                )

        select_node = exp.select(*projections, copy=False).from_(table_node, copy=False)
        if self._dialect == "oracle" and parallelism and parallelism > 1:
            select_node = select_node.hint(exp.Var(this=f"NO_INDEX(t) PARALLEL(t, {parallelism})"))

        if where_clauses:
            combined_where: exp.Expr | None = None
            for clause in where_clauses:
                clause_expr = exp.Var(this=clause)
                combined_where = (
                    clause_expr if combined_where is None else exp.And(this=combined_where, expression=clause_expr)
                )
            if combined_where is not None:
                select_node = select_node.where(combined_where, copy=False)

        if group_bys:
            group_exprs = [exp.Column(this=exp.Identifier(this=col, quoted=True)) for col in group_bys]
            select_node = select_node.group_by(*group_exprs, copy=False)
            order_exprs = [
                exp.Var(
                    this=f"{exp.Column(this=exp.Identifier(this=col, quoted=True)).sql(self._dialect)} ASC NULLS LAST"
                )
                for col in group_bys
            ]
            select_node = select_node.order_by(*order_exprs, copy=False)

        return select_node.sql(self._dialect)

    def validation_sample_hash_query(
        self,
        *,
        table: TableRef,
        key_columns: Sequence[str],
        value_columns: Sequence[str],
        where_clauses: Sequence[str] = (),
        as_of_scn_bind: bool = False,
    ) -> str:
        """Render a sample row-level hash aggregate query."""
        cols = [*key_columns, *value_columns]
        if not cols:
            raise ValidationError("At least one column is required for sample hash validation")

        cast_type = (
            "VARCHAR2(4000)"
            if self._dialect == "oracle"
            else ("STRING" if self._dialect in ("bigquery", "spark", "impala") else "VARCHAR")
        )
        casted: list[exp.Expr] = []
        for col in cols:
            col_ident = exp.Column(this=exp.Identifier(this=col, quoted=True))
            casted.append(
                exp.Coalesce(
                    this=exp.Cast(this=col_ident, to=exp.DataType.build(cast_type, dialect=self._dialect)),
                    expressions=[exp.Literal.string("~")],
                )
            )
        concat_expr: exp.Expr = casted[0] if len(casted) == 1 else exp.Concat(expressions=casted, safe=True)
        agg_expr = self._build_hash_aggregate_on_expr(concat_expr)
        projection = exp.alias_(agg_expr, "ROW_HASH_AGG", quoted=True, copy=False)

        table_node = self._table_node(table)
        if self._dialect == "oracle" and as_of_scn_bind:
            table_node.set(
                "version",
                exp.Version(this="SCN", kind="AS OF", expression=exp.Placeholder(this="scn")),
            )

        select_node = exp.select(projection, copy=False).from_(table_node, copy=False)
        if where_clauses:
            combined_where: exp.Expr | None = None
            for clause in where_clauses:
                clause_expr = exp.Var(this=clause)
                combined_where = (
                    clause_expr if combined_where is None else exp.And(this=combined_where, expression=clause_expr)
                )
            if combined_where is not None:
                select_node = select_node.where(combined_where, copy=False)

        return select_node.sql(self._dialect)

    def transpile_safe_filter(
        self,
        raw_filter: str,
        *,
        source_dialect: str = "oracle",
        quote_identifiers: bool = False,
    ) -> str:
        """Validate a raw filter condition against an AST allowlist and render in this dialect."""
        cleaned = raw_filter.strip()
        if not cleaned or ";" in cleaned or "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
            raise ValidationError(f"Unsafe or empty filter clause: {raw_filter!r}")
        try:
            statements = [stmt for stmt in sqlglot.parse(cleaned, read=source_dialect) if stmt is not None]
        except Exception as exc:
            raise ValidationError(f"Invalid filter clause {raw_filter!r}: {exc}") from exc
        if len(statements) != 1:
            raise ValidationError(f"Unsafe filter expression in {raw_filter!r}: multiple statements")
        parsed = statements[0]
        for node in parsed.walk():
            if isinstance(node, _FORBIDDEN_FILTER_NODES):
                raise ValidationError(
                    f"Unsafe filter expression in {raw_filter!r}: forbidden AST node {type(node).__name__}"
                )
            if isinstance(node, exp.Anonymous) and node.name.upper() not in _ALLOWED_FILTER_ANONYMOUS:
                raise ValidationError(f"Unsafe filter function in {raw_filter!r}: {node.name}")
            if quote_identifiers and isinstance(node, exp.Column) and isinstance(node.this, exp.Identifier):
                node.this.set("quoted", True)
        return parsed.sql(self._dialect)

    def parse_filter_tuples(
        self,
        raw_filter: str,
        *,
        source_dialect: str = "oracle",
    ) -> list[tuple[str, str, Any] | str]:
        """Parse comma-separated or single filter clauses via sqlglot AST into validated tuples or clauses."""
        parts = [part.strip() for part in raw_filter.split(",") if part.strip()]
        if not parts:
            raise ValidationError(f"Unsafe or empty filter clause: {raw_filter!r}")
        results: list[tuple[str, str, Any] | str] = []
        op_map: dict[type[exp.Expr], str] = {
            exp.EQ: "=",
            exp.NEQ: "!=",
            exp.LT: "<",
            exp.LTE: "<=",
            exp.GT: ">",
            exp.GTE: ">=",
            exp.Like: "like",
        }
        for part in parts:
            validated_sql = self.transpile_safe_filter(part, source_dialect=source_dialect)
            parsed = sqlglot.parse_one(validated_sql, read=self._dialect)
            if isinstance(parsed, exp.Not) and isinstance(parsed.this, exp.Like):
                like_node = parsed.this
                if isinstance(like_node.this, exp.Column) and isinstance(like_node.expression, exp.Literal):
                    results.append((like_node.this.name, "not like", self._literal_to_python(like_node.expression)))
                    continue
            if (
                type(parsed) in op_map
                and isinstance(parsed.this, exp.Column)
                and isinstance(parsed.expression, exp.Literal)
            ):
                results.append((parsed.this.name, op_map[type(parsed)], self._literal_to_python(parsed.expression)))
            else:
                results.append(validated_sql)
        return results

    def build_spec_aggregate_query(
        self,
        *,
        table_identifier: str,
        select_items: Sequence[str],
        where_sql: str = "",
        group_by_cols: Sequence[str] = (),
        order_by_cols: Sequence[str] = (),
        query_hints: str = "",
        prior_to_where: str = "",
    ) -> str:
        """Construct an aggregate validation SELECT query from raw clause components."""
        projections = [exp.Var(this=item) for item in select_items]
        from_target = f"{table_identifier} {prior_to_where}".strip()
        select_node = exp.select(*projections, copy=False).from_(exp.Var(this=from_target), copy=False)
        if where_sql:
            select_node = select_node.where(exp.Var(this=where_sql), copy=False)
        if group_by_cols:
            select_node = select_node.group_by(*[exp.Var(this=col) for col in group_by_cols], copy=False)
        if order_by_cols:
            select_node = select_node.order_by(
                *[exp.Ordered(this=exp.Var(this=col)) for col in order_by_cols],
                copy=False,
            )
        rendered = select_node.sql(self._dialect)
        if query_hints:
            hint_str = query_hints.strip()
            rendered = f"SELECT {hint_str} {rendered[len('SELECT ') :]}"
        return rendered

    def _require(self, method: str, *dialects: str) -> None:
        """Raise DialectNotSupportedError when this engine's dialect is not in dialects."""
        if self._dialect not in dialects:
            raise DialectNotSupportedError(f"{method} is not supported for dialect {self._dialect}")

    @staticmethod
    def _version_node(transport_scn: int | None) -> exp.Version | None:
        """Build an exp.Version node for AS OF SCN when transport_scn is provided."""
        if transport_scn is None:
            return None
        return exp.Version(
            this="SCN",
            kind="AS OF",
            expression=exp.Literal.number(int(transport_scn)),
        )

    @staticmethod
    def _partition_node(
        partition_names: Sequence[str] | None,
        *,
        is_subpartition: bool = False,
        quoted: bool = True,
    ) -> exp.Partition | None:
        """Build an exp.Partition node for PARTITION(...) or SUBPARTITION(...)."""
        if not partition_names:
            return None
        return exp.Partition(
            subpartition=is_subpartition,
            expressions=[exp.Identifier(this=name, quoted=quoted) for name in partition_names],
        )

    def _table_node(self, table: TableRef) -> exp.Table:
        """Build an exp.Table AST node with quoted name, schema, and catalog identifiers."""
        return exp.Table(
            this=exp.Identifier(this=table.name, quoted=True),
            db=exp.Identifier(this=table.schema, quoted=True) if table.schema else None,
            catalog=exp.Identifier(this=table.catalog, quoted=True) if table.catalog else None,
        )

    @classmethod
    def _oracle_table_node(
        cls,
        *,
        owner: str,
        table_name: str,
        alias: str | None = "g",
        partition_names: Sequence[str] | None = None,
        is_subpartition: bool = False,
        transport_scn: int | None = None,
    ) -> exp.Table:
        """Build an exp.Table AST node with optional partition, flashback SCN, and alias."""
        return exp.Table(
            this=exp.Identifier(this=table_name, quoted=True),
            db=exp.Identifier(this=owner, quoted=True),
            partition=cls._partition_node(partition_names, is_subpartition=is_subpartition, quoted=True),
            version=cls._version_node(transport_scn),
            alias=exp.TableAlias(this=exp.Identifier(this=alias, quoted=False)) if alias else None,
        )

    @staticmethod
    def _column_def(col: "ColumnSpec") -> exp.ColumnDef:
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
            return exp.Array(expressions=[DialectSqlEngine._option_value(item) for item in val])
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

    def _build_validation_agg_expr(self, column_name: str | None, func_name: str) -> exp.Expr:
        """Build a dialect-aware validation aggregate expression AST node."""
        if func_name == "COUNT":
            if column_name is None:
                return exp.Count(this=exp.Star())
            return exp.Count(this=exp.Column(this=exp.Identifier(this=column_name, quoted=True)))

        col_expr = exp.Column(this=exp.Identifier(this=column_name or "*", quoted=bool(column_name)))
        if func_name == "MIN":
            return exp.Min(this=col_expr)
        if func_name == "MAX":
            return exp.Max(this=col_expr)
        if func_name == "SUM":
            return exp.Sum(this=col_expr)
        if func_name == "AVG":
            return exp.Avg(this=col_expr)
        if func_name == "STDDEV":
            if self._dialect == "oracle":
                return exp.Stddev(this=col_expr)
            return exp.StddevSamp(this=col_expr)
        if func_name == "HASH_XOR":
            cast_type = (
                "VARCHAR2(4000)"
                if self._dialect == "oracle"
                else ("STRING" if self._dialect in ("bigquery", "spark", "impala") else "VARCHAR")
            )
            str_expr = exp.Coalesce(
                this=exp.Cast(this=col_expr, to=exp.DataType.build(cast_type, dialect=self._dialect)),
                expressions=[exp.Literal.string("~")],
            )
            return self._build_hash_aggregate_on_expr(str_expr)
        raise ValidationError(f"Unsupported aggregate function: {func_name!r}")

    def _build_hash_aggregate_on_expr(self, value_expr: exp.Expr) -> exp.Expr:
        """Build a dialect-specific hash aggregate expression over value_expr."""
        if self._dialect == "bigquery":
            return exp.Anonymous(
                this="BIT_XOR",
                expressions=[exp.Anonymous(this="FARM_FINGERPRINT", expressions=[value_expr])],
            )
        if self._dialect == "oracle":
            return exp.Sum(this=exp.Anonymous(this="ORA_HASH", expressions=[value_expr]))
        if self._dialect == "snowflake":
            return exp.Anonymous(
                this="BITXOR_AGG",
                expressions=[exp.Anonymous(this="HASH", expressions=[value_expr])],
            )
        if self._dialect == "teradata":
            return exp.Sum(this=exp.Anonymous(this="HASHROW", expressions=[value_expr]))
        if self._dialect in ("spark", "impala"):
            return exp.Sum(this=exp.Anonymous(this="XXHASH64", expressions=[value_expr]))
        return exp.Anonymous(
            this="BIT_XOR",
            expressions=[exp.Anonymous(this="HASH", expressions=[value_expr])],
        )

    @staticmethod
    def _literal_to_python(node: exp.Literal) -> Any:
        """Convert an exp.Literal AST node to a Python int, float, or str."""
        if node.is_string:
            return str(node.this)
        text = str(node.this)
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return text


@lru_cache(maxsize=16)
def get_dialect_engine(dialect: SqlDialect) -> DialectSqlEngine:
    """Return the cached DialectSqlEngine for a dialect."""
    return DialectSqlEngine(dialect)
