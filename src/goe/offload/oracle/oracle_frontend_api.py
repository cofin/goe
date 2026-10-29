# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OracleFrontendApi: Library for logic/interaction with an Oracle frontend.
Implements abstract methods from FrontendApiInterface.
"""

import logging
import re
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any, Final, cast

import msgspec
import oracledb as cxo
from numpy import datetime64
from sqlspec.core.sqlcommenter import SQLCommenterContext

from goe.offload import offload_constants
from goe.offload.frontend_api import (
    FETCH_ACTION_ALL,
    FETCH_ACTION_CURSOR,
    FETCH_ACTION_ONE,
    FRONTEND_TRACE_MODULE,
    FrontendApiException,
    FrontendApiInterface,
    QueryParameter,
)
from goe.offload.frontend_cache import FrontendCatalogCache, get_frontend_catalog_cache
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.oracle.catalog import (
    OracleCatalogService,
    OracleSessionContext,
    OracleTableSnapshot,
)
from goe.offload.oracle.oracle_literal import OracleLiteral
from goe.offload.schema.column_spec import (
    CANONICAL_CHAR_SEMANTICS_BYTE,
    CANONICAL_CHAR_SEMANTICS_CHAR,
    CANONICAL_CHAR_SEMANTICS_UNICODE,
    ORACLE_TYPE_FLOAT,
    ORACLE_TYPE_NCHAR,
    ORACLE_TYPE_NCLOB,
    ORACLE_TYPE_NVARCHAR2,
    ORACLE_TYPE_VARCHAR2,
    ColumnDialect,
    ColumnSpec,
    match_table_column,
)
from goe.persistence.registry import OracleDatabaseRegistry, OracleRole
from goe.persistence.retry import run_with_session_retry
from goe.persistence.statements import NamedStatements
from goe.util import GOEVersion
from goe.util.string_utils import double_quote_sandwich, format_list_for_logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


MAX_DEPENDENCY_DEPTH = 100

ORACLE_VERSION_WITH_128_BYTE_IDENTIFIERS = "12.2.0"

CREATE_TABLE_ORACLE_PARTITION_SPEC = "partition_spec"

ORACLE_SPLIT_HIGH_VALUE_RE = re.compile(r"( *TO_DATE\([^)]+\)|[^,]+)+")

FRONTEND_METADATA_SQL_PATH = Path(__file__).resolve().parent / "sql" / "frontend_metadata.sql"
LEASE_IDLE_PING_SECONDS: Final = 60.0
_DDL_TABLE_RE = re.compile(
    r"(?:TABLE|INDEX|VIEW)\s+(?:IF\s+EXISTS\s+)?(?:\"?(?P<owner>[A-Za-z0-9_$#]+)\"?\.)?\"?(?P<table>[A-Za-z0-9_$#]+)\"?",
    re.IGNORECASE,
)


def switch_oracle_open_partition_token(frontend_token):
    if frontend_token and frontend_token.upper() == "MAXVALUE":
        return offload_constants.PART_OUT_OF_RANGE
    if frontend_token and frontend_token.upper() == "DEFAULT":
        return offload_constants.PART_OUT_OF_LIST
    return frontend_token


def oracle_column_from_dictionary_row(attribute_list: Sequence[Any]) -> ColumnSpec:
    """Construct an Oracle ColumnSpec from an 11-element Oracle dictionary row."""
    (
        name,
        _,
        nullable,
        data_type,
        data_precision,
        data_scale,
        data_length,
        data_default,
        hidden,
        char_used,
        char_length,
    ) = attribute_list
    if data_type == ORACLE_TYPE_FLOAT and data_precision:
        data_precision = None
    if char_used:
        if data_type in (
            ORACLE_TYPE_NCHAR,
            ORACLE_TYPE_NCLOB,
            ORACLE_TYPE_NVARCHAR2,
        ):
            char_semantics = CANONICAL_CHAR_SEMANTICS_UNICODE
        else:
            char_semantics = CANONICAL_CHAR_SEMANTICS_BYTE if char_used == "B" else CANONICAL_CHAR_SEMANTICS_CHAR
    else:
        char_semantics = None
    return ColumnSpec(
        ColumnDialect.ORACLE,
        name,
        data_type,
        data_length=data_length,
        data_precision=data_precision,
        data_scale=data_scale,
        nullable=nullable,
        data_default=data_default,
        hidden=hidden,
        char_semantics=char_semantics,
        char_length=char_length,
    )


class OracleFrontendApi(FrontendApiInterface):
    """Oracle FrontendApi implementation"""

    def __init__(
        self,
        connection_options: Any,
        frontend_type: Any,
        messages: Any,
        conn_user_override: Any = None,
        existing_connection: Any = None,
        dry_run: bool = False,
        do_not_connect: bool = False,
        trace_action: Any = None,
        registry: OracleDatabaseRegistry | None = None,
        catalog_cache: FrontendCatalogCache | None = None,
        catalog_service: OracleCatalogService | None = None,
    ) -> None:
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

        self._db_conn: Any = None
        self._db_curs: Any = None
        self._lease_role: OracleRole | None = None
        self._last_used = 0.0
        self._registry: Any = registry or (
            None if do_not_connect else OracleDatabaseRegistry.for_options(connection_options)
        )
        self._catalog_service = catalog_service or OracleCatalogService()
        self._catalog_cache = catalog_cache or (
            FrontendCatalogCache(catalog_service=self._catalog_service)
            if catalog_service is not None
            else get_frontend_catalog_cache()
        )
        self._metadata_statements = NamedStatements(FRONTEND_METADATA_SQL_PATH)
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
            "%s SQL: %s" % (self._sql_engine_name, self._metadata_statements.text("agg_validate_sample_column_names")),
            log_level=VVERBOSE,
        )
        self._log_or_not(
            "Bind values:\n%s" % "\n".join("%s = %s" % (k, v) for k, v in params.items()), log_level=VVERBOSE
        )
        rows = self._select_tuples("agg_validate_sample_column_names", params)
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
        if self._db_conn is not None and getattr(self._db_conn, "version", None):
            return self._db_conn.version
        ctx = self.get_session_context()
        return ctx.version if ctx else None

    def gen_column_object(self, column_name, **kwargs):
        return ColumnSpec(ColumnDialect.ORACLE, column_name, **kwargs)

    def generic_string_data_type(self) -> str:
        return ORACLE_TYPE_VARCHAR2

    def get_table_snapshot(
        self,
        schema: str,
        table_name: str,
        *,
        force_refresh: bool = False,
    ) -> OracleTableSnapshot | None:
        """Return the cached or freshly queried OracleTableSnapshot for (schema, table_name)."""
        return self._with_driver(
            lambda driver: self._catalog_cache.get_table_snapshot(
                self._dsn,
                schema,
                table_name,
                driver,
                force_refresh=force_refresh,
            )
        )

    def get_session_context(self, *, force_refresh: bool = False) -> OracleSessionContext | None:
        """Return the cached or freshly queried OracleSessionContext for the active DSN."""
        return self._with_driver(
            lambda driver: self._catalog_cache.get_session_context(
                self._dsn,
                driver,
                force_refresh=force_refresh,
            )
        )

    def get_columns(self, schema, table_name):
        snap = self.get_table_snapshot(schema, table_name)
        if snap is None:
            return []
        return [
            oracle_column_from_dictionary_row(
                (
                    col.name,
                    col.column_id,
                    "Y" if col.nullable else "N",
                    col.data_type,
                    col.data_precision,
                    col.data_scale,
                    col.data_length,
                    col.data_default,
                    "YES" if col.hidden else "NO",
                    col.char_used,
                    col.char_length,
                )
            )
            for col in snap.columns
            if not col.hidden
        ]

    def get_current_scn(self) -> int | None:
        """Return the current system change number for the source RDBMS."""
        ctx = self.get_session_context()
        return ctx.current_scn if ctx else None

    def get_db_unique_name(self) -> str:
        ctx = self.get_session_context()
        return cast(str, ctx.db_unique_name if ctx else None)

    def get_distinct_column_values(self, schema, table_name, column_names, partition_name=None, order_results=False):
        assert schema and table_name
        assert column_names
        if isinstance(column_names, str):
            column_names = [column_names]
        projection = ",".join([self.enclose_identifier(_) for _ in column_names])
        partition_clause = f" PARTITION ({self.enclose_identifier(partition_name)})" if partition_name else ""
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
        snap = self.get_table_snapshot(schema, table_name)
        return list(snap.primary_key_columns) if snap else []

    def get_session_option(self, option_name):
        """Using v$parameter to retrieve value for a parameter.
        Not using GV$ because we want the value for the session which is from the instance to which we
        are connected. Making this RAC aware would make it trickier to maintain an interface across all RDBMSs.
        """
        logger.debug(f"Fetching {option_name} from DB")
        lowered = str(option_name).lower()
        if lowered in {"compatible", "db_block_size", "max_string_size", "cell_offload_processing"}:
            ctx = self.get_session_context()
            if ctx is not None:
                if lowered == "compatible":
                    return ctx.compatible
                if lowered == "db_block_size":
                    return str(ctx.db_block_size)
                if lowered == "max_string_size":
                    return ctx.max_string_size
                return "TRUE" if ctx.cell_offload_processing else "FALSE"
        return self._execute_plsql_function("offload.get_init_param", return_type=str, arg_list=[option_name])

    def get_session_user(self) -> str:
        ctx = self.get_session_context()
        return cast(str, ctx.current_user if ctx else None)

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
        snap = self.get_table_snapshot(schema, table_name)
        return snap.degree if snap else None

    def get_table_row_count_from_metadata(self, schema: Any, table_name: Any) -> int | None:
        snap = self.get_table_snapshot(schema, table_name)
        return snap.stats.num_rows if snap else None

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

    def get_table_size(self, schema: Any, table_name: Any, no_caching: bool = False) -> int | None:
        """Total size (in bytes) of segments for a table.
        NB: does not currently include LOB or overflow segments
        """
        logger.debug("get_table_size: %s, %s" % (schema, table_name))
        snap = self.get_table_snapshot(schema, table_name, force_refresh=no_caching)
        return snap.stats.size_in_bytes if snap else None

    def is_iot(self, schema: Any, table_name: Any) -> bool:
        return self._is_iot(schema, table_name)

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

    def new_out_var(self, python_type: type) -> Any:
        """Return an OUT bind variable of ``python_type`` allocated on the attached connection."""
        connection = self._active_connection()
        if connection is None:
            raise FrontendApiException("No Oracle connection is available to allocate an OUT bind variable")
        return connection.cursor().var(python_type)

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

    def select_statement[S: msgspec.Struct](
        self,
        statements: NamedStatements,
        name: str,
        params: Mapping[str, Any] | None = None,
        *,
        schema_type: type[S],
        slots: Mapping[str, str] | None = None,
    ) -> list[S] | None:
        """Return rows of a named statement hydrated into ``schema_type`` on the attached connection.

        Returns None when the API is not connected. Retries once after a lost session.
        """
        if self._db_conn is None or self._registry is None:
            return None
        return run_with_session_retry(
            lambda: self._run_statement(statements, name, params, slots, schema_type), self._renew_connection
        )

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
        return bool(self._select_tuples("schema_exists", {"schema": schema}))

    def table_exists(self, schema: Any, table_name: Any) -> bool:
        return self.get_table_snapshot(str(schema), str(table_name)) is not None

    def to_frontend_literal(self, py_val: Any, data_type: Any = None) -> str:
        self._debug("Formatting %s literal: %s" % (type(py_val), repr(py_val)))
        self._debug("For data type: %s" % data_type)
        new_py_val = OracleLiteral.format_literal(py_val, data_type=data_type)
        self._debug("Final %s literal: %s" % (type(py_val), str(new_py_val)))
        return new_py_val

    def view_exists(self, schema: Any, view_name: Any) -> bool:
        return bool(self._select_tuples("view_exists", {"owner": schema, "view_name": view_name}))

    @property
    def _dsn(self) -> str:
        if self._registry is not None and getattr(self._registry, "settings", None) is not None:
            return str(self._registry.settings.dsn or "default")
        return str(
            getattr(self._connection_options, "rdbms_dsn", None)
            or getattr(self._connection_options, "ora_dsn", None)
            or "default"
        )

    def _with_driver(self, fn: Callable[[Any], Any]) -> Any:
        if self._db_conn is not None and self._registry is not None and hasattr(self._registry, "driver_for"):
            return run_with_session_retry(
                lambda: fn(self._registry.driver_for(self._active_connection(), self._lease_role or "adm")),
                self._renew_connection,
            )
        if self._registry is not None and hasattr(self._registry, "adm_session"):
            with self._registry.adm_session() as driver:
                return fn(driver)
        return None

    def _invalidate_cache_for_ddl(self, sqls: list[str]) -> None:
        matched = False
        for stmt in sqls:
            for m in _DDL_TABLE_RE.finditer(stmt):
                owner = m.group("owner")
                table = m.group("table")
                if owner and table:
                    self._catalog_cache.invalidate_table(self._dsn, owner, table)
                    matched = True
        if not matched:
            self._catalog_cache.clear()

    def _active_connection(self) -> Any:
        """Return the attached connection, pinging a lease idle for LEASE_IDLE_PING_SECONDS and renewing a lost one."""
        if self._db_conn is None:
            return None
        if self._lease_role is not None and time.monotonic() - self._last_used >= LEASE_IDLE_PING_SECONDS:
            run_with_session_retry(lambda: self._db_conn.ping(), self._renew_connection)
        self._last_used = time.monotonic()
        return self._db_conn

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

    def _connect(self) -> None:
        """Attach the borrowed, proxied, or leased connection selected by the constructor arguments."""
        assert self._registry is not None
        override = (self._conn_user_override or "").upper()
        adm_user = self._upper_or_empty(self._connection_options.ora_adm_user)
        app_user = self._upper_or_empty(self._connection_options.ora_app_user)
        if self._existing_connection:
            self._db_conn = self._existing_connection
            self._db_conn.module = FRONTEND_TRACE_MODULE
            self._db_conn.action = self._trace_action
        elif override and override not in (adm_user, app_user):
            self._db_conn = self._registry.connect_proxy(self._conn_user_override, action=self._trace_action)
        else:
            self._lease_role = "app" if override and override == app_user else "adm"
            self._db_conn = self._registry.lease(self._lease_role, action=self._trace_action)
        self._db_conn.outputtypehandler = self._connection_output_type_handler
        self._last_used = time.monotonic()

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

    def _disconnect(self, force: bool = False) -> None:
        """Release a lease, close a proxy connection, or close a borrowed connection only when forced."""
        self._debug("Disconnecting from DB")
        if self._existing_connection and not force:
            return
        if self._db_curs:
            self._close_cursor()
        connection, self._db_conn = self._db_conn, None
        lease_role, self._lease_role = self._lease_role, None
        if connection is not None:
            try:
                if lease_role is not None and self._registry is not None:
                    connection.outputtypehandler = None
                    self._registry.release(lease_role, connection)
                else:
                    connection.close()
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
        for run_sql in sqls:
            self._log_or_not("%s SQL: %s" % (self._sql_engine_name, run_sql), log_level=log_level)
            run_sqls.append(run_sql)
            if not self._dry_run:
                if self._db_curs is not None:
                    if query_params:
                        self._log_or_not("Bind values:", log_level=log_level)
                        self._log_or_not(
                            "\n".join(
                                "%s = %s" % (k, v) for k, v in self._to_native_query_params(query_params).items()
                            ),
                            log_level=log_level,
                        )
                        self._db_curs.execute(run_sql, self._to_native_query_params(query_params))
                    else:
                        self._db_curs.execute(run_sql)
                else:
                    params = self._to_native_query_params(query_params) if query_params else None

                    def _exec_ddl_stmt(driver: Any) -> Any:
                        return driver.execute(run_sql, params)

                    self._with_driver(_exec_ddl_stmt)
        self._close_cursor()
        if not self._dry_run:
            self._invalidate_cache_for_ddl(run_sqls)
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
        snap = self.get_table_snapshot(schema, table_name)
        if snap is None:
            return []
        return list(snap.subpartition_column_names if subpartition_level else snap.partition_column_names)

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
            event_name: event_sec for event_name, event_sec in self._select_tuples("get_session_events") or []
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
        snap = self.get_table_snapshot(schema, table_name)
        return bool(snap and snap.iot_type == "IOT")

    def _open_cursor(self) -> None:
        """Open a fresh cursor on the active connection, or clear the cursor when unconnected."""
        connection = self._active_connection()
        self._db_curs = connection.cursor() if connection is not None else None

    def _renew_connection(self, failure: BaseException | None = None) -> None:
        """Discard a lost lease or proxy connection and attach a fresh one."""
        self._log(f"Reconnecting to Oracle due to: {failure}", detail=VVERBOSE)
        logger.info(f"Reconnecting to Oracle due to: {failure}")
        connection, self._db_conn = self._db_conn, None
        lease_role, self._lease_role = self._lease_role, None
        if connection is not None and lease_role is not None and self._registry is not None:
            self._registry.release(lease_role, connection, discard=True)
        elif connection is not None and not self._existing_connection:
            try:
                connection.close()
            except Exception as exc:
                self._log("Exception closing connection:\n%s" % str(exc), detail=VVERBOSE)
        self._connect()

    def _run_statement(
        self,
        statements: NamedStatements,
        name: str,
        params: Mapping[str, Any] | None,
        slots: Mapping[str, str] | None,
        schema_type: type[Any] | None,
    ) -> list[Any]:
        """Execute a named statement on the active connection through a pool-shared SQLSpec driver."""
        assert self._registry is not None
        driver = self._registry.driver_for(self._active_connection(), self._lease_role or "adm")
        text = statements.text(name, slots)
        binds = dict(params or {})
        with SQLCommenterContext.scope({"module": FRONTEND_TRACE_MODULE, "action": self._trace_action}):
            if schema_type is None:
                return driver.select(text, binds) if binds else driver.select(text)
            if binds:
                return driver.select(text, binds, schema_type=schema_type)
            return driver.select(text, schema_type=schema_type)

    def _select_tuples(self, name: str, params: Mapping[str, Any] | None = None) -> list[tuple[Any, ...]] | None:
        """Return rows of a ``frontend_metadata.sql`` statement as tuples in projection order, or None unconnected."""
        if self._db_conn is None or self._registry is None:
            return None
        rows = run_with_session_retry(
            lambda: self._run_statement(self._metadata_statements, name, params, None, None), self._renew_connection
        )
        return [tuple(row.values()) for row in rows]

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
