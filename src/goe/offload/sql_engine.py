# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Library-agnostic SQL dialect and AST engine protocols and value objects."""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import msgspec

if TYPE_CHECKING:
    from goe.offload.column_metadata import ColumnMetadataInterface

__all__ = [
    "BigQueryDialectEngineProtocol",
    "OracleExtractionQueryProtocol",
    "PredicateDialectEngineProtocol",
    "RenderedSQL",
    "ValidationQueryEngineProtocol",
    "ValidationQuerySpec",
]


class RenderedSQL(msgspec.Struct, frozen=True, kw_only=True):
    """Rendered SQL text paired with named bind parameters."""

    sql: str
    params: dict[str, Any] = msgspec.field(default_factory=dict)


class ValidationQuerySpec(msgspec.Struct, frozen=True, kw_only=True):
    """Domain specification for constructing a cross-DB aggregate validation query."""

    table_identifier: str
    select_items: Sequence[str]
    where_clauses: Sequence[str] = ()
    group_by_cols: Sequence[str] = ()
    order_by_cols: Sequence[str] = ()
    query_hints: str = ""
    prior_to_where: str = ""
    dialect: str = "oracle"


@runtime_checkable
class BigQueryDialectEngineProtocol(Protocol):
    """Protocol for generating BigQuery DDL, DML, and projection SQL strings."""

    def partition_by_clause(self, partition_column: "ColumnMetadataInterface") -> str:
        """Render the BigQuery PARTITION BY expression for a partition column."""

    def properties_clause(
        self,
        *,
        partition_expr_sql: str | None = None,
        cluster_cols: Sequence[str] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> str:
        """Render the BigQuery PARTITION BY / CLUSTER BY / OPTIONS clause."""

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

    def create_or_replace_ddl(self, ddl: str) -> str:
        """Rewrite a BigQuery CREATE TABLE DDL string to CREATE OR REPLACE TABLE via lexical tokenization."""

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

    def alter_add_columns(
        self,
        *,
        project: str | None,
        db_name: str,
        table_name: str,
        column_name_type_pairs: Sequence[tuple[str, str]],
    ) -> str:
        """Render a BigQuery ALTER TABLE ... ADD COLUMN IF NOT EXISTS statement."""

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


@runtime_checkable
class OracleExtractionQueryProtocol(Protocol):
    """Protocol for building and parsing Oracle extraction queries with AS OF SCN and PARTITION clauses."""

    def snapshot_scn_clause(self, transport_scn: int | None) -> str:
        """Render an Oracle AS OF SCN clause from an integer SCN."""

    def iot_partition_clause(self, partition_name: str | None) -> str:
        """Render an Oracle PARTITION("name") clause for an index-organized table."""

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

    def parse_and_render(self, sql: str) -> str:
        """Parse an Oracle query (including PARTITION/SUBPARTITION and AS OF SCN) and render back to SQL."""


@runtime_checkable
class PredicateDialectEngineProtocol(Protocol):
    """Protocol for rendering typed Lark predicate trees to dialect SQL and validating WHERE clauses."""

    def render_literal_sql(
        self,
        typed_tree: Any,
        columns: Sequence["ColumnMetadataInterface"],
    ) -> str:
        """Render a typed predicate tree into a SQL WHERE clause with inline literals."""

    def render_bind_sql(
        self,
        typed_tree: Any,
        columns: Sequence["ColumnMetadataInterface"],
    ) -> RenderedSQL:
        """Render a typed predicate tree into a SQL WHERE clause with named bind parameters."""

    def validate_where_clause(self, raw_sql: str, dialect: str) -> str:
        """Validate a raw SQL WHERE condition against an AST allowlist and return normalized SQL."""


@runtime_checkable
class ValidationQueryEngineProtocol(Protocol):
    """Protocol for validating cross-DB filter clauses and building aggregate validation SQL."""

    def validate_filter_clause(self, raw_filter: str, dialect: str) -> str:
        """Validate a raw filter condition string for the given dialect."""

    def build_aggregate_query(self, spec: ValidationQuerySpec) -> str:
        """Construct an aggregate validation SELECT query from a ValidationQuerySpec."""
