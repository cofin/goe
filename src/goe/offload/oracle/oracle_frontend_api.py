#! /usr/bin/env python3

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OracleFrontendApi: Library for logic/interaction with an Oracle frontend.
Implements abstract methods from FrontendApiInterface.
"""

import logging
import traceback
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

import oracledb as cxo
from numpy import datetime64

from goe.observability.db import apply_oracle_session_trace_info
from goe.offload import offload_constants
from goe.offload.column_metadata import match_table_column
from goe.offload.frontend_api import (
    FETCH_ACTION_ALL,
    FETCH_ACTION_CURSOR,
    FETCH_ACTION_ONE,
    FRONTEND_TRACE_ID,
    FRONTEND_TRACE_MODULE,
    FrontendApiException,
    FrontendApiInterface,
    QueryParameter,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.oracle.oracle_column import (
    ORACLE_SPLIT_HIGH_VALUE_RE,
    ORACLE_TYPE_VARCHAR2,
    OracleColumn,
)
from goe.offload.oracle.oracle_literal import OracleLiteral
from goe.persistence.oracle_gateway import OracleGateway, load_sql_file
from goe.util.goe_version import GOEVersion
from goe.util.misc_functions import double_quote_sandwich, format_list_for_logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


MAX_DEPENDENCY_DEPTH = 100

ORACLE_VERSION_WITH_128_BYTE_IDENTIFIERS = "12.2.0"

CREATE_TABLE_ORACLE_PARTITION_SPEC = "partition_spec"

FRONTEND_METADATA_SQL_PATH = Path(__file__).resolve().parent / "sql" / "frontend_metadata.sql"

RECONNECT_ERROR_MARKERS = (
    "ORA-02396",
    "ORA-2396",
    "ORA-03113",
    "ORA-3113",
    "ORA-03114",
    "ORA-3114",
    "ORA-03135",
    "ORA-3135",
)


def switch_oracle_open_partition_token(frontend_token):
    if frontend_token and frontend_token.upper() == "MAXVALUE":
        return offload_constants.PART_OUT_OF_RANGE
    if frontend_token and frontend_token.upper() == "DEFAULT":
        return offload_constants.PART_OUT_OF_LIST
    return frontend_token


class OracleFrontendApi(FrontendApiInterface):
    """Oracle FrontendApi implementation"""

    def __init__(
        self,
        connection_options,
        frontend_type,
        messages,
        conn_user_override=None,
        existing_connection=None,
        dry_run=False,
        do_not_connect=False,
        trace_action=None,
    ):
        """Standard CONSTRUCTOR

        Unit testing requires no db connection.
        Be careful caching in state, only cache values that cannot change for a different set of inputs
        such as for a different db_user or table_name.
        """
        super().__init__(
            connection_options,
            frontend_type,
            messages,
            conn_user_override=conn_user_override,
            existing_connection=existing_connection,
            dry_run=dry_run,
            do_not_connect=do_not_connect,
            trace_action=trace_action,
        )

        logger.debug("OracleFrontendApi")
        if dry_run:
            logger.debug("* Dry run *")

        self._trace_action = self.v_session_safe_action(self._trace_action)

        self._db_conn = None
        self._db_curs = None
        self._metadata_gateway = OracleGateway(
            self.get_validated_oracle_connection, load_sql_file(FRONTEND_METADATA_SQL_PATH)
        )
        if not do_not_connect:
            self._connect()

        self._instance_compatible = None
        self._max_table_name_length = None

    def __del__(self):
        """Clean up connection"""
        try:
            self._disconnect()
        except Exception:
            pass

    def v_session_safe_action(self, action):
        """V$SESSION.ACTION is limited to 64 characters."""
        if action and isinstance(action, str) and len(action) > 64:
            action = action[:61] + "..."
        return action

    def close(self, force=False):
        self._disconnect(force=force)

    def agg_validate_sample_column_names(self, schema: Any, table_name: Any, num_required: int = 5) -> list:
        params = {"owner": schema, "table_name": table_name, "required_no": num_required}
        self._log_or_not(
            "%s SQL: %s"
            % (self._sql_engine_name, self._metadata_gateway.statement_text("agg_validate_sample_column_names")),
            log_level=VVERBOSE,
        )
        self._log_or_not(
            "Bind values:\n%s" % "\n".join("%s = %s" % (k, v) for k, v in params.items()), log_level=VVERBOSE
        )
        rows = self._metadata_gateway.select_tuples("agg_validate_sample_column_names", params)
        return [_[0] for _ in rows or []]

    def create_new_connection(self, user_name, user_password, trace_action_override=None):
        self._debug("Making new connection with user %s" % user_name)
        client = cxo.connect(
            user=user_name,
            password=user_password,
            dsn=self._connection_options.rdbms_dsn,
        )
        client.module = FRONTEND_TRACE_MODULE
        client.action = trace_action_override or self._trace_action
        return client

    def enclose_identifier(self, identifier):
        if identifier is None:
            return None
        return double_quote_sandwich(identifier)

    def enclose_query_hints(self, hint_contents):
        if not hint_contents:
            return ""
        if isinstance(hint_contents, str):
            hint_contents = [hint_contents]
        return "/*+ {} */".format(" ".join(str(_) for _ in hint_contents if _))

    def enclosure_character(self):
        return '"'

    def execute_function(
        self,
        sql_fn,
        return_type=None,
        return_type_name=None,
        arg_list=None,
        log_level=VERBOSE,
        not_when_dry_running=False,
        commit=False,
    ):
        return self._execute_plsql_function(
            sql_fn,
            return_type=return_type,
            return_type_name=return_type_name,
            arg_list=arg_list,
            log_level=log_level,
            not_when_dry_running=not_when_dry_running,
            commit=commit,
        )

    def fetchmany_takes_fetch_size(self):
        return False

    def format_query_parameter(self, param_name):
        assert param_name
        return f":{param_name}"

    def frontend_version(self):
        if self._db_conn:
            return self._db_conn.version
        return None

    def gen_column_object(self, column_name, **kwargs):
        return OracleColumn(column_name, **kwargs)

    def generic_string_data_type(self) -> str:
        return ORACLE_TYPE_VARCHAR2

    def get_columns(self, schema, table_name):
        rows = self._metadata_gateway.select_tuples("get_columns", {"owner": schema, "table_name": table_name})
        return [OracleColumn.from_oracle(row) for row in rows or []]

    def get_current_scn(self) -> int | None:
        """Return the current system change number for the source RDBMS."""
        rows = self._metadata_gateway.select_tuples("get_current_scn")
        return rows[0][0] if rows else None

    def get_db_unique_name(self) -> str:
        rows = self._metadata_gateway.select_tuples("get_db_unique_name")
        return cast(str, rows[0][0] if rows else None)

    def get_distinct_column_values(self, schema, table_name, column_names, partition_name=None, order_results=False):
        assert schema and table_name
        assert column_names
        if isinstance(column_names, str):
            column_names = [column_names]
        projection = ",".join([self.enclose_identifier(_) for _ in column_names])
        partition_clause = f" PARTITION ({partition_name})" if partition_name else ""
        order_clause = f" ORDER BY {projection}" if order_results else ""
        sql = "SELECT DISTINCT %(col)s FROM %(own)s.%(tab)s%(part_clause)s%(order_clause)s" % {
            "col": projection,
            "own": self.enclose_identifier(schema.upper()),
            "tab": self.enclose_identifier(table_name.upper()),
            "part_clause": partition_clause,
            "order_clause": order_clause,
        }
        self._messages.log("Distinct column SQL: %s" % sql, detail=VVERBOSE)
        return self.execute_query_fetch_all(sql)

    def get_object_ddl(
        self,
        schema,
        object_name,
        object_type,
        as_list=False,
        terminate_sql=False,
        remap_schema=None,
    ):
        return self._get_ddl(
            schema,
            object_name,
            object_type,
            as_list=as_list,
            terminate_sql=terminate_sql,
            remap_schema=remap_schema,
        )

    def get_oracle_connection_object(self):
        """Return an Oracle connection object. Oracle specific method not provided by other frontends."""
        return self._db_conn

    def get_validated_oracle_connection(self) -> "cxo.Connection | None":
        """Return the live connection after ``_open_cursor`` tagging and reconnect checks, or ``None`` if unconnected.

        Oracle-specific method used as the ``OracleGateway`` connection provider so gateway queries keep the same
        ``TRACEFILE_IDENTIFIER`` tagging and sniped-session reconnect as ``execute_query_fetch_*``.
        """
        self._open_cursor()
        self._close_cursor()
        return self._db_conn

    def get_partition_column_names(self, schema, table_name, conv_fn=None):
        names = self._get_partition_column_names(schema, table_name)
        return [conv_fn(_) for _ in names or []] if conv_fn else names

    def get_partition_columns(self, schema, table_name):
        table_columns = self.get_columns(schema, table_name)
        part_cols = []
        for part_col in self._get_partition_column_names(schema, table_name):
            part_cols.append(match_table_column(part_col, table_columns))
        return part_cols

    def get_primary_key_column_names(self, schema, table_name):
        rows = self._metadata_gateway.select_tuples(
            "get_primary_key_column_names", {"owner": schema, "table_name": table_name}
        )
        return [_[0] for _ in rows] if rows else []

    def get_session_option(self, option_name):
        """Using v$parameter to retrieve value for a parameter.
        Not using GV$ because we want the value for the session which is from the instance to which we
        are connected. Making this RAC aware would make it trickier to maintain an interface across all RDBMSs.
        """
        logger.debug(f"Fetching {option_name} from DB")
        return self._execute_plsql_function("offload.get_init_param", return_type=str, arg_list=[option_name])

    def get_session_user(self) -> str:
        rows = self._metadata_gateway.select_tuples("get_session_user")
        return cast(str, rows[0][0] if rows else None)

    def get_subpartition_column_names(self, schema, table_name, conv_fn=None):
        names = self._get_partition_column_names(schema, table_name, subpartition_level=True)
        return [conv_fn(_) for _ in names or []] if conv_fn else names

    def get_subpartition_columns(self, schema, table_name):
        table_columns = self.get_columns(schema, table_name)
        part_cols = []
        for part_col in self._get_partition_column_names(schema, table_name, subpartition_level=True):
            part_cols.append(match_table_column(part_col, table_columns))
        return part_cols

    def get_table_default_parallelism(self, schema, table_name):
        rows = self._metadata_gateway.select_tuples(
            "get_table_default_parallelism", {"owner": schema, "table_name": table_name}
        )
        return rows[0][0] if rows else None

    def get_table_row_count(
        self,
        schema,
        table_name,
        filter_clause=None,
        filter_clause_params=None,
        hint_block=None,
        not_when_dry_running=False,
        log_level=VVERBOSE,
    ):
        where_clause = f" WHERE {filter_clause}" if filter_clause else ""
        hint_clause = f" {hint_block}" if hint_block else ""
        sql = "SELECT%s COUNT(*) FROM %s%s" % (
            hint_clause,
            self.enclose_object_reference(schema, table_name),
            where_clause,
        )
        row = self.execute_query_fetch_one(
            sql,
            query_params=filter_clause_params,
            log_level=log_level,
            not_when_dry_running=not_when_dry_running,
        )
        return row[0] if row else None

    def get_table_size(self, schema, table_name):
        """Total size (in bytes) of segments for a table.
        NB: does not currently include LOB or overflow segments
        """
        logger.debug("get_table_size: %s, %s" % (schema, table_name))
        query_name = "get_iot_table_size" if self._is_iot(schema, table_name) else "get_table_size"
        rows = self._metadata_gateway.select_tuples(query_name, {"owner": schema, "table_name": table_name})
        return rows[0][0] if rows else None

    def is_view(self, schema: Any, object_name: Any) -> bool:
        return self.view_exists(schema, object_name)

    def max_datetime_scale(self) -> int:
        """Oracle supports up to nanoseconds"""
        return 9

    def max_datetime_value(self):
        return datetime64("9999-12-31")

    def max_table_name_length(self):
        """This maximum identifier length on Oracle changed in 12.2 therefore we must check DB compatible"""

        def oracle_max_table_name_length(instance_compatible):
            if GOEVersion(instance_compatible) >= GOEVersion(ORACLE_VERSION_WITH_128_BYTE_IDENTIFIERS):
                return 128
            return 30

        if not self._max_table_name_length:
            self._max_table_name_length = oracle_max_table_name_length(self._get_instance_compatible())
        return self._max_table_name_length

    def min_datetime_value(self):
        return datetime64("-4712-01-01")

    def oracle_get_column_low_high_dates(self, schema, table_name, column_name):
        """Expose a specific call to offload.get_column_low_high_dates() procedure.
        Only ever likely to be implemented for Oracle hence the name of the method and absence of abstractmethod.
        Wanted the code in here so cursor management is not in higher level APIs.
        """
        logger.debug("Calling get_column_low_high_dates")
        self._open_cursor()
        try:
            assert self._db_curs is not None
            low = self._db_curs.var(cxo.DB_TYPE_DATE)
            high = self._db_curs.var(cxo.DB_TYPE_DATE)
            self._db_curs.callproc(
                "offload.get_column_low_high_dates",
                [schema, table_name, column_name, low, high],
            )
            low_val = low.getvalue() if low else None
            high_val = high.getvalue() if high else None
            return (
                datetime64(low_val) if low_val is not None else None,
                datetime64(high_val) if high_val is not None else None,
            )
        finally:
            self._close_cursor()

    def oracle_get_type_object(self, type_owner_name):
        """Returns a oracledb type object.
        Only ever likely to be implemented for Oracle hence the name of the method and absence of abstractmethod.
        Wanted the code in here so oracledb is not directly exposed to higher level APIs, although you could
        argue that returning the type object is just as bad.
        """
        assert self._db_conn is not None
        ora_type = self._db_conn.gettype(type_owner_name)
        return ora_type.newobject()

    def parallel_query_hint(self, query_parallelism):
        if query_parallelism:
            assert isinstance(query_parallelism, int)
        if query_parallelism in [0, 1]:
            return "NO_PARALLEL"
        if query_parallelism and query_parallelism > 1:
            return "PARALLEL(%s)" % query_parallelism
        return ""

    def split_partition_high_value_string(self, hv_string):
        """Break up high value by comma while respecting parentheses in TO_DATE(...,...,...)
        TIMESTAMPs don't contain commas and are therefore not a special case.
        """
        if not hv_string:
            return []
        tokens = [hv_val.strip() for hv_val in ORACLE_SPLIT_HIGH_VALUE_RE.findall(hv_string)]
        tokens = [switch_oracle_open_partition_token(_) for _ in tokens]
        return tokens

    def schema_exists(self, schema: Any) -> bool:
        return bool(self._metadata_gateway.select_tuples("schema_exists", {"schema": schema}))

    def table_exists(self, schema: Any, table_name: Any) -> bool:
        return bool(self._metadata_gateway.select_tuples("table_exists", {"owner": schema, "table_name": table_name}))

    def to_frontend_literal(self, py_val: Any, data_type: Any = None) -> str:
        self._debug("Formatting %s literal: %s" % (type(py_val), repr(py_val)))
        self._debug("For data type: %s" % data_type)
        new_py_val = OracleLiteral.format_literal(py_val, data_type=data_type)
        self._debug("Final %s literal: %s" % (type(py_val), str(new_py_val)))
        return new_py_val

    def view_exists(self, schema: Any, view_name: Any) -> bool:
        return bool(self._metadata_gateway.select_tuples("view_exists", {"owner": schema, "view_name": view_name}))

    def _conn_user_and_pass_for_override(self):
        """Return a user and password from connection_options object for the override user

        Assume we want to proxy to a hybrid schema through the adm user
        """
        assert self._conn_user_override
        if self._conn_user_override.upper() == self._upper_or_empty(self._connection_options.ora_adm_user):
            return (
                self._connection_options.ora_adm_user,
                self._connection_options.ora_adm_pass,
            )
        if self._conn_user_override.upper() == self._upper_or_empty(self._connection_options.ora_app_user):
            return (
                self._connection_options.ora_app_user,
                self._connection_options.ora_app_pass,
            )
        return (
            "%s[%s]" % (self._connection_options.ora_adm_user, self._conn_user_override),
            self._connection_options.ora_app_pass,
        )

    def _close_cursor(self):
        if self._db_conn and self._db_curs:
            try:
                self._db_curs.close()
            except Exception as exc:
                self._log("Exception closing cursor:\n%s" % str(exc), detail=VVERBOSE)
        self._db_curs = None

    def _connection_output_type_handler(self, cursor, name, default_type, size, precision, scale):
        if default_type == cxo.DB_TYPE_CLOB:
            return cursor.var(getattr(cxo, "DB_TYPE_LONG_STRING", None), arraysize=cursor.arraysize)
        if default_type == cxo.DB_TYPE_BLOB:
            return cursor.var(cxo.DB_TYPE_LONG_RAW, arraysize=cursor.arraysize)

    def _connect(self):
        made_new_connection = False
        if self._existing_connection:
            self._db_conn = self._existing_connection
        else:
            dsn = self._connection_options.rdbms_dsn
            if self._connection_options.use_oracle_wallet:
                if self._conn_user_override and self._conn_user_override.upper() not in [
                    self._upper_or_empty(self._connection_options.ora_adm_user),
                    self._upper_or_empty(self._connection_options.ora_app_user),
                ]:
                    self._debug("Proxying to DSN [%s]%s" % (self._conn_user_override, dsn))
                    self._db_conn = cxo.connect(user="[%s]" % self._conn_user_override, dsn=dsn)
                else:
                    self._debug("Connecting to DSN %s" % dsn)
                    self._db_conn = cxo.connect(dsn=dsn)
            elif self._conn_user_override:
                conn_user, conn_pass = self._conn_user_and_pass_for_override()
                self._debug("Connecting to %s" % conn_user)
                self._db_conn = cxo.connect(user=conn_user, password=conn_pass, dsn=dsn)
            else:
                self._debug("Connecting to %s" % self._connection_options.ora_adm_user)
                self._db_conn = cxo.connect(
                    user=self._connection_options.ora_adm_user,
                    password=self._connection_options.ora_adm_pass,
                    dsn=dsn,
                )
            made_new_connection = True
        self._db_conn.module = FRONTEND_TRACE_MODULE
        self._db_conn.action = self._trace_action
        self._db_conn.outputtypehandler = self._connection_output_type_handler
        apply_oracle_session_trace_info(self._db_conn)
        self._db_conn.ping()
        return made_new_connection

    def _create_table_sql_text(
        self,
        schema: Any,
        table_name: Any,
        column_list: Any,
        partition_column_names: Any,
        table_properties: Any = None,
    ) -> str:
        if table_properties:
            raise NotImplementedError(f"Create table properties pending implementation: {table_properties}")

        col_projection = self._create_table_columns_clause_common(column_list)

        partition_clause = ""
        if partition_column_names:
            for part_col in partition_column_names:
                real_col = match_table_column(part_col, column_list)
                if not real_col:
                    raise FrontendApiException("Partition column is not in proposed table columns: %s" % part_col)
            assert table_properties and CREATE_TABLE_ORACLE_PARTITION_SPEC in table_properties
            raise NotImplementedError("Create table partitioning pending implementation")

        sql = dedent("""\
            CREATE TABLE %(owner_table)s (
                %(col_projection)s
            )%(partition_clause)s""") % {
            "owner_table": self.enclose_object_reference(schema, table_name),
            "col_projection": col_projection,
            "partition_clause": partition_clause,
        }
        return sql

    def _cx_getvalue(self, incoming):
        return incoming.getvalue() if incoming and hasattr(incoming, "getvalue") else incoming

    def _disconnect(self, force=False):
        self._debug("Disconnecting from DB")
        if not self._existing_connection or force:
            if self._db_curs:
                self._close_cursor()
            try:
                if self._db_conn:
                    self._db_conn.close()
                    self._db_conn = None
            except Exception as exc:
                self._log("Exception closing connection:\n%s" % str(exc), detail=VVERBOSE)
            self._existing_connection = None

    def _execute_ddl_or_dml(
        self,
        sql,
        query_options=None,
        log_level=VERBOSE,
        trace_action=None,
        query_params=None,
    ):
        """Run SQL that has no result set, e.g. DDL, sql can be a str or a list of SQLs.
        Always opens/closes a fresh cursor to ensure we have a clean session environment with no settings
        carried forwards from a previous action. All SQLs in sql are executed in the same query environment.
        """
        assert sql
        assert isinstance(sql, (str, list))

        self._open_cursor()
        if trace_action and self._db_conn:
            self._db_conn.action = self.v_session_safe_action(trace_action)
        run_opts = self._execute_session_options(query_options, log_level=log_level)
        run_sqls = []
        sqls = [sql] if isinstance(sql, str) else sql
        for i, run_sql in enumerate(sqls):
            self._log_or_not("%s SQL: %s" % (self._sql_engine_name, run_sql), log_level=log_level)
            run_sqls.append(run_sql)
            if not self._dry_run:
                assert self._db_curs is not None
                if query_params:
                    self._log_or_not("Bind values:", log_level=log_level)
                    self._log_or_not(
                        "\n".join("%s = %s" % (k, v) for k, v in self._to_native_query_params(query_params).items()),
                        log_level=log_level,
                    )
                    self._db_curs.execute(run_sql, self._to_native_query_params(query_params))
                else:
                    self._db_curs.execute(run_sql)
        self._close_cursor()
        if trace_action and self._db_conn:
            self._db_conn.action = self._trace_action
        return run_opts + run_sqls

    def _execute_plsql_function(
        self,
        sql_fn,
        return_type=None,
        return_type_name=None,
        arg_list=None,
        log_level=None,
        not_when_dry_running=False,
        commit=False,
    ):
        """Wrapper over oracledb callfunc to additionally get and close a cursor"""
        logger.debug("Calling SQL function %s" % sql_fn)
        self._open_cursor()
        try:
            self._log_or_not("%s SQL: %s" % (self._sql_engine_name, sql_fn), log_level=log_level)
            if arg_list:
                assert isinstance(arg_list, list)
                self._log_or_not(f"Arguments: {arg_list!s}", log_level=log_level)
            if self._dry_run and not_when_dry_running:
                return None

            assert self._db_curs is not None
            if return_type:
                if return_type == cxo.DB_TYPE_OBJECT and return_type_name:
                    assert self._db_conn is not None
                    return_type = self._db_conn.gettype(return_type_name)
                if arg_list:
                    return_val = self._db_curs.callfunc(sql_fn, return_type, arg_list)
                else:
                    return_val = self._db_curs.callfunc(sql_fn, return_type)
                return self._cx_getvalue(return_val)
            if arg_list:
                self._db_curs.callproc(sql_fn, arg_list)
            else:
                self._db_curs.callproc(sql_fn)
            return None
        finally:
            self._close_cursor()
            if commit and self._db_conn:
                self._db_conn.commit()

    def _execute_query_fetch_x(
        self,
        sql,
        fetch_action=FETCH_ACTION_ALL,
        query_options=None,
        log_level=None,
        time_sql=False,
        not_when_dry_running=False,
        query_params=None,
        profile=False,
        trace_action=None,
        as_dict=False,
    ):
        """Run a query, fetch and return the results.
        Always opens/closes a fresh cursor to ensure we have a clean session environment with no settings
        carried forwards from a previous action.
        """

        def log_query():
            self._log_or_not("%s SQL: %s" % (self._sql_engine_name, sql), log_level=log_level)
            if query_params:
                self._log_or_not("Bind values:", log_level=log_level)
                self._log_or_not(
                    "\n".join("%s = %s" % (k, v) for k, v in self._to_native_query_params(query_params).items()),
                    log_level=log_level,
                )

        assert sql

        if trace_action and self._db_conn:
            self._db_conn.action = self.v_session_safe_action(trace_action)

        profile_dict = {}
        if profile and fetch_action in (FETCH_ACTION_ALL, FETCH_ACTION_ONE):
            profile_dict = self._instrumentation_snap()
        t1 = datetime.now().replace(microsecond=0)

        if (self._dry_run and not_when_dry_running) or self._db_conn is None:
            log_query()
            return None

        self._open_cursor()
        try:
            self._execute_session_options(query_options, log_level=log_level)
            log_query()
            assert self._db_curs is not None
            if query_params:
                self._db_curs.execute(sql, self._to_native_query_params(query_params))
            else:
                self._db_curs.execute(sql)
            if as_dict:
                columns = self._cursor_projection(self._db_curs)
                self._db_curs.rowfactory = lambda *row_args: self._cursor_row_to_dict(columns, row_args)
            if fetch_action == FETCH_ACTION_ALL:
                rows = self._db_curs.fetchall()
            elif fetch_action == FETCH_ACTION_ONE:
                rows = self._db_curs.fetchone()
            else:
                rows = None

            if time_sql:
                t2 = datetime.now().replace(microsecond=0)
                self._log("Elapsed time: %s" % (t2 - t1), detail=VVERBOSE)
        finally:
            if fetch_action in (FETCH_ACTION_ALL, FETCH_ACTION_ONE):
                self._close_cursor()

        if profile and fetch_action in (FETCH_ACTION_ALL, FETCH_ACTION_ONE):
            try:
                profile_dict = self._instrumentation_snap(profile_dict)
                profile_list = sorted(iter(profile_dict.items()), key=lambda kv: kv[1])
                profile_list = [("DB Statistic", "Seconds")] + profile_list
                self._log(format_list_for_logging(profile_list), detail=VVERBOSE)
            except Exception as exc:
                self._log(
                    "Exception formatting profile (non-fatal): %s" % str(exc),
                    detail=VERBOSE,
                )
                self._log(traceback.format_exc(), detail=VVERBOSE)

        if trace_action and self._db_conn:
            self._db_conn.action = self._trace_action

        if fetch_action == FETCH_ACTION_CURSOR:
            return self._db_curs
        return rows

    def _execute_session_options(self, query_options, log_level):
        return_list = []
        if query_options:
            for prep_sql in self._format_query_options(query_options):
                self._log_or_not(
                    "%s SQL: %s" % (self._sql_engine_name, prep_sql),
                    log_level=log_level,
                )
                if self._db_conn and self._db_curs:
                    self._db_curs.execute(prep_sql)
                return_list.append(prep_sql)
        return return_list

    def _executemany_dml(
        self,
        sql,
        query_options=None,
        log_level=VERBOSE,
        trace_action=None,
        query_params=None,
        batch_size=None,
    ):
        assert sql
        if trace_action and self._db_conn:
            self._db_conn.action = self.v_session_safe_action(trace_action)
        run_opts = self._execute_session_options(query_options, log_level=log_level)
        self._log_or_not("%s SQL: %s" % (self._sql_engine_name, sql), log_level=log_level)
        self._open_cursor()
        assert self._db_curs is not None
        self._db_curs.prepare(sql)
        native_params = [self._to_native_query_params(_) for _ in query_params]
        batch_size = batch_size or len(query_params)
        for i, param_batch in enumerate(
            [
                native_params[_ * batch_size : (_ + 1) * batch_size]
                for _ in range(int(len(native_params) / batch_size) + 1)
            ]
        ):
            if param_batch == []:
                continue
            self._log_or_not("Binds(%s): %s rows" % (i, len(param_batch)), log_level=log_level)
            if not self._dry_run:
                self._db_curs.executemany(None, param_batch)
        self._close_cursor()
        if trace_action and self._db_conn:
            self._db_conn.action = self._trace_action
        return run_opts + [sql]

    def _fast_executemany_dml(
        self,
        sql,
        query_options=None,
        log_level=VERBOSE,
        trace_action=None,
        query_params=None,
        batch_size=None,
        param_inputsizes=None,
    ):
        raise NotImplementedError("_fast_executemany_dml() is not implemented for Oracle")

    def _format_query_options(self, query_options: dict | None = None) -> list:
        """Format options for Oracle
        query_options: key/value pairs for session settings
        """
        if not query_options:
            return []
        assert isinstance(query_options, dict)
        return [f"""ALTER SESSION SET {k}={v}""" for k, v in query_options.items()]

    def _frontend_capabilities(self):
        return offload_constants.ORACLE_FRONTEND_CAPABILITIES

    def _goe_db_component_version(self):
        logger.debug("Fetching GOE DB component version")
        return self._execute_plsql_function("offload.version", return_type=str)

    def _get_ddl(
        self,
        schema,
        object_name,
        object_type,
        as_list=False,
        terminate_sql=False,
        remap_schema=None,
    ):
        logger.debug(f"Fetching DDL for {schema}.{object_name}")
        params = {
            "owner": schema.upper(),
            "name": object_name.upper(),
            "object_type": object_type,
        }
        remap_command = ""
        if remap_schema:
            remap_command = "dbms_metadata.set_remap_param(th, 'REMAP_SCHEMA', :owner, :remap_schema);"
            params["remap_schema"] = remap_schema
        q = dedent("""\
                DECLARE
                  h   NUMBER;
                  th  NUMBER;
                BEGIN
                  h := dbms_metadata.open(:object_type);
                  dbms_metadata.set_filter(h, 'NAME', :name);
                  dbms_metadata.set_filter(h, 'SCHEMA', :owner);
                  th := dbms_metadata.add_transform(h, 'MODIFY');
                  %(remap_command)s
                  th := dbms_metadata.add_transform(h,'DDL');
                  :ddl := dbms_metadata.fetch_clob(h);
                  dbms_metadata.close(h);
                END;""") % {"remap_command": remap_command}
        self._log(
            "Fetch %s %s.%s SQL:\n%s" % (object_type.lower(), schema, object_name, q),
            detail=VVERBOSE,
        )
        self._open_cursor()
        try:
            assert self._db_curs is not None
            ddl = self._db_curs.var(cxo.DB_TYPE_CLOB)
            params["ddl"] = ddl
            self._db_curs.execute(q, params)
            ddl_val = ddl.getvalue()
            if ddl_val:
                ddl_str = ddl_val.read()
                if terminate_sql:
                    ddl_str += ";"
                if as_list:
                    return ddl_str.split("\n")
                return ddl_str
            return None
        finally:
            self._close_cursor()

    def _get_instance_compatible(self):
        """Returns the RDBMS version"""
        if not self._instance_compatible:
            self._instance_compatible = self.get_session_option("compatible")
        return self._instance_compatible

    def _get_partition_column_names(self, schema, table_name, subpartition_level=False):
        """Return a list of partition column names in the correct order."""
        logger.debug("_get_partition_column_names: %s, %s" % (schema, table_name))
        query_name = "get_subpartition_column_names" if subpartition_level else "get_partition_column_names"
        rows = self._metadata_gateway.select_tuples(query_name, {"owner": schema, "table_name": table_name})
        return [_[0] for _ in rows or []]

    def _instrumentation_snap(self, delta_dict=None):
        """Capture and return session events and CPU usage and return as a dict
        Values in dicts are in seconds
        """

        def get_cpu_s():
            logger.debug("Fetching CPU time from DB")
            cpu = self._execute_plsql_function("DBMS_UTILITY.GET_CPU_TIME", return_type=cxo.DB_TYPE_NUMBER)
            return float(cpu) / 100

        if delta_dict:
            cpu_seconds = get_cpu_s()

        logger.debug("Fetching session events from DB")
        profile_dict = {
            event_name: event_sec
            for event_name, event_sec in self._metadata_gateway.select_tuples("get_session_events") or []
        }

        if not delta_dict:
            cpu_seconds = get_cpu_s()

        profile_dict["cpu_seconds"] = cpu_seconds

        if delta_dict:
            for event_name, event_sec in profile_dict.items():
                profile_dict[event_name] = round(event_sec - delta_dict.get(event_name, 0), 2)

            for zero_key in [_ for _ in profile_dict if profile_dict[_] == 0 and _ != "cpu_seconds"]:
                del profile_dict[zero_key]

        return profile_dict

    def _is_iot(self, schema, table_name):
        rows = self._metadata_gateway.select_tuples("get_iot_type", {"owner": schema, "table_name": table_name})
        return bool(rows and rows[0][0] == "IOT")

    def _open_cursor(self) -> None:
        """Open a fresh cursor, reconnecting once when the session was sniped or the connection was lost.

        The ``ALTER SESSION SET TRACEFILE_IDENTIFIER`` execute is what surfaces a dead session; taking a cursor is
        not enough. Errors are matched by substring because python-oracledb reports padded (``ORA-02396``) and
        unpadded (``DPI-1080: connection was closed by ORA-2396``) codes: ORA-02396 idle-time sniping, ORA-03113
        end-of-file, ORA-03114 not connected, ORA-03135 lost contact. Reconnection runs after the ``except`` block,
        once, so a failed reconnect is not chained to the original error.
        """

        def setup_cursor() -> None:
            assert self._db_conn is not None
            self._db_curs = self._db_conn.cursor()
            self._db_curs.execute('ALTER SESSION SET TRACEFILE_IDENTIFIER="%s"' % FRONTEND_TRACE_ID)

        if not self._db_conn:
            self._db_curs = None
            return
        reconnect_reason = None
        try:
            setup_cursor()
        except cxo.DatabaseError as exc:
            if not any(marker in str(exc) for marker in RECONNECT_ERROR_MARKERS):
                raise
            reconnect_reason = str(exc)
        if reconnect_reason is not None:
            self._log(f"Reconnecting to Oracle due to: {reconnect_reason}", detail=VVERBOSE)
            logger.info(f"Reconnecting to Oracle due to: {reconnect_reason}")
            self._disconnect(force=True)
            self._connect()
            setup_cursor()

    def _to_native_query_params(self, query_params):
        """Using a dict for oracledb binds.
        For convenience, if it is already a dict then turning a blind eye and returning it, this allows code
        migrated here from OffloadSourceTable to remain unchanged.
        """
        if isinstance(query_params, dict):
            return query_params
        assert isinstance(query_params, list)
        if query_params:
            assert isinstance(query_params[0], QueryParameter)
        param_dict = {}
        for qp in query_params:
            param_dict[qp.param_name] = qp.param_value
        return param_dict
