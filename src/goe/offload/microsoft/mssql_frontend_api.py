# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""MSSQLFrontendApi: Library for logic/interaction with an MSSQL frontend."""

import logging
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

from numpy import datetime64

from goe.observability.db import build_db_observability_config
from goe.offload.frontend_api import (
    FETCH_ACTION_ALL,
    FETCH_ACTION_CURSOR,
    FETCH_ACTION_ONE,
    FRONTEND_TRACE_MODULE,
    FrontendApiInterface,
    QueryParameter,
    extract_connection_details_from_dsn,
)
from goe.offload.frontend_cache import FrontendCatalogCache, get_frontend_catalog_cache
from goe.offload.microsoft.synapse_literal import SynapseLiteral
from goe.offload.offload_constants import MSSQL_FRONTEND_CAPABILITIES
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.schema.column_spec import MSSQL_TYPE_VARCHAR, ColumnDialect, ColumnSpec
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.statements import NamedStatements
from goe.typing import FrozenBaseStruct
from goe.util.module_loader import ensure_module

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

MSSQL_MAX_TABLE_NAME_LENGTH = 128

_MSSQL_CATALOG_SQL = NamedStatements(Path(__file__).resolve().parent / "sql" / "mssql_catalog.sql")


class MssqlTableCatalogSnapshot(FrozenBaseStruct, frozen=True):
    """Cached catalog snapshot for a single SQL Server table."""

    schema_name: str
    table_name: str
    table_exists: bool
    num_rows: int | None
    partitioned: str
    size_bytes: int | None
    columns: tuple[ColumnSpec, ...]
    primary_key_columns: tuple[str, ...]
    hash_bucket_candidate: str | None


def build_mssql_config(
    server: str,
    port: int | str,
    database: str,
    username: str,
    password: str,
) -> Any:
    """Build a pooled SQLSpec MssqlPythonConfig for SQL Server connections."""
    assert server
    assert port
    assert database
    assert username
    assert password
    ensure_module("mssql_python", extra="sql_server")
    mssql_adapter = ensure_module("sqlspec.adapters.mssql_python", extra="sql_server")
    pool_params = mssql_adapter.MssqlPythonPoolParams(
        server=server,
        port=int(port),
        database=database,
        user=username,
        password=password,
        trust_server_certificate=True,
    )
    return mssql_adapter.MssqlPythonConfig(
        connection_config=pool_params,
        observability_config=build_db_observability_config(),
    )


def setup_mssql_session(
    server: str,
    port: int | str,
    database: str,
    username: str,
    password: str,
    appname: str = FRONTEND_TRACE_MODULE,
) -> Any:
    """Create and return a SQL Server connection via MssqlPythonConfig."""
    logger.debug('Connecting to DB "%s" as %s', database, username)
    config = build_mssql_config(server, port, database, username, password)
    return config.create_connection()


def mssql_column_from_dictionary_row(attribute_list: Sequence[Any]) -> ColumnSpec:
    """Construct an MSSQL ColumnSpec from a 10-element SQL Server catalog row."""
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
        char_length,
    ) = attribute_list
    return ColumnSpec(
        ColumnDialect.MSSQL,
        name,
        data_type,
        data_length=data_length,
        data_precision=data_precision,
        data_scale=data_scale,
        nullable=nullable,
        data_default=data_default,
        hidden=hidden,
        char_length=char_length,
    )


class MSSQLFrontendApi(FrontendApiInterface):
    """MSSQL FrontendApi implementation backed by MssqlPythonConfig and named catalog SQL."""

    def __init__(
        self,
        connection_options: Any,
        frontend_type: str,
        messages: Any,
        conn_user_override: str | None = None,
        existing_connection: Any = None,
        dry_run: bool = False,
        do_not_connect: bool = False,
        trace_action: str | None = None,
        catalog_cache: FrontendCatalogCache | None = None,
    ) -> None:
        """Construct MSSQLFrontendApi with optional catalog cache and deferred connection."""
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

        logger.info("MSSQLFrontendApi")
        if dry_run:
            logger.info("* Dry run *")

        self._catalog_cache = catalog_cache or get_frontend_catalog_cache()
        self._mssql_config: Any = None
        self._db_conn: Any = existing_connection
        self._db_curs: Any = None
        if not do_not_connect:
            self._connect()

        self._instance_compatible = None
        self._max_table_name_length = None

    def __del__(self) -> None:
        """Clean up connection resources on garbage collection."""
        try:
            self._disconnect()
        except Exception:
            pass

    def close(self, force: bool = False) -> None:
        self._disconnect(force=force)

    def agg_validate_sample_column_names(self, schema: str, table_name: str, num_required: int = 5) -> list[str]:
        raise NotImplementedError("MSSQL agg_validate_sample_column_names() not implemented.")

    def create_new_connection(
        self,
        user_name: str,
        user_password: str,
        trace_action_override: str | None = None,
    ) -> Any:
        self._debug(f"Making new connection with user {user_name}")
        server, port, database = extract_connection_details_from_dsn(self._connection_options.rdbms_dsn)
        return setup_mssql_session(server, port, database, user_name, user_password)

    def enclose_identifier(self, identifier: str | None) -> str | None:
        if identifier is None:
            return None
        return f"[{identifier}]"

    def enclose_query_hints(self, hint_contents: str | list[str] | None) -> str:
        if not hint_contents:
            return ""
        if isinstance(hint_contents, str):
            hint_contents = [hint_contents]
        return "OPTION({})".format(", ".join(str(_) for _ in hint_contents if _))

    def enclosure_character(self) -> str | None:
        return None

    def execute_function(
        self,
        sql_fn: str,
        return_type: Any = None,
        return_type_name: str | None = None,
        arg_list: list[Any] | None = None,
        log_level: int = VERBOSE,
        not_when_dry_running: bool = False,
        commit: bool = False,
    ) -> Any:
        raise NotImplementedError("MSSQL execute_function not implemented.")

    def format_query_parameter(self, param_name: str) -> str:
        """Return qmark placeholder expected by mssql-python."""
        return "?"

    def frontend_db_name(self) -> str:
        return self._frontend_type.upper()

    def frontend_version(self) -> Any:
        row = self.execute_query_fetch_one(_MSSQL_CATALOG_SQL["fetch_server_version"], log_level=VVERBOSE)
        return row[0] if row else None

    def gen_column_object(self, column_name: str, **kwargs: Any) -> ColumnSpec:
        return ColumnSpec(ColumnDialect.MSSQL, column_name, **kwargs)

    def generic_string_data_type(self) -> str:
        return MSSQL_TYPE_VARCHAR

    def get_table_snapshot(
        self,
        schema: str,
        table_name: str,
        *,
        force_refresh: bool = False,
    ) -> MssqlTableCatalogSnapshot:
        """Return a cached or freshly loaded MssqlTableCatalogSnapshot for (schema, table_name)."""
        dsn = getattr(self._connection_options, "rdbms_dsn", "mssql")
        if force_refresh:
            self._catalog_cache.invalidate_table(dsn, schema, table_name)
        return self._catalog_cache.get_or_load_snapshot(
            dsn,
            schema,
            table_name,
            lambda: self._load_table_snapshot(schema, table_name),
        )

    def get_columns(self, schema: str, table_name: str) -> list[ColumnSpec]:
        return list(self.get_table_snapshot(schema, table_name).columns)

    def get_current_scn(self) -> int:
        raise NotImplementedError("MSSQL get_current_scn not implemented.")

    def get_db_unique_name(self) -> str:
        return self._connection_options.rdbms_dsn.split("=")[1]

    def get_distinct_column_values(
        self,
        schema: str,
        table_name: str,
        column_names: str | list[str],
        partition_name: str | None = None,
        order_results: bool = False,
    ) -> Any:
        assert schema and table_name
        assert column_names
        if isinstance(column_names, str):
            column_names = [column_names]

        raise NotImplementedError("MSSQL get_distinct_column_values not implemented.")

    def get_object_ddl(
        self,
        schema: str,
        object_name: str,
        object_type: str,
        as_list: bool = False,
        terminate_sql: bool = False,
        remap_schema: str | None = None,
    ) -> Any:
        raise NotImplementedError("MSSQL get_object_ddl not implemented.")

    def get_command_step_codes(self) -> list[Any]:
        raise NotImplementedError("MSSQL get_command_step_codes is not implemented.")

    def get_command_executions(self) -> list[dict[str, str | Any]]:
        raise NotImplementedError("MSSQL get_command_executions is not implemented.")

    def get_command_execution(self, execution_id: ExecutionId) -> dict[str, str | Any]:
        raise NotImplementedError("MSSQL get_command_execution_status is not implemented.")

    def get_command_execution_steps(self, execution_id: ExecutionId) -> list[dict[str, str | Any]]:
        raise NotImplementedError("MSSQL get_command_execution_steps is not implemented.")

    def get_partition_column_names(self, schema: str, table_name: str, conv_fn: Any = None) -> list[str]:
        raise NotImplementedError("MSSQL get_partition_column_names not implemented.")

    def get_partition_columns(self, schema: str, table_name: str) -> list[ColumnSpec]:
        raise NotImplementedError("MSSQL get_partition_column_names not implemented.")

    def get_primary_key_column_names(self, schema: str, table_name: str) -> list[str]:
        return list(self.get_table_snapshot(schema, table_name).primary_key_columns)

    def get_session_option(self, option_name: str) -> Any:
        raise NotImplementedError("MSSQL get_session_option not implemented.")

    def get_session_user(self) -> str:
        raise NotImplementedError("MSSQL get_session_user not implemented.")

    def get_subpartition_column_names(self, schema: str, table_name: str, conv_fn: Any = None) -> list[str]:
        raise NotImplementedError("MSSQL get_subpartition_column_names not implemented.")

    def get_subpartition_columns(self, schema: str, table_name: str) -> list[ColumnSpec]:
        raise NotImplementedError("MSSQL get_subpartition_columns not implemented.")

    def get_table_row_count(
        self,
        schema: str,
        table_name: str,
        filter_clause: str | None = None,
        filter_clause_params: Any = None,
        hint_block: str | None = None,
        not_when_dry_running: bool = False,
        log_level: int = VVERBOSE,
    ) -> int:
        raise NotImplementedError("MSSQL get_table_row_count not implemented.")

    def get_table_size(self, schema: str, table_name: str) -> int | None:
        """Return table data size in bytes from sys.dm_db_partition_stats."""
        return self.get_table_snapshot(schema, table_name).size_bytes

    def is_view(self, schema: str, object_name: str) -> bool:
        return self.view_exists(schema, object_name)

    def max_datetime_scale(self) -> int:
        """Return maximum fractional second scale supported by MSSQL."""
        return 3

    def max_datetime_value(self) -> datetime64:
        return datetime64("9999-12-31")

    def max_table_name_length(self) -> int:
        return MSSQL_MAX_TABLE_NAME_LENGTH

    def min_datetime_value(self) -> datetime64:
        return datetime64("1753-01-01")

    def parallel_query_hint(self, query_parallelism: int | None) -> str:
        if query_parallelism:
            assert isinstance(query_parallelism, int)
            return f"MAXDOP {query_parallelism}"
        return ""

    def split_partition_high_value_string(self, hv_string: str) -> list[str]:
        raise NotImplementedError("MSSQL split_partition_high_value_string not implemented.")

    def schema_exists(self, schema: str) -> bool:
        row = self.execute_query_fetch_one(
            _MSSQL_CATALOG_SQL["check_schema_exists"],
            query_params=(schema,),
            log_level=VVERBOSE,
        )
        return bool(row)

    def table_exists(self, schema: str, table_name: str) -> bool:
        row = self.execute_query_fetch_one(
            _MSSQL_CATALOG_SQL["check_table_exists"],
            query_params=(schema, table_name),
            log_level=VVERBOSE,
        )
        return bool(row)

    def to_frontend_literal(self, py_val: Any, data_type: str | None = None) -> str:
        self._debug(f"Formatting {type(py_val)} literal: {py_val!r}")
        self._debug(f"For data type: {data_type}")
        new_py_val = SynapseLiteral.format_literal(py_val, data_type=data_type)
        self._debug(f"Final {type(py_val)} literal: {new_py_val}")
        return new_py_val

    def view_exists(self, schema: str, view_name: str) -> bool:
        row = self.execute_query_fetch_one(
            _MSSQL_CATALOG_SQL["check_view_exists"],
            query_params=(schema, view_name),
            log_level=VVERBOSE,
        )
        return bool(row)

    def _close_cursor(self) -> None:
        if self._db_conn and self._db_curs:
            try:
                self._db_curs.close()
                self._db_curs = None
            except Exception as exc:
                self._log(f"Exception closing cursor:\n{exc}", detail=VVERBOSE)

    def _connect(self) -> None:
        if self._existing_connection is not None:
            self._db_conn = self._existing_connection
            return
        server, port, database = extract_connection_details_from_dsn(self._connection_options.rdbms_dsn)
        user_name = self._conn_user_override or self._connection_options.rdbms_app_user
        self._mssql_config = build_mssql_config(
            server,
            port,
            database,
            user_name,
            self._connection_options.rdbms_app_pass,
        )

    def _create_table_sql_text(
        self,
        schema: Any,
        table_name: Any,
        column_list: Any,
        partition_column_names: Any,
        table_properties: Any = None,
    ) -> str:
        """Build a CREATE TABLE DDL statement for SQL Server."""
        if table_properties:
            raise NotImplementedError(f"Create table properties pending implementation: {table_properties}")

        col_projection = self._create_table_columns_clause_common(column_list)

        if partition_column_names:
            raise NotImplementedError("Create table partitioning pending implementation")

        sql = dedent(
            """\
            CREATE TABLE %(owner_table)s (
            %(col_projection)s
            )"""
        ) % {
            "owner_table": self.enclose_object_reference(schema, table_name),
            "col_projection": col_projection,
        }
        return sql

    def _disconnect(self, force: bool = False) -> None:
        if logger:
            self._debug("Disconnecting from DB")
        if not self._existing_connection or force:
            if self._db_curs:
                self._close_cursor()
            try:
                if self._db_conn:
                    self._db_conn.close()
                    self._db_conn = None
            except Exception:
                pass
            try:
                if self._mssql_config is not None and hasattr(self._mssql_config, "close_pool"):
                    self._mssql_config.close_pool()
            except Exception:
                pass

    def _execute_ddl_or_dml(
        self,
        sql: str | list[str],
        query_options: Any = None,
        log_level: int = VERBOSE,
        trace_action: str | None = None,
        query_params: Any = None,
    ) -> list[Any]:
        """Execute one or more DDL or DML statements over the pooled SQL Server session."""
        assert sql
        assert isinstance(sql, (str, list))
        run_opts: list[Any] = []
        run_sqls: list[str] = []
        sqls = [sql] if isinstance(sql, str) else sql
        native_params = self._to_native_query_params(query_params) if query_params else ()

        if self._dry_run:
            for run_sql in sqls:
                self._log_or_not(f"{self._sql_engine_name} SQL: {run_sql}", log_level=log_level)
                run_sqls.append(run_sql)
            return run_opts + run_sqls

        if self._mssql_config is not None:
            with self._session_scope() as session:
                for run_sql in sqls:
                    self._log_or_not(f"{self._sql_engine_name} SQL: {run_sql}", log_level=log_level)
                    run_sqls.append(run_sql)
                    if native_params:
                        session.execute(run_sql, native_params)
                    else:
                        session.execute(run_sql)
        else:
            self._open_cursor()
            try:
                for run_sql in sqls:
                    self._log_or_not(f"{self._sql_engine_name} SQL: {run_sql}", log_level=log_level)
                    run_sqls.append(run_sql)
                    assert self._db_curs is not None
                    if native_params:
                        self._db_curs.execute(run_sql, native_params)
                    else:
                        self._db_curs.execute(run_sql)
            finally:
                self._close_cursor()

        self._catalog_cache.clear()
        return run_opts + run_sqls

    def _execute_query_fetch_x(
        self,
        sql: str,
        fetch_action: str = FETCH_ACTION_ALL,
        query_options: Any = None,
        log_level: int | None = None,
        time_sql: bool = False,
        not_when_dry_running: bool = False,
        query_params: Any = None,
        profile: bool = False,
        trace_action: str | None = None,
        as_dict: bool = False,
    ) -> Any:
        """Run a query, fetch, and return the results via MssqlPythonConfig or an existing connection."""
        assert sql

        if self._dry_run and not_when_dry_running:
            return None

        if fetch_action == FETCH_ACTION_CURSOR:
            raise NotImplementedError("_execute_query_fetch_x() by FETCH_ACTION_CURSOR is not supported on MSSQL")

        t1 = datetime.now().replace(microsecond=0)
        self._log_or_not(f"{self._sql_engine_name} SQL: {sql}", log_level=log_level)
        native_params = self._to_native_query_params(query_params) if query_params else ()

        if self._mssql_config is not None:
            with self._session_scope() as session:
                if fetch_action == FETCH_ACTION_ALL:
                    raw_rows = session.select(sql, native_params) if native_params else session.select(sql)
                    rows: Any = [self._coerce_row(r, as_dict=as_dict) for r in raw_rows]
                elif fetch_action == FETCH_ACTION_ONE:
                    raw_row = (
                        session.select_one_or_none(sql, native_params)
                        if native_params
                        else session.select_one_or_none(sql)
                    )
                    rows = self._coerce_row(raw_row, as_dict=as_dict) if raw_row is not None else None
                else:
                    if native_params:
                        session.execute(sql, native_params)
                    else:
                        session.execute(sql)
                    rows = None
        else:
            self._open_cursor()
            try:
                assert self._db_curs is not None
                if native_params:
                    self._db_curs.execute(sql, native_params)
                else:
                    self._db_curs.execute(sql)
                if fetch_action == FETCH_ACTION_ALL:
                    rows = self._db_curs.fetchall()
                elif fetch_action == FETCH_ACTION_ONE:
                    fetched = self._db_curs.fetchall()
                    rows = fetched[0] if fetched else fetched
                else:
                    rows = None
            finally:
                self._close_cursor()

        if time_sql:
            t2 = datetime.now().replace(microsecond=0)
            self._log(f"Elapsed time: {t2 - t1}", detail=VVERBOSE)

        return rows

    def _executemany_dml(
        self,
        sql: str,
        query_options: Any = None,
        log_level: int = VERBOSE,
        trace_action: str | None = None,
        query_params: Any = None,
        batch_size: int | None = None,
    ) -> Any:
        raise NotImplementedError("_executemany_dml() is not implemented for MSSQL")

    def _fast_executemany_dml(
        self,
        sql: str,
        query_options: Any = None,
        log_level: int = VERBOSE,
        trace_action: str | None = None,
        query_params: Any = None,
        batch_size: int | None = None,
        param_inputsizes: Any = None,
    ) -> Any:
        raise NotImplementedError("_fast_executemany_dml() is not implemented for MSSQL")

    def _frontend_capabilities(self) -> dict[str, Any]:
        return MSSQL_FRONTEND_CAPABILITIES

    def _goe_db_component_version(self) -> str | None:
        return None

    def _load_table_snapshot(self, schema: str, table_name: str) -> MssqlTableCatalogSnapshot:
        """Query SQL Server catalog views in one batch to build MssqlTableCatalogSnapshot."""
        bind_pair = (schema, table_name)
        details_row = self.execute_query_fetch_one(
            _MSSQL_CATALOG_SQL["fetch_table_details"],
            query_params=bind_pair,
            log_level=VVERBOSE,
        )
        num_rows: int | None = None
        partitioned = "NO"
        if details_row:
            num_rows = int(details_row[1]) if details_row[1] is not None else None
            partitioned = str(details_row[2] or "NO")

        size_row = self.execute_query_fetch_one(
            _MSSQL_CATALOG_SQL["fetch_table_size_bytes"],
            query_params=bind_pair,
            log_level=VVERBOSE,
        )
        size_bytes = int(size_row[0]) if size_row and size_row[0] is not None else None

        col_rows = self.execute_query_fetch_all(
            _MSSQL_CATALOG_SQL["fetch_table_columns"],
            query_params=bind_pair,
            log_level=VVERBOSE,
        )
        columns = tuple(mssql_column_from_dictionary_row(row) for row in (col_rows or []))

        pk_rows = self.execute_query_fetch_all(
            _MSSQL_CATALOG_SQL["fetch_primary_key_columns"],
            query_params=bind_pair,
            log_level=VVERBOSE,
        )
        primary_key_columns = tuple(str(row[0]) for row in (pk_rows or []))

        hb_row = self.execute_query_fetch_one(
            _MSSQL_CATALOG_SQL["fetch_hash_bucket_candidate"],
            query_params=bind_pair,
            log_level=VVERBOSE,
        )
        hash_bucket_candidate = str(hb_row[0]) if hb_row and hb_row[0] is not None else None

        return MssqlTableCatalogSnapshot(
            schema_name=schema,
            table_name=table_name,
            table_exists=num_rows is not None or bool(columns),
            num_rows=num_rows,
            partitioned=partitioned,
            size_bytes=size_bytes,
            columns=columns,
            primary_key_columns=primary_key_columns,
            hash_bucket_candidate=hash_bucket_candidate,
        )

    def _open_cursor(self) -> None:
        if self._db_conn:
            self._db_curs = self._db_conn.cursor()
        else:
            self._db_curs = None

    @contextmanager
    def _session_scope(self) -> Any:
        if self._mssql_config is None:
            self._connect()
        assert self._mssql_config is not None
        with self._mssql_config.provide_session() as session:
            yield session

    @staticmethod
    def _coerce_row(row: Any, *, as_dict: bool = False) -> Any:
        if as_dict:
            if isinstance(row, dict):
                return dict(row)
            return {str(idx): val for idx, val in enumerate(row)}
        if isinstance(row, dict):
            return tuple(row.values())
        if isinstance(row, list):
            return tuple(row)
        return row

    def _to_native_query_params(self, query_params: Any) -> tuple[Any, ...]:
        """Convert a tuple or list of QueryParameter instances into a positional bind tuple."""
        if isinstance(query_params, tuple):
            return query_params
        assert isinstance(query_params, list)
        if not query_params:
            return ()
        if isinstance(query_params[0], QueryParameter):
            return tuple(qp.param_value for qp in query_params)
        return tuple(query_params)
