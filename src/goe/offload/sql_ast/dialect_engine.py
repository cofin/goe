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

from goe.exceptions import GOEError
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
from goe.typing import FrozenBaseStruct

if TYPE_CHECKING:
    from goe.offload.column_metadata import ColumnMetadataInterface

__all__ = (
    "DialectNotSupportedError",
    "DialectSqlEngine",
    "SqlDialect",
    "TableRef",
    "get_dialect_engine",
)

type SqlDialect = Literal["oracle", "bigquery", "snowflake", "tsql", "hive", "spark"]

_ALTER_DIALECTS: frozenset[str] = frozenset({"bigquery", "snowflake", "tsql"})
_ALTER_COLUMN_DIALECTS: frozenset[str] = frozenset({"bigquery", "snowflake"})
_IF_NOT_EXISTS_DIALECTS: frozenset[str] = frozenset({"bigquery", "snowflake"})


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

    def partition_by_clause(self, partition_column: "ColumnMetadataInterface") -> str:
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
        columns: "Sequence[ColumnMetadataInterface]",
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
        columns: "Sequence[ColumnMetadataInterface] | None" = None,
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


@lru_cache(maxsize=8)
def get_dialect_engine(dialect: SqlDialect) -> DialectSqlEngine:
    """Return the cached DialectSqlEngine for a dialect."""
    return DialectSqlEngine(dialect)
