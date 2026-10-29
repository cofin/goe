# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Cross-database offload validation facade and verification clause builders."""

import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from functools import lru_cache
from typing import Any, cast

import duckdb

from goe.config.options import AggValidateOptions
from goe.config.orchestration_config import OrchestrationConfig
from goe.exceptions import GOEError, ValidationError
from goe.offload.frontend_api import QueryParameter
from goe.offload.offload_constants import DBTYPE_ORACLE
from goe.offload.offload_functions import (
    expand_columns_csv,
    get_hybrid_predicate_clauses,
    get_hybrid_threshold_clauses,
    hvs_to_backend_sql_literals,
    hybrid_view_combine_hv_and_pred_clauses,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE, OffloadMessages, OffloadMessagesMixin
from goe.offload.offload_metadata_functions import (
    decode_metadata_incremental_high_values_from_metadata,
)
from goe.offload.predicates import (
    PredicateOffloadException,
    get_predicate_dialect_engine,
)
from goe.offload.registry import (
    create_backend_api,
    create_backend_table,
    create_frontend_api,
    create_repository_client,
    create_source_table,
)
from goe.offload.schema.column_spec import match_table_column
from goe.offload.sql_ast.dialect_engine import SqlDialect, get_dialect_engine
from goe.offload.sql_engine import ValidationQueryEngineProtocol, ValidationQuerySpec
from goe.offload.validation.ast_builder import (
    AggregateQuestion,
    CrossDbValidationBuilder,
    ValidationBatchQuery,
)
from goe.offload.validation.runner import (
    ColumnMismatch,
    ValidationResult,
)
from goe.offload.validation.runner import (
    CrossDbValidator as ConcurrentCrossDbValidator,
)
from goe.orchestration import command_steps
from goe.orchestration.logging_init import (
    get_log_fh,
    get_log_fh_name,
    init,
    init_log,
    log,
    log_timestamp,
    version,
)
from goe.orchestration.stages.plan_resolution import normalise_owner_table_options
from goe.persistence.models import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
    OffloadMetadata,
)
from goe.util.concurrency import run_bounded
from goe.util.goe_log import log_exception
from goe.util.string_utils import csv_split, is_number, is_pos_int, isclose, str_floatlike

__all__ = (
    "DEFAULT_AGGS",
    "DEFAULT_SELECT_COLS",
    "ENGINE_BACK",
    "ENGINE_FRONT",
    "GROUPBY_PARTITIONS",
    "PROG_BANNER",
    "SUPPORTED_OPERATIONS",
    "AggValidateException",
    "AggregateQuestion",
    "BackendCountValidator",
    "ColumnMismatch",
    "CrossDbValidationBuilder",
    "CrossDbValidator",
    "CrossDbValidatorException",
    "OffloadValidationException",
    "ValidationBatchQuery",
    "ValidationResult",
    "ValidationSqlEngine",
    "build_verification_clauses",
    "combine_validation_filters",
    "diff_rows_in_duckdb",
    "get_validation_query_engine",
    "post_process_args",
    "print_title",
    "run_agg_validate",
    "set_logging",
    "validate_raw_filter_clause",
    "validate_table",
)


class CrossDbValidatorException(ValidationError):
    """Raised when cross-database validation fails or receives invalid inputs."""


OffloadValidationException = CrossDbValidatorException

_TRIVIAL_TAUTOLOGIES: frozenset[str] = frozenset({"1=1", "1 = 1", "(1=1)", "(1 = 1)"})

DEFAULT_SELECT_COLS = 5
DEFAULT_AGGS = ("min", "max", "count")
GROUPBY_PARTITIONS = "<extract partition columns>"
SUPPORTED_OPERATIONS = ("<", "<=", ">", ">=", "=", "!=", "<>", "like", "not like")
ENGINE_FRONT = "FRONT"
ENGINE_BACK = "BACK"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def validate_raw_filter_clause(raw_filter: str, dialect: str = "oracle") -> str:
    """Validate a raw filter condition string via PredicateDialectEngineProtocol."""
    try:
        return get_predicate_dialect_engine(dialect).validate_where_clause(raw_filter, dialect=dialect)
    except (PredicateOffloadException, ValidationError) as exc:
        raise CrossDbValidatorException(str(exc)) from exc


def combine_validation_filters(filters: Sequence[str], dialect: str = "oracle") -> str:
    """Validate and combine non-trivial filter clauses into a parenthesized AND conjunction."""
    cleaned: list[str] = []
    for raw in filters:
        stripped = raw.strip()
        if not stripped or stripped in _TRIVIAL_TAUTOLOGIES:
            continue
        cleaned.append(validate_raw_filter_clause(stripped, dialect=dialect))
    if not cleaned:
        return ""
    return " AND ".join(
        f"({clause})" if not (clause.startswith("(") and clause.endswith(")")) else clause for clause in cleaned
    )


def diff_rows_in_duckdb(
    source_rows: Sequence[Mapping[str, Any]],
    target_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Run an in-memory DuckDB EXCEPT diff over normalized source and target row dictionaries."""
    if not source_rows:
        return []
    columns = [str(k).upper() for k in source_rows[0].keys()]
    if not columns:
        return []
    conn = duckdb.connect(":memory:")
    try:
        col_defs = ", ".join(f'"{col}" VARCHAR' for col in columns)
        conn.execute(f"CREATE TABLE source_rows ({col_defs})")
        conn.execute(f"CREATE TABLE target_rows ({col_defs})")
        placeholders = ", ".join("?" for _ in columns)
        src_tuples = [
            tuple(
                None if row.get(k) is None and row.get(k.lower()) is None else str(row.get(k, row.get(k.lower())))
                for k in columns
            )
            for row in source_rows
        ]
        tgt_tuples = [
            tuple(
                None if row.get(k) is None and row.get(k.lower()) is None else str(row.get(k, row.get(k.lower())))
                for k in columns
            )
            for row in target_rows
        ]
        if src_tuples:
            conn.executemany(f"INSERT INTO source_rows VALUES ({placeholders})", src_tuples)
        if tgt_tuples:
            conn.executemany(f"INSERT INTO target_rows VALUES ({placeholders})", tgt_tuples)
        cursor = conn.execute("SELECT * FROM source_rows EXCEPT SELECT * FROM target_rows")
        fetched = cursor.fetchall()
        return [dict(zip(columns, row)) for row in fetched]
    finally:
        conn.close()


class ValidationSqlEngine(ValidationQueryEngineProtocol):
    """Aggregate validation query builder and filter validator satisfying ValidationQueryEngineProtocol."""

    def __init__(self, dialect: str = "oracle") -> None:
        self._dialect = dialect

    def validate_filter_clause(self, raw_filter: str, dialect: str) -> str:
        """Validate a raw filter condition string for the given dialect."""
        return validate_raw_filter_clause(raw_filter, dialect=dialect)

    def build_aggregate_query(self, spec: ValidationQuerySpec) -> str:
        """Construct an aggregate validation SELECT query from a ValidationQuerySpec."""
        where_sql = combine_validation_filters(spec.where_clauses, dialect=spec.dialect)
        engine = get_dialect_engine(cast(SqlDialect, spec.dialect))
        return engine.build_spec_aggregate_query(
            table_identifier=spec.table_identifier,
            select_items=spec.select_items,
            where_sql=where_sql,
            group_by_cols=spec.group_by_cols,
            order_by_cols=spec.order_by_cols,
            query_hints=spec.query_hints,
            prior_to_where=spec.prior_to_where,
        )


@lru_cache(maxsize=4)
def get_validation_query_engine(dialect: str = "oracle") -> ValidationQueryEngineProtocol:
    """Return a cached ValidationQueryEngineProtocol instance for the given dialect."""
    return ValidationSqlEngine(dialect=dialect)


def build_verification_clauses(
    offload_source_table: Any,
    ipa_predicate_type: Any,
    verification_hvs: Any,
    prior_hvs: Any,
    offload_predicate: Any = None,
    with_binds: bool = True,
    backend_table: Any = None,
) -> tuple[list[str], list[QueryParameter]]:
    """Build clauses used in verification queries from frontend partition columns and partition key values."""

    def get_bind_and_literal(col_hv: Any, bind_counter: int, bind_pattern: str, data_type: str) -> tuple[Any, Any]:
        if col_hv is None:
            return None, None
        new_bind = None
        if backend_table:
            where_clause_expr = backend_table.to_backend_literal(col_hv, data_type=data_type)
            where_clause_expr = (
                str(where_clause_expr) if isinstance(where_clause_expr, (int, float)) else where_clause_expr
            )
        else:
            bind_name = bind_pattern % bind_counter
            bind_value, sql_fn = offload_source_table.to_rdbms_literal_with_sql_conv_fn(col_hv, data_type)
            if with_binds:
                where_clause_value = offload_source_table.format_query_parameter(bind_name)
                new_bind = QueryParameter(bind_name, bind_value)
            else:
                where_clause_value = f"'{bind_value}'" if isinstance(bind_value, str) else bind_value
            where_clause_expr = sql_fn % where_clause_value if sql_fn else where_clause_value
        return new_bind, where_clause_expr

    if offload_predicate:
        if backend_table:
            return [backend_table.predicate_to_where_clause(offload_predicate)], []
        if with_binds:
            where_clause, binds = offload_source_table.predicate_to_where_clause_with_binds(offload_predicate)
            return [where_clause], binds
        return [offload_source_table.predicate_to_where_clause(offload_predicate)], []

    rdbms_part_cols = offload_source_table.partition_columns
    query_params: list[QueryParameter] = []
    threshold_clauses: list[str] = []
    enclosure_fn = backend_table.enclose_identifier if backend_table else offload_source_table.enclose_identifier

    if rdbms_part_cols and verification_hvs:
        prior_literals: list[Any] = []
        new_literals: list[Any] = []
        prior_bind_count, new_bind_count = 0, 0
        if ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST:
            verification_hvs = [verification_hvs]
        if prior_hvs is None:
            prior_hvs = [None for _ in range(len(rdbms_part_cols))]

        for part_col, hv, prior_hv in zip(rdbms_part_cols, verification_hvs, prior_hvs):
            data_type = backend_table.get_column(part_col.name).data_type if backend_table else part_col.data_type
            if prior_hv is not None and ipa_predicate_type in (
                INCREMENTAL_PREDICATE_TYPE_RANGE,
                INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
            ):
                new_bind, new_literal = get_bind_and_literal(prior_hv, prior_bind_count, "l%d", data_type)
                if new_bind:
                    query_params.append(new_bind)
                    prior_bind_count += 1
                prior_literals.append(new_literal)

            if hv is not None:
                if ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST:
                    for part_hv in hv:
                        col_hv_list = []
                        for phv in part_hv:
                            new_bind, new_literal = get_bind_and_literal(phv, new_bind_count, "h%d", data_type)
                            if new_bind:
                                query_params.append(new_bind)
                                new_bind_count += 1
                            col_hv_list.append(new_literal)
                        new_literals.append(tuple(col_hv_list))
                else:
                    new_bind, new_literal = get_bind_and_literal(hv, new_bind_count, "h%d", data_type)
                    if new_bind:
                        query_params.append(new_bind)
                        new_bind_count += 1
                    new_literals.append(new_literal)

        if prior_literals:
            _, prior_gte_clause = get_hybrid_threshold_clauses(
                rdbms_part_cols,
                rdbms_part_cols,
                ipa_predicate_type,
                prior_literals,
                col_enclosure_fn=enclosure_fn,
            )
            threshold_clauses.append(prior_gte_clause)
        if new_literals:
            new_lt_clause, _ = get_hybrid_threshold_clauses(
                rdbms_part_cols,
                rdbms_part_cols,
                ipa_predicate_type,
                new_literals,
                col_enclosure_fn=enclosure_fn,
            )
            threshold_clauses.append(new_lt_clause)
    return threshold_clauses, query_params


class CrossDbValidator(OffloadMessagesMixin):
    """Validate that data in frontend RDBMS matches backend data warehouse via aggregates."""

    def __init__(
        self,
        db_name: str,
        table_name: str,
        connection_options: Any,
        backend_obj: Any = None,
        messages: Any = None,
        backend_db: str | None = None,
        backend_table: str | None = None,
        execute: bool = True,
    ) -> None:
        assert db_name and table_name
        self._execute = execute
        self._db_name = db_name
        self._table_name = table_name
        self._db_table = f"{db_name}.{table_name}"
        self._frontend = create_frontend_api(
            connection_options.db_type,
            connection_options,
            messages,
            conn_user_override=connection_options.rdbms_app_user,
            dry_run=(not self._execute),
            trace_action=self.__class__.__name__,
        )
        self._backend = backend_obj or create_backend_api(
            connection_options.target,
            connection_options,
            messages,
            dry_run=bool(not self._execute),
        )
        self._connection_options = connection_options
        self._messages = messages

        if not backend_db and not backend_table:
            repo_client = create_repository_client(
                self._connection_options,
                messages,
                dry_run=bool(not self._execute),
                trace_action=self.__class__.__name__,
            )
            self._offload_metadata: OffloadMetadata | None = repo_client.get_offload_metadata(
                self._db_name.upper(),
                self._table_name.upper(),
            )
        else:
            self._offload_metadata = None

        if self._offload_metadata:
            self._backend_db = self._offload_metadata.backend_owner
            self._backend_table = self._offload_metadata.backend_table
        else:
            self._backend_db = backend_db or self._db_name
            self._backend_table = backend_table or self._table_name

        super().__init__(messages, logger)
        self._frontend_table: Any = None
        self._frontend_sql: str | None = None
        self._backend_sql: str | None = None
        self._results: dict[str, Any] | None = None
        self._success: bool | None = None
        self._concurrent_runner = ConcurrentCrossDbValidator
        logger.debug("Initialized CrossDbValidator() object for: %s", self._db_table)

    def __del__(self) -> None:
        if getattr(self, "_frontend", None):
            self._frontend.close()

    @property
    def frontend_sql(self) -> str | None:
        """Return the generated frontend SQL statement."""
        return self._frontend_sql

    @property
    def backend_sql(self) -> str | None:
        """Return the generated backend SQL statement."""
        return self._backend_sql

    @property
    def results(self) -> dict[str, Any] | None:
        """Return the raw frontend and backend execution results."""
        return self._results

    @property
    def success(self) -> bool | None:
        """Return whether the most recent validation succeeded."""
        return self._success

    def validate(
        self,
        selects: Any = DEFAULT_SELECT_COLS,
        filters: Any = None,
        group_bys: Any = None,
        aggs: Any = DEFAULT_AGGS,
        safe: bool = True,
        as_of_scn: int | None = None,
        execute: bool = True,
        frontend_filters: Any = None,
        frontend_query_params: Any = None,
        frontend_parallelism: int | None = None,
    ) -> tuple[bool, str]:
        """Run cross-database aggregate validation and return (success, message)."""
        if frontend_query_params:
            assert isinstance(frontend_query_params, list)
            assert isinstance(frontend_query_params[0], QueryParameter)

        selects = self._get_select_cols(selects, aggs)
        backend_filters = self._get_filters(filters, safe)
        group_bys = self._get_group_bys(group_bys)
        frontend_filters = frontend_filters or self._get_filters(filters, safe, frontend=True)
        frontend_hint_block = (
            self._get_frontend_query_hint_block(frontend_parallelism) if frontend_parallelism is not None else ""
        )
        self._frontend_sql, front_selects = self._construct_simple_front_agg_sql(
            selects, frontend_filters, group_bys, aggs, as_of_scn, frontend_hint_block
        )
        self._backend_sql = self._construct_simple_back_agg_sql(selects, backend_filters, group_bys, aggs)
        agg_message = "Compared aggregations of columns: %s" % ", ".join(selects)

        if execute:
            self._results = self._run_sqls(self._frontend_sql, self._backend_sql, frontend_query_params)
            self._success = self._compare_results(self._results, front_selects, group_bys)
            return bool(self._success), agg_message
        self.log_verbose("Frontend sql: %s" % self._frontend_sql)
        self.log_verbose("Backend sql: %s" % self._backend_sql)
        return True, agg_message

    def run_row_diff(self) -> list[dict[str, Any]]:
        """Compute an in-memory DuckDB EXCEPT diff over the last executed validation result rows."""
        if not self._results:
            return []
        front_rows = self._results.get(ENGINE_FRONT) or []
        back_rows = self._results.get(ENGINE_BACK) or []
        if not isinstance(front_rows, list) or not isinstance(back_rows, list):
            return []
        front_dicts = [
            {f"COL_{idx}": val for idx, val in enumerate(row)} if isinstance(row, (list, tuple)) else dict(row)
            for row in front_rows
        ]
        back_dicts = [
            {f"COL_{idx}": val for idx, val in enumerate(row)} if isinstance(row, (list, tuple)) else dict(row)
            for row in back_rows
        ]
        return diff_rows_in_duckdb(front_dicts, back_dicts)

    def _get_frontend_table(self) -> Any:
        if not self._frontend_table:
            owner = self._offload_metadata.offloaded_owner if self._offload_metadata else self._db_name
            table = self._offload_metadata.offloaded_table if self._offload_metadata else self._table_name
            self._frontend_table = create_source_table(
                owner,
                table,
                self._connection_options,
                self._messages,
            )
        return self._frontend_table

    def _get_sample_cols(self, required_no: int) -> list[str]:
        return self._frontend.agg_validate_sample_column_names(
            self._db_name.upper(), self._table_name.upper(), num_required=required_no
        )

    def _get_group_bys(self, group_bys: Any) -> Any:
        if not group_bys:
            pass
        elif group_bys == GROUPBY_PARTITIONS:
            group_bys = self._get_partition_columns()
        elif isinstance(group_bys, (list, tuple)):
            frontend_table = self._get_frontend_table()
            group_bys = expand_columns_csv(
                ",".join(group_bys),
                frontend_table.columns,
                retain_non_matching_names=True,
            )
        else:
            raise CrossDbValidatorException("Invalid list of GROUPBYs: %s" % group_bys)
        return group_bys

    def _get_select_cols(self, select_cols: Any, aggs: Any) -> list[str]:
        if is_number(select_cols):
            select_cols = self._get_sample_cols(max(int(select_cols), 1))
        elif isinstance(select_cols, (list, tuple)):
            frontend_table = self._get_frontend_table()
            select_cols = expand_columns_csv(
                ",".join(select_cols),
                frontend_table.columns,
                retain_non_matching_names=True,
            )
        else:
            raise CrossDbValidatorException("Invalid list of SELECTs: %s" % select_cols)
        if not select_cols:
            raise CrossDbValidatorException("Unable to identify columns for table: %s" % self._db_table)
        return select_cols

    def _get_partition_columns(self) -> list[str]:
        sql = """
            select column_name from all_part_key_columns
            where owner=:OWNER and name=:TABLE_NAME order by column_position
        """
        binds = {
            QueryParameter(param_name="OWNER", param_value=self._db_name.upper()),
            QueryParameter(param_name="TABLE_NAME", param_value=self._table_name.upper()),
        }
        query_result = self._frontend.execute_query_fetch_all(sql, query_params=binds, log_level=VVERBOSE)
        return [x[0] for x in query_result]

    def _construct_simple_agg_sql(
        self,
        selects: Sequence[str],
        filters: Any,
        group_bys: Any,
        aggs: Sequence[str],
        as_of_scn: int | None = None,
        db_name: str | None = None,
        table_name: str | None = None,
        frontend_hint_block: str | None = None,
    ) -> tuple[str, list[str]]:
        db_name = db_name or self._db_name
        table_name = table_name or self._table_name
        normalized_group_bys = list(group_bys) if group_bys else []
        select_expressions = normalized_group_bys + [f"{a.upper()}({s})" for s in selects for a in aggs]
        normalized_filters = [
            f"{x[0]} {x[1]} {x[2]}" if isinstance(x, (list, tuple)) else str(x) for x in (filters or [])
        ]
        spec = ValidationQuerySpec(
            table_identifier=f"{db_name}.{table_name}",
            select_items=select_expressions,
            where_clauses=normalized_filters,
            group_by_cols=normalized_group_bys,
            order_by_cols=normalized_group_bys,
            query_hints=frontend_hint_block or "",
            prior_to_where=f"AS OF SCN {int(as_of_scn)}" if as_of_scn else "",
            dialect="oracle",
        )
        sql = get_validation_query_engine("oracle").build_aggregate_query(spec)
        return sql, select_expressions

    def _construct_simple_front_agg_sql(
        self,
        selects: Sequence[str],
        filters: Any,
        group_bys: Any,
        aggs: Sequence[str],
        as_of_scn: int | None,
        frontend_hint_block: str | None,
    ) -> tuple[str, list[str]]:
        return self._construct_simple_agg_sql(
            selects,
            self._adjust_filters_front(filters),
            group_bys,
            aggs,
            as_of_scn=as_of_scn,
            frontend_hint_block=frontend_hint_block,
        )

    def _construct_simple_back_agg_sql(
        self,
        selects: Sequence[str],
        filters: Any,
        group_bys: Any,
        aggs: Sequence[str],
    ) -> str:
        backend_filters = self._adjust_filters_back(filters)
        if not self._backend.exists(self._backend_db, self._backend_table):
            raise CrossDbValidatorException(
                f"Table {self._backend_db}.{self._backend_table} does not exist in {self._backend.backend_type()}"
            )
        return self._backend.gen_sql_text(
            self._backend_db,
            self._backend_table,
            column_names=group_bys,
            filter_clauses=backend_filters,
            measures=selects,
            agg_fns=aggs,
        )

    def _adjust_filters_front(self, filters: Any) -> Any:
        if filters:
            engine = get_validation_query_engine("oracle")
            new_filters = []
            for filt in filters:
                if isinstance(filt, (list, tuple)):
                    left, expr, right = filt
                    right = self._frontend.to_frontend_literal(right)
                    clause = f"{left} {expr} {right}"
                else:
                    clause = str(filt)
                new_filters.append(engine.validate_filter_clause(clause, "oracle"))
            filters = new_filters
        return filters

    def _adjust_filters_back(self, filters: Any) -> Any:
        if filters:
            backend_dialect = "bigquery" if self._backend.backend_type() == "BIGQUERY" else "oracle"
            engine = get_validation_query_engine(backend_dialect)
            new_filters = []
            for filt in filters:
                if isinstance(filt, (list, tuple)):
                    left, expr, right = filt
                    left = self._backend.enclose_identifier(left)
                    right = self._backend.to_backend_literal(right)
                    clause = f"{left} {expr} {right}"
                else:
                    clause = str(filt)
                    if self._backend.enclosure_character() != '"':
                        clause = clause.replace('"', self._backend.enclosure_character())
                new_filters.append(engine.validate_filter_clause(clause, backend_dialect))
            filters = new_filters
        return filters

    def _run_sqls(self, front_sql: str, back_sql: str, front_binds: Any = None) -> dict[str, Any]:
        def run_front() -> Any:
            return self._frontend.execute_query_fetch_all(front_sql, query_params=front_binds, log_level=VERBOSE)

        def run_back() -> Any:
            return self._backend.execute_query_fetch_all(back_sql, log_level=VERBOSE)

        results = run_bounded([run_front, run_back], max_workers=2)
        return {ENGINE_FRONT: results[0], ENGINE_BACK: results[1]}

    def _compare_results(self, results: Any, front_selects: Sequence[str], group_bys: Any) -> bool:
        def front_and_back_match(front: Any, back: Any) -> bool:
            if is_number(front) and is_number(back) and isclose(float(front), float(back)):
                return True
            if isinstance(front, date) and isinstance(back, (date, str)):
                if isinstance(back, str):
                    back = datetime.strptime(back, "%Y-%m-%d").date()
                if front.strftime("%Y-%m-%d %H:%M:%S.%f") == back.strftime("%Y-%m-%d %H:%M:%S.%f"):
                    return True
            return str(front) == str(back)

        def row_pk(row: Sequence[Any]) -> str:
            if group_bys:
                no_pk_cols = len(group_bys)
                pk = list(zip(front_selects[:no_pk_cols], row[:no_pk_cols]))
                return ", ".join("%s: %s" % (k, v) for k, v in pk)
            return "TOTAL"

        def rows(res: Any) -> int:
            return 0 if not res or not isinstance(res, (list, tuple)) else len(res)

        def cols(res: Any) -> int:
            return (
                0
                if not res or not isinstance(res, list) or len(res) == 0 or not isinstance(res[0], (list, tuple))
                else len(res[0])
            )

        front_results, back_results = results[ENGINE_FRONT], results[ENGINE_BACK]
        if results == [[], []]:
            return True
        if front_results is False:
            raise CrossDbValidatorException("FRONT-END SQL execution failed")
        if back_results is False:
            raise CrossDbValidatorException("BACK-END SQL execution failed")
        if rows(front_results) != rows(back_results):
            return False
        if cols(front_results) != cols(back_results):
            return False

        pk_len = len(group_bys) if group_bys else 0
        no_columns = len(front_results[0])
        all_matched = True
        for row_no, front_row in enumerate(front_results):
            back_row = back_results[row_no]
            pk_label = row_pk(front_row)
            for col_no in range(pk_len, no_columns):
                front_val = front_row[col_no]
                back_val = back_row[col_no]
                if not front_and_back_match(front_val, back_val):
                    self.warn(
                        "Results for [%s]: %s do NOT match - FRONT: %s vs BACK: %s"
                        % (pk_label, front_selects[col_no], str_floatlike(front_val), str_floatlike(back_val))
                    )
                    all_matched = False
        return all_matched

    def _extract_offload_boundary(self, frontend: bool = False) -> str:
        if not self._offload_metadata:
            return ""
        rdbms_table = self._get_frontend_table()
        backend_table = (
            None
            if frontend
            else create_backend_table(
                self._offload_metadata.backend_owner,
                self._offload_metadata.backend_table,
                self._backend.backend_type(),
                self._connection_options,
                self._messages,
                hybrid_metadata=self._offload_metadata,
                existing_backend_api=self._backend,
                dry_run=(not self._execute),
            )
        )
        inc_keys, hv_real_vals, hv_indiv_vals = decode_metadata_incremental_high_values_from_metadata(
            self._offload_metadata, rdbms_table
        )
        offload_predicates = self._offload_metadata.decode_incremental_predicate_values()
        inc_predicate_type = self._offload_metadata.incremental_predicate_type
        enclosure_fn = enclosure_character = None
        if frontend:
            lt_threshold_vals = hv_indiv_vals
            enclosure_character = '"'
        else:
            assert backend_table is not None
            backend_threshold_cols = [match_table_column(_.name, backend_table.get_columns()) for _ in inc_keys]
            lt_threshold_vals = hvs_to_backend_sql_literals(
                backend_threshold_cols,
                hv_real_vals,
                inc_predicate_type,
                self._backend.to_backend_literal,
            )
            enclosure_fn = self._backend.enclose_identifier
        lt_clause, _ = get_hybrid_threshold_clauses(
            inc_keys,
            inc_keys,
            inc_predicate_type,
            lt_threshold_vals,
            col_quoting_char=enclosure_character,
            col_enclosure_fn=enclosure_fn,
        )
        if offload_predicates:
            predicate_table_obj = rdbms_table if frontend else backend_table
            offloaded_pred, _ = get_hybrid_predicate_clauses(offload_predicates, predicate_table_obj)
        else:
            offloaded_pred = ""
        return hybrid_view_combine_hv_and_pred_clauses(lt_clause, offloaded_pred, "OR")

    def _add_boundary_filters(self, filters: Any, frontend: bool = False) -> list[Any]:
        offload_boundary = self._extract_offload_boundary(frontend=frontend)
        new_filters: list[Any] = []
        if filters:
            new_filters.extend(filters)
        if offload_boundary:
            new_filters.append(offload_boundary)
        return new_filters

    def _get_filters(self, filters: Any, safe: bool, frontend: bool = False) -> Any:
        if safe:
            filters = self._add_boundary_filters(filters, frontend=frontend)
        return filters

    def _get_frontend_query_hint_block(self, frontend_parallelism: int | None) -> str:
        if frontend_parallelism is None or self._connection_options.db_type != DBTYPE_ORACLE:
            return ""
        frontend_table = self._get_frontend_table()
        return frontend_table.enclose_query_hints(frontend_table.parallel_query_hint(frontend_parallelism))


class BackendCountValidator:
    """Validate data volume in the frontend table matches that in the backend table using COUNT(*) queries."""

    def __init__(self, frontend_table: Any, backend_table: Any, messages: Any, dry_run: bool = False) -> None:
        self._frontend_table = frontend_table
        self._backend_table = backend_table
        self._messages = messages
        self._dry_run = dry_run

    def validate(
        self,
        frontend_filters: list[str] | None,
        frontend_query_params: list[QueryParameter] | None,
        backend_filters: list[str] | None,
        frontend_hint_block: str | None = None,
    ) -> tuple[int, int, int]:
        """Run frontend and backend row count queries and return (diff, frontend_count, backend_count)."""
        if frontend_filters:
            assert isinstance(frontend_filters, list)
        if frontend_query_params:
            assert isinstance(frontend_query_params, list)
            assert isinstance(frontend_query_params[0], QueryParameter)

        frontend_api = self._frontend_table.get_frontend_api()
        backend_api = self._backend_table.get_backend_api()
        frontend_filter = " AND ".join(frontend_filters) if frontend_filters else None
        backend_filter = " AND ".join(backend_filters) if backend_filters else None
        frontend_count = frontend_api.get_table_row_count(
            self._frontend_table.owner,
            self._frontend_table.table_name,
            filter_clause=frontend_filter,
            filter_clause_params=frontend_query_params,
            hint_block=frontend_hint_block,
            not_when_dry_running=True,
            log_level=VERBOSE,
        )
        backend_count = backend_api.get_table_row_count(
            self._backend_table.db_name,
            self._backend_table.table_name,
            filter_clause=backend_filter,
            not_when_dry_running=True,
            log_level=VERBOSE,
        )
        if self._dry_run:
            return 0, 0, 0
        return (frontend_count - backend_count), frontend_count, backend_count


class AggValidateException(ValidationError):
    """Raised when agg_validate option parsing or execution fails."""


PROG_BANNER = f"Validate (agg_validate) v{version()}"


def validate_table(args: Any, messages: Any) -> bool:
    """Validate a specific table using CrossDbValidator."""

    def step_fn() -> bool:
        config = OrchestrationConfig.from_dict({"verbose": args.verbose})
        validator = CrossDbValidator(
            db_name=args.owner,
            table_name=args.table_name,
            connection_options=config,
            messages=messages,
        )
        status, _ = validator.validate(
            selects=args.selects,
            filters=args.filters,
            group_bys=args.group_bys,
            aggs=args.aggregate_functions,
            safe=not args.skip_boundary_check,
            as_of_scn=args.as_of_scn,
            execute=args.execute,
            frontend_parallelism=args.frontend_parallelism,
        )
        if status:
            messages.log("[OK]", ansi_code="green")
            return True
        if getattr(args, "diff", False) and args.execute:
            diff_rows = validator.run_row_diff()
            if diff_rows:
                messages.warning(f"Row-level diff detected {len(diff_rows)} differing group row(s): {diff_rows}")
        messages.log("[ERROR]", ansi_code="red")
        return False

    return bool(
        messages.offload_step(
            command_steps.STEP_VALIDATE_DATA,
            step_fn,
            execute=args.execute,
        )
    )


def set_logging(log_level: str | None) -> None:
    """Set global logging parameters."""
    if log_level:
        logging.basicConfig(
            level=logging.getLevelName(log_level),
            format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def print_title() -> None:
    """Print utility title."""
    sys.stdout.write(f"{PROG_BANNER}\n\n")


def post_process_args(args: AggValidateOptions) -> None:
    """Post-process and AST-validate CLI arguments."""
    if isinstance(args.filters, str) and args.filters:
        builder = CrossDbValidationBuilder("oracle")
        try:
            args.filters = cast(list[tuple[str, str, object]], builder.parse_filter_tuples(args.filters))
        except GOEError as exc:
            raise AggValidateException(f"Invalid FILTER expression: {args.filters}") from exc
    if args.selects:
        if isinstance(args.selects, (list, str)) and len(args.selects) == 1 and is_number(args.selects[0]):
            args.selects = args.selects[0]
        elif isinstance(args.selects, str):
            args.selects = list[str | int](csv_split(args.selects))
    if isinstance(args.group_bys, str) and args.group_bys and args.group_bys != GROUPBY_PARTITIONS:
        args.group_bys = csv_split(args.group_bys)
    if (
        isinstance(args.aggregate_functions, str)
        and args.aggregate_functions
        and args.aggregate_functions != DEFAULT_AGGS
    ):
        args.aggregate_functions = csv_split(args.aggregate_functions)
    if args.frontend_parallelism:
        if not is_pos_int(args.frontend_parallelism):
            raise AggValidateException("Invalid frontend parallelism: %s" % args.frontend_parallelism)
        args.frontend_parallelism = int(args.frontend_parallelism)


def run_agg_validate(args: AggValidateOptions) -> bool:
    """Run aggregate validation with parsed args namespace."""
    init(args)
    init_log("agg_validate_%s" % args.owner_table)
    log("")
    log(PROG_BANNER, ansi_code="underline")
    log("Log file: %s" % get_log_fh_name())

    normalise_owner_table_options(args)
    set_logging(args.dev_log_level)

    try:
        messages = OffloadMessages.from_options(args)
        return validate_table(args=args, messages=messages)
    except Exception as exc:
        log("Exception caught at top-level", ansi_code="red")
        log_timestamp()
        log_exception(exc, log_fh=get_log_fh(), options=args)
        sys.exit(1)
