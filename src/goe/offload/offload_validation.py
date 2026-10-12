#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Offload data validation library

CrossDbValidator:   Validate successful offload via calculating aggregates in front/back databases
                    and comparing them
"""

import logging
from collections.abc import Sequence
from datetime import date, datetime
from functools import lru_cache

from sqlglot import exp

from goe.offload.column_metadata import match_table_column
from goe.offload.factory.backend_api_factory import backend_api_factory
from goe.offload.factory.backend_table_factory import backend_table_factory
from goe.offload.factory.frontend_api_factory import (
    frontend_api_factory,
)
from goe.offload.factory.offload_source_table_factory import OffloadSourceTable
from goe.offload.frontend_api import QueryParameter
from goe.offload.offload_constants import DBTYPE_ORACLE
from goe.offload.offload_functions import (
    expand_columns_csv,
    get_hybrid_predicate_clauses,
    get_hybrid_threshold_clauses,
    hvs_to_backend_sql_literals,
    hybrid_view_combine_hv_and_pred_clauses,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE, OffloadMessagesMixin
from goe.offload.offload_metadata_functions import (
    decode_metadata_incremental_high_values_from_metadata,
)
from goe.offload.oracle.oracle_dialect import register_oracle_dialect_extensions
from goe.offload.predicate_offload import (
    PredicateOffloadException,
    get_predicate_dialect_engine,
)
from goe.offload.sql_engine import ValidationQueryEngineProtocol, ValidationQuerySpec
from goe.persistence.orchestration_metadata import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
    OrchestrationMetadata,
)
from goe.util.misc_functions import is_number, isclose, str_floatlike
from goe.util.parallel_exec import ParallelExecutor


class CrossDbValidatorException(Exception):
    pass


OffloadValidationException = CrossDbValidatorException

_TRIVIAL_TAUTOLOGIES: frozenset[str] = frozenset({"1=1", "1 = 1", "(1=1)", "(1 = 1)"})

DEFAULT_SELECT_COLS = 5

DEFAULT_AGGS = ("min", "max", "count")

GROUPBY_PARTITIONS = "<extract partition columns>"

SUPPORTED_OPERATIONS = ("<", "<=", ">", ">=", "=", "!=", "<>", "like", "not like")

ENGINE_FRONT = "FRONT"
ENGINE_BACK = "BACK"


def validate_raw_filter_clause(raw_filter: str, dialect: str = "oracle") -> str:
    """Validate a raw filter condition string via PredicateDialectEngineProtocol."""
    try:
        return get_predicate_dialect_engine(dialect).validate_where_clause(raw_filter, dialect=dialect)
    except PredicateOffloadException as exc:
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
    if len(cleaned) == 1:
        return f"({cleaned[0]})" if not (cleaned[0].startswith("(") and cleaned[0].endswith(")")) else cleaned[0]
    combined: exp.Expr | None = None
    for clause in cleaned:
        wrapped = exp.Paren(this=exp.Var(this=clause))
        combined = wrapped if combined is None else exp.And(this=combined, expression=wrapped)
    assert combined is not None
    return combined.sql(dialect)


class ValidationSqlEngine(ValidationQueryEngineProtocol):
    """Aggregate validation query builder and filter validator satisfying ValidationQueryEngineProtocol."""

    def __init__(self, dialect: str = "oracle") -> None:
        self._dialect = dialect
        if dialect == "oracle":
            register_oracle_dialect_extensions()

    def validate_filter_clause(self, raw_filter: str, dialect: str) -> str:
        """Validate a raw filter condition string for the given dialect."""
        return validate_raw_filter_clause(raw_filter, dialect=dialect)

    def build_aggregate_query(self, spec: ValidationQuerySpec) -> str:
        """Construct an aggregate validation SELECT query from a ValidationQuerySpec."""
        if spec.dialect == "oracle":
            register_oracle_dialect_extensions()
        projections = [exp.Var(this=item) for item in spec.select_items]
        from_target = f"{spec.table_identifier} {spec.prior_to_where}".strip()
        select_node = exp.select(*projections, copy=False).from_(exp.Var(this=from_target), copy=False)
        where_sql = combine_validation_filters(spec.where_clauses, dialect=spec.dialect)
        if where_sql:
            select_node = select_node.where(exp.Var(this=where_sql), copy=False)
        if spec.group_by_cols:
            select_node = select_node.group_by(*[exp.Var(this=col) for col in spec.group_by_cols], copy=False)
        if spec.order_by_cols:
            select_node = select_node.order_by(
                *[exp.Ordered(this=exp.Var(this=col)) for col in spec.order_by_cols],
                copy=False,
            )
        rendered = select_node.sql(spec.dialect)
        if spec.query_hints:
            hint_str = spec.query_hints.strip()
            rendered = f"SELECT {hint_str} {rendered[len('SELECT ') :]}"
        return rendered


@lru_cache(maxsize=4)
def get_validation_query_engine(dialect: str = "oracle") -> ValidationQueryEngineProtocol:
    """Return a cached ValidationQueryEngineProtocol instance for the given dialect."""
    return ValidationSqlEngine(dialect=dialect)


def build_verification_clauses(
    offload_source_table,
    ipa_predicate_type,
    verification_hvs,
    prior_hvs,
    offload_predicate=None,
    with_binds=True,
    backend_table=None,
):
    """Build clauses used in verification queries from frontend partition columns and partition key values.
    This function is careful with truthy comparisons and uses is None/is not None because Unix epoch
    is False in numpy.datetime64. In theory numeric HVs of 0 would have the same problem.
    If offload_predicate is active then we only verify rows selected by that predicate.

    For INCREMENTAL_PREDICATE_TYPE_LIST there is only a single column and it has a list of values, therefore
    wrap the hvs in [] to allow it to zip with part col, instead of picking up only the first literal.
    Bulk this out with None to same length as rdbms_part_cols.
    Prior values only applicable for RANGE
    LIST HVs are a list of tuples because a single column can match many partitions,
    each with their own list of HVs
    """

    def get_bind_and_literal(col_hv, bind_counter, bind_pattern, data_type):
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
            if sql_fn:
                where_clause_expr = sql_fn % where_clause_value
            else:
                where_clause_expr = where_clause_value
        return new_bind, where_clause_expr

    if offload_predicate:
        if backend_table:
            where_clause = backend_table.predicate_to_where_clause(offload_predicate)
            return [where_clause], []
        if with_binds:
            (
                where_clause,
                binds,
            ) = offload_source_table.predicate_to_where_clause_with_binds(offload_predicate)
            return [where_clause], binds
        where_clause = offload_source_table.predicate_to_where_clause(offload_predicate)
        return [where_clause], []

    rdbms_part_cols = offload_source_table.partition_columns
    query_params = []
    threshold_clauses = []
    if backend_table:
        enclosure_fn = backend_table.enclose_identifier
    else:
        enclosure_fn = offload_source_table.enclose_identifier

    if rdbms_part_cols and verification_hvs:
        prior_literals, new_literals = [], []
        prior_bind_count, new_bind_count = 0, 0
        if ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST:
            verification_hvs = [verification_hvs]

        if prior_hvs is None:
            prior_hvs = [None for _ in range(len(rdbms_part_cols))]

        for part_col, hv, prior_hv in zip(rdbms_part_cols, verification_hvs, prior_hvs):
            if backend_table:
                backend_column = backend_table.get_column(part_col.name)
                data_type = backend_column.data_type
            else:
                data_type = part_col.data_type

            if prior_hv is not None:
                if ipa_predicate_type in [
                    INCREMENTAL_PREDICATE_TYPE_RANGE,
                    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
                ]:
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


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class CrossDbValidator(OffloadMessagesMixin):
    """Validate that data in front-end (FRONT) database (RDBMS)
    is the same as data in back-end (BACK) database (Hadoop/Cloud backend)

    Important: As of this moment, frontend db assumed to be: ORACLE
    (i.e. internal logic depends on ORACLE dictionary views)
    Also, it's assumed that:
        backend_obj => BackendApi
    """

    def __init__(
        self,
        db_name,
        table_name,
        connection_options,
        backend_obj=None,
        messages=None,
        backend_db=None,
        backend_table=None,
        execute=True,
    ):
        """CONSTRUCTOR

        backend_obj  - BackendApi object
        connection_options - Optparse/Argparse option bundle
        messages - OffloadMessages object

        backend_db, backend_table - Backend db/table name (if different from frontend)

        Execution results and intermediaries
        """
        assert db_name and table_name

        self._execute = execute
        self._db_name = db_name
        self._table_name = table_name
        self._db_table = "%s.%s" % (db_name, table_name)
        self._frontend = frontend_api_factory(
            connection_options.db_type,
            connection_options,
            messages,
            conn_user_override=connection_options.rdbms_app_user,
            dry_run=(not self._execute),
            trace_action=self.__class__.__name__,
        )
        if backend_obj:
            self._backend = backend_obj
        else:
            self._backend = backend_api_factory(
                connection_options.target,
                connection_options,
                messages,
                dry_run=bool(not self._execute),
            )
        self._connection_options = connection_options
        self._messages = messages

        if not backend_db and not backend_table:
            self._offload_metadata = OrchestrationMetadata.from_name(
                self._db_name.upper(),
                self._table_name.upper(),
                connection_options=self._connection_options,
                messages=messages,
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

        self._pexec = ParallelExecutor()

        self._frontend_table = None
        self._frontend_sql = None
        self._backend_sql = None
        self._results = None
        self._success = None

        logger.debug("Initialized CrossDbValidator() object for: %s" % self._db_table)

    def __del__(self):
        if self._frontend:
            self._frontend.close()

    @property
    def frontend_sql(self):
        return self._frontend_sql

    @property
    def backend_sql(self):
        return self._backend_sql

    @property
    def results(self):
        return self._results

    @property
    def success(self):
        return self._success

    def validate(
        self,
        selects=DEFAULT_SELECT_COLS,
        filters=None,
        group_bys=None,
        aggs=DEFAULT_AGGS,
        safe=True,
        as_of_scn=None,
        execute=True,
        frontend_filters=None,
        frontend_query_params=None,
        frontend_parallelism=None,
    ):
        """Main entry point validation routine

        selects:    Either "list of columns" or <number of columns>
                    if <number> -> 12, last and top N columns (by cardinality) will be selected

        filters:    List of (column, oper, value) tuples, i.e. ('prod_id', '<', 23) or
                    List of "expression strings". This allows complex input such as:
                        "((col1 <= 2018 and col2 < 12) or (col1 < 2018))"
                    or
                        "((col1 <= :year and col2 < :month) or (col1 < :year))"

        group_bys:  List of expressions to GROUP BY result (will also ORDER BY the same list)

        aggs:       List of aggragate functions to calculate on each column, i.e. ('min', 'max', 'count')
                    Functions must exist in both FRONT add BACK database

        safe:       True = include additional "offload boundary" filter

        as_of_scn:  Execute (frontend) query as of SCN

        execute:    True = execute validation

        frontend_filters: Same format as filters but allows an override when frontend is not the same, e.g. binds

        frontend_query_params: Optional list of QueryParameter objects

        frontend_parallelism: See Offload option --verify-parallelism

        Expand SELECTs if necessary
        Expand FILTERs if necessary
        Expand GROUPBYs if necessary
        """
        logger.info("Validating table: %s" % self._db_table)
        logger.debug(
            "Parameters: SELECT: %s, WHERE: %s, GROUP BY: %s AS OF: %s" % (selects, filters, group_bys, as_of_scn)
        )

        if frontend_query_params:
            assert isinstance(frontend_query_params, list)
            assert isinstance(frontend_query_params[0], QueryParameter)

        selects = self._get_select_cols(selects, aggs)
        backend_filters = self._get_filters(filters, safe)
        group_bys = self._get_group_bys(group_bys)
        frontend_filters = frontend_filters or self._get_filters(filters, safe, frontend=True)
        frontend_hint_block = ""
        if frontend_parallelism is not None:
            frontend_hint_block = self._get_frontend_query_hint_block(frontend_parallelism)
        self._frontend_sql, front_selects = self._construct_simple_front_agg_sql(
            selects, frontend_filters, group_bys, aggs, as_of_scn, frontend_hint_block
        )
        self._backend_sql = self._construct_simple_back_agg_sql(selects, backend_filters, group_bys, aggs)
        agg_message = "Compared aggregations of columns: %s" % ", ".join(selects)

        if execute:
            self._results = self._run_sqls(self._frontend_sql, self._backend_sql, frontend_query_params)
            self._success = self._compare_results(self._results, front_selects, group_bys)

            logger.info("Validating table: %s. Valid: %s" % (self._db_table, self._success))
            return self._success, agg_message
        logger.info("Skipping validation for table: %s as execute=False" % self._db_table)
        self.log_verbose("Frontend sql: %s" % self._frontend_sql)
        self.log_verbose("Backend sql: %s" % self._backend_sql)
        return True, agg_message

    def _get_frontend_table(self):
        """Connection we already have in self._frontend cannot be passed into OffloadSourceTable

        because one is GOE_APP and the other is GOE_ADM
        """
        if not self._frontend_table:
            if self._offload_metadata:
                self._frontend_table = OffloadSourceTable.create(
                    self._offload_metadata.offloaded_owner,
                    self._offload_metadata.offloaded_table,
                    self._connection_options,
                    self._messages,
                )
            else:
                self._frontend_table = OffloadSourceTable.create(
                    self._db_name,
                    self._table_name,
                    self._connection_options,
                    self._messages,
                )
        return self._frontend_table

    def _get_sample_cols(self, required_no):
        """Get sample of columns from self._db_table"""
        return self._frontend.agg_validate_sample_column_names(
            self._db_name.upper(), self._table_name.upper(), num_required=required_no
        )

    def _get_group_bys(self, group_bys):
        """Analyze and expand GROUP BY columns"""
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

        logger.info("GROUPING BY columns: %s" % group_bys)
        return group_bys

    def _get_select_cols(self, select_cols, aggs):
        """Analyze 'requested' select_cols and return a full list of columns
        to run aggregations on

        Set the floor for column sample
        """
        if is_number(select_cols):
            select_cols = max(int(select_cols), 1)
            select_cols = self._get_sample_cols(select_cols)
        elif isinstance(select_cols, (list, tuple)):
            frontend_table = self._get_frontend_table()
            select_cols = expand_columns_csv(
                ",".join(select_cols),
                frontend_table.columns,
                retain_non_matching_names=True,
            )
        else:
            raise CrossDbValidatorException("Invalid list of SELECTs: %s" % select_cols)

        logger.info("Calculating %s AGGREGATEs on columns: %s" % (aggs, select_cols))
        if not select_cols:
            raise CrossDbValidatorException("Unable to identify columns for table: %s" % self._db_table)
        return select_cols

    def _get_partition_columns(self):
        """Extract table partition columns (if any)"""
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
        selects,
        filters,
        group_bys,
        aggs,
        as_of_scn=None,
        db_name=None,
        table_name=None,
        frontend_hint_block=None,
    ):
        """Construct frontend aggregate validation SQL via ValidationQueryEngineProtocol."""
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

    def _construct_simple_front_agg_sql(self, selects, filters, group_bys, aggs, as_of_scn, frontend_hint_block):
        """Construst FRONT-END (== ORACLE) aggregate SQL"""
        return self._construct_simple_agg_sql(
            selects,
            self._adjust_filters_front(filters),
            group_bys,
            aggs,
            as_of_scn=as_of_scn,
            frontend_hint_block=frontend_hint_block,
        )

    def _construct_simple_back_agg_sql(self, selects, filters, group_bys, aggs):
        """Construct BACK-END aggregate SQL"""
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

    def _adjust_filters_front(self, filters):
        """Adjust and AST-validate filters for the FRONT-END (Oracle) database."""
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

    def _adjust_filters_back(self, filters):
        """Adjust and AST-validate filters for the BACK-END database."""
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

    def _run_sqls(self, front_sql, back_sql, front_binds=None):
        """Run front end and back end SQL and return results as:
        {'FRONT': ..., 'BACK': ...}
        front_binds can be used to cater for binds

        Run in parallel, because, why not ?
        """

        def exec_sql_front(obj, sql, binds=None):
            return obj.execute_query_fetch_all(sql, query_params=binds, log_level=VERBOSE)

        def exec_sql_back(obj, sql):
            return obj.execute_query_fetch_all(sql, log_level=VERBOSE)

        self._pexec.execute_in_threads(
            2,
            [
                [exec_sql_front, ENGINE_FRONT, self._frontend, front_sql, front_binds],
                [exec_sql_back, ENGINE_BACK, self._backend, back_sql],
            ],
            ids=True,
        )

        return self._pexec.tasks

    def _compare_results(self, results, front_selects, group_bys):
        """Compare FRONT and BACK results

        Returns: True if all results match, False otherwise

        Note: Functional style loops because, why not ?

        Re-format 'results' by combining FRONT/BACK results together
        in (row, col, front_result, back_result) tuples
        And compare
        """

        def col_name(col_no):
            return front_selects[col_no]

        def front_and_back_match(front, back):
            """TODO: maxym@ 2016-09-14

            Somewhat dubious isclose(float(), float()) comparison
            Works for now, but may need to find a better way to compare
            This may be a backend DATE which we need to convert to datetime.date because of Impyla issue 410:
            https://github.com/cloudera/impyla/issues/410
            """
            matched = False
            if is_number(front) and is_number(back) and isclose(float(front), float(back)):
                matched = True
            elif isinstance(front, date) and isinstance(back, (date, str)):
                if isinstance(back, str):
                    back = datetime.strptime(back, "%Y-%m-%d").date()
                if front.strftime("%Y-%m-%d %H:%M:%S.%f") == back.strftime("%Y-%m-%d %H:%M:%S.%f"):
                    matched = True
            elif str(front) == str(back):
                matched = True
            return matched

        def merge_front_end_results(front_results, back_results):
            """Transform: [
                [(row0_col0, row0_col1, ...), (row1_col0, row1_col1, ..)], # FRONT
                [(row0_col0, row0_col1, ...), (row1_col0, row1_col1, ..)]  # BACK
            ]

            Into: [
                [(0, 0, front_row0_col0, back_row0_col0), (0, 1, front_row0_col1, back_row0_col1), .. ],
                [(1, 0, front_row1_col0, back_row1_col0), (1, 1, front_row1_col1, back_row1_col1), .. ],
                ..
            ]

            All rows should have the same # of columns
            """
            no_columns = len(front_results[0])
            joined_results = []
            for row_no, _ in enumerate(front_results):
                row_results = []
                for col_no in range(no_columns):
                    row_results.append(
                        (
                            row_pk(front_results[row_no]),
                            col_name(col_no),
                            front_results[row_no][col_no],
                            back_results[row_no][col_no],
                        )
                    )
                joined_results.append(row_results)

            return joined_results

        def process_rows(row):
            """Only process 'statistical' data, skip row PKs"""
            pk_len = len(group_bys) if group_bys else 0
            return all(process_columns(_) for _ in row[pk_len:])

        def process_columns(column):
            row_pk, col_name, front, back = column
            matched = front_and_back_match(front, back)
            if not matched:
                self.warn(
                    "Results for [%s]: %s do NOT match - FRONT: %s vs BACK: %s"
                    % (row_pk, col_name, str_floatlike(front), str_floatlike(back))
                )
                return False
            logger.debug("Results for [%s]: %s match - FRONT: %s vs BACK: %s" % (row_pk, col_name, front, back))
            return True

        def row_pk(row):
            if group_bys:
                no_pk_cols = len(group_bys)
                pk = list(zip(front_selects[:no_pk_cols], row[:no_pk_cols]))
                return ", ".join("%s: %s" % (k, v) for k, v in pk)
            return "TOTAL"

        def rows(results):
            return 0 if not results or not isinstance(results, (list, tuple)) else len(results)

        def cols(results):
            return (
                0
                if not results
                or not isinstance(results, list)
                or len(results) == 0
                or not isinstance(results[0], (list, tuple))
                else len(results[0])
            )

        front_results, back_results = results[ENGINE_FRONT], results[ENGINE_BACK]

        if results == [[], []]:
            logger.warning("Results are EMPTY")
            return True
        if front_results == False:
            raise CrossDbValidatorException("FRONT-END SQL execution failed")
        if back_results == False:
            raise CrossDbValidatorException("BACK-END SQL execution failed")
        if rows(front_results) != rows(back_results):
            logger.warning(
                "Result (row) dimensions do not match: FRONT: %d BACK: %d" % (rows(front_results), rows(back_results))
            )
            return False
        if cols(front_results) != cols(back_results):
            logger.warning(
                "Result (column) dimensions do not match: FRONT: %d BACK: %d"
                % (cols(front_results), cols(back_results))
            )
            return False
        results = merge_front_end_results(front_results, back_results)
        logger.debug("Validating cross results: %s" % results)

        return all(map(process_rows, results))

    def _resolve_oracle_date(self, oracle_date):
        """Run a query to resolve ORACLE date to Python date

        TODO: maxym@ 2016-08-31
        I'm feeling lazy to write oracle-to-python data format parser
        so, calling ORACLE to convert instead
        Obviously, inefficient and might need a re-write

        Special case for NULLs
        """
        if oracle_date is None:
            return None

        sql = "select %s as dt from dual" % oracle_date
        query_result = self._frontend.execute_query_fetch_one(sql)
        logger.debug("Resolved ORACLE date expression: %s to python date: %s" % (oracle_date, query_result[0]))

        return query_result[0]

    def _extract_offload_boundary(self, frontend=False):
        """Extract offload boundary for offloaded table
        Returns a string value ready to be plugged in to a SQL statement.
        """
        if not self._offload_metadata:
            logger.debug("No metadata therefore no boundary for table: %s" % self._db_table)
            return ""

        rdbms_table = self._get_frontend_table()
        if frontend:
            backend_table = None
        else:
            backend_table = backend_table_factory(
                self._offload_metadata.backend_owner,
                self._offload_metadata.backend_table,
                self._backend.backend_type(),
                self._connection_options,
                self._messages,
                hybrid_metadata=self._offload_metadata,
                existing_backend_api=self._backend,
                dry_run=(not self._execute),
            )
        (
            inc_keys,
            hv_real_vals,
            hv_indiv_vals,
        ) = decode_metadata_incremental_high_values_from_metadata(self._offload_metadata, rdbms_table)
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
        offload_boundary = hybrid_view_combine_hv_and_pred_clauses(lt_clause, offloaded_pred, "OR")

        logger.debug("Extracted offload boundary for table: %s as: %s" % (self._db_table, offload_boundary))
        return offload_boundary

    def _add_boundary_filters(self, filters, frontend=False):
        """Extract 'offloaded data boundary' and add to FILTERs"""
        offload_boundary = self._extract_offload_boundary(frontend=frontend)
        new_filters = []
        if filters:
            new_filters.extend(filters)
        if offload_boundary:
            new_filters.append(offload_boundary)
        return new_filters

    def _get_filters(self, filters, safe, frontend=False):
        """Analyze and expand filters

        Add 'offloaded data ' boundary FILTERs
        """
        if safe:
            filters = self._add_boundary_filters(filters, frontend=frontend)

        logger.info("Applying FILTERs: %s" % filters)
        return filters

    def _get_frontend_query_hint_block(self, frontend_parallelism):
        """Hints only supported for Oracle"""
        if frontend_parallelism is None:
            return ""
        if self._connection_options.db_type != DBTYPE_ORACLE:
            return ""
        frontend_table = self._get_frontend_table()
        return frontend_table.enclose_query_hints(frontend_table.parallel_query_hint(frontend_parallelism))


class BackendCountValidator:
    """Validate data volume in the frontend table matches that in the backend table using COUNT(*) queries."""

    def __init__(self, frontend_table, backend_table, messages, dry_run=False):
        """CONSTRUCTOR
        messages - OffloadMessages object, None means no logging
        """
        self._frontend_table = frontend_table
        self._backend_table = backend_table
        self._messages = messages
        self._dry_run = dry_run

    def validate(
        self,
        frontend_filters,
        frontend_query_params,
        backend_filters,
        frontend_hint_block=None,
    ):
        """Main entry point for frontend vs backend validation by count routine

        frontend_filters: List of filters passed through from Offload
        frontend_binds: Optional list of frontend query parameters (e.g. bind variable values)
        backend_filters: Same format as frontend_filters but formatted for backend
        frontend_hint_block: See Offload option --verify-parallelism

        We set not_when_dry_running=True for count calls because we don't want to actually run the counts, we
        just want to log the SQL we intend to run when in preview mode.

        Combine all filters into a single filter
        """
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

    def _log(self, msg, detail=None, ansi_code=None):
        """Write to offload log file."""
        self._messages.log(msg, detail=detail, ansi_code=ansi_code)
        if detail == VVERBOSE:
            logger.debug(msg)
        else:
            logger.info(msg)
