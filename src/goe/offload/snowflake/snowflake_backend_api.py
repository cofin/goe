# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""BackendSnowflakeApi: Library for logic/interaction with a remote Snowflake backend.
This module enforces an interface with common, high level, methods and an implementation
for each supported remote system, e.g. Impala, Hive, Google BigQuery.
"""

from __future__ import annotations

import logging
import re
import time
import traceback
from datetime import datetime
from textwrap import dedent
from typing import ClassVar

import msgspec
from numpy import datetime64

from goe.config.password_tools import PasswordTools
from goe.offload.backend_api import (
    CONNECT_DETAIL,
    CONNECT_STATUS,
    CONNECT_TEST,
    FETCH_ACTION_ALL,
    FETCH_ACTION_CURSOR,
    FETCH_ACTION_ONE,
    REPORT_ATTR_BACKEND_CLASS,
    REPORT_ATTR_BACKEND_DISPLAY_NAME,
    REPORT_ATTR_BACKEND_HOST_INFO,
    REPORT_ATTR_BACKEND_HOST_INFO_TYPE,
    REPORT_ATTR_BACKEND_TYPE,
    SORT_COLUMNS_UNLIMITED,
    BackendApiException,
    BackendApiInterface,
    UdfDetails,
    UdfParameter,
)
from goe.offload.backend_cache import BackendTableSnapshot, CachedBackendCatalog
from goe.offload.backend_capabilities import BackendCapabilities
from goe.offload.offload_constants import (
    DBTYPE_SNOWFLAKE,
    EMPTY_BACKEND_COLUMN_STATS_DICT,
    EMPTY_BACKEND_COLUMN_STATS_LIST,
    EMPTY_BACKEND_TABLE_STATS_DICT,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_PARQUET,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.schema.column_spec import (
    SNOWFLAKE_TYPE_BINARY,
    SNOWFLAKE_TYPE_DATE,
    SNOWFLAKE_TYPE_FLOAT,
    SNOWFLAKE_TYPE_INTEGER,
    SNOWFLAKE_TYPE_NUMBER,
    SNOWFLAKE_TYPE_TEXT,
    SNOWFLAKE_TYPE_TIME,
    SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
    SNOWFLAKE_TYPE_TIMESTAMP_TZ,
    ColumnDialect,
    ColumnSpec,
    valid_column_list,
)
from goe.offload.schema.type_registry import TYPE_REGISTRY, MappingTarget
from goe.offload.snowflake.snowflake_literal import SnowflakeLiteral
from goe.offload.sql_ast.dialect_engine import get_dialect_engine
from goe.util.module_loader import import_optional
from goe.util.string_utils import (
    backtick_sandwich,
    format_list_for_logging,
    unsurround,
)

snowflake = import_optional("snowflake")
snowflake_connector = import_optional("snowflake.connector")
_SNOWFLAKE_PROGRAMMING_ERROR: type[Exception] = (
    snowflake_connector.ProgrammingError if snowflake_connector is not None else Exception
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

SNOWFLAKE_CAPABILITIES: BackendCapabilities = BackendCapabilities.for_snowflake()

SNOWFLAKE_INVALID_IDENTIFIER_CHARS_RE = re.compile(r"[\"]", re.IGNORECASE)

SNOWFLAKE_CONNECTION_IDENTIFIER = "GOE"


class BackendSnowflakeApi(BackendApiInterface):
    type_mapping_target: ClassVar[MappingTarget] = MappingTarget.SNOWFLAKE

    def __init__(
        self,
        connection_options,
        backend_type,
        messages,
        dry_run=False,
        no_caching=False,
        do_not_connect=False,
    ):
        """Allow true bind variables

        An incorrect snowflake_warehouse does not cause an exception above (2020-12-01), check below with USE
        """
        super().__init__(
            connection_options,
            backend_type,
            messages,
            dry_run=dry_run,
            no_caching=no_caching,
            do_not_connect=do_not_connect,
        )
        if snowflake is None or snowflake_connector is None:
            raise ModuleNotFoundError("No module named 'snowflake.connector'")

        logger.info("BackendSnowflakeApi")
        if dry_run:
            logger.info("* Dry run *")

        self._capabilities = SNOWFLAKE_CAPABILITIES
        self._sql_engine = get_dialect_engine("snowflake")
        self.catalog = CachedBackendCatalog(case_sensitive=True, no_caching=bool(no_caching))

        self._client = None
        if not do_not_connect:
            snowflake.connector.paramstyle = "qmark"

            if connection_options.snowflake_pem_file:
                if connection_options.snowflake_pem_passphrase:
                    self._log(
                        "Establishing Snowflake connection with PEM file and passphrase",
                        detail=VVERBOSE,
                    )
                else:
                    self._log(
                        "Establishing Snowflake connection with PEM file",
                        detail=VVERBOSE,
                    )
                snowflake_pass = None
                pem_passphrase = None
                if connection_options.snowflake_pem_passphrase is not None:
                    pem_passphrase = self._decrypt_password(connection_options.snowflake_pem_passphrase)
                private_key = self._get_private_key_from_pemfile(connection_options.snowflake_pem_file, pem_passphrase)
            else:
                self._log(
                    "Establishing Snowflake connection with password authentication",
                    detail=VVERBOSE,
                )
                snowflake_pass = self._decrypt_password(connection_options.snowflake_pass)
                private_key = None

            self._client = snowflake.connector.connect(
                user=connection_options.snowflake_user,
                password=snowflake_pass,
                private_key=private_key,
                account=connection_options.snowflake_account,
                database=connection_options.snowflake_database,
                role=connection_options.snowflake_role,
                warehouse=connection_options.snowflake_warehouse,
                session_parameters=self._execute_global_session_parameters(),
                application=SNOWFLAKE_CONNECTION_IDENTIFIER,
            )
            self._use_warehouse(connection_options.snowflake_warehouse, log_level=VVERBOSE)
        self._cursor = None

        self._sql_engine_name = "Snowflake"
        self._target_version = None

    def warm_schema(self, db_name: str) -> int:
        """Warm the backend catalog for all tables and columns in ``db_name`` using 2 queries."""
        assert db_name
        if self._dry_run:
            return 0
        catalog_ident = self.enclose_identifier(self._catalog_name())
        tables_sql = dedent(
            f"""\
            SELECT table_name, table_type, bytes, row_count
            FROM   {catalog_ident}.information_schema.tables
            WHERE  table_catalog = ? AND table_schema = ?"""
        )
        cols_sql = dedent(
            f"""\
            SELECT table_name, column_name, data_type, is_nullable
            ,      character_maximum_length, character_octet_length
            ,      numeric_precision, numeric_scale, datetime_precision
            FROM   {catalog_ident}.information_schema.columns
            WHERE  table_catalog = ? AND table_schema = ?
            ORDER BY table_name, ordinal_position"""
        )
        params = [self._catalog_name(), db_name]
        table_rows = self.execute_query_fetch_all(tables_sql, log_level=VVERBOSE, query_params=params) or []
        col_rows = self.execute_query_fetch_all(cols_sql, log_level=VVERBOSE, query_params=params) or []

        cols_by_table: dict[str, list[ColumnSpec]] = {}
        for col in col_rows:
            (
                tbl_name,
                col_name,
                data_type,
                is_nullable,
                char_length,
                byte_length,
                num_precision,
                num_scale,
                time_scale,
            ) = col
            data_scale = time_scale if time_scale is not None else num_scale
            cols_by_table.setdefault(tbl_name, []).append(
                ColumnSpec(
                    ColumnDialect.SNOWFLAKE,
                    col_name,
                    data_type,
                    data_length=byte_length,
                    char_length=char_length,
                    data_precision=num_precision,
                    data_scale=data_scale,
                    nullable=is_nullable,
                )
            )

        snapshots: dict[str, BackendTableSnapshot] = {}
        now = time.monotonic()
        for tbl_row in table_rows:
            tbl_name, tbl_type, size_bytes, row_count = tbl_row
            is_view = bool(str(tbl_type).upper() == "VIEW")
            snapshots[tbl_name] = BackendTableSnapshot(
                db_name=db_name,
                table_name=tbl_name,
                exists=not is_view,
                fetched_at=now,
                is_view=is_view,
                columns=tuple(cols_by_table.get(tbl_name, ())),
                size_bytes=int(size_bytes) if size_bytes is not None else None,
                size_calculated=True,
                row_count=int(row_count) if row_count is not None else None,
                row_count_calculated=True,
            )
        return self.catalog.warm_schema(db_name, snapshots.values())

    def add_columns(self, db_name, table_name, column_tuples, sync=None):
        """See interface spec for description"""
        assert db_name and table_name
        assert column_tuples
        assert isinstance(column_tuples, list), "%s is not list" % type(column_tuples)
        assert isinstance(column_tuples[0], (tuple, list))

        ddls = []
        for col_name, col_type in column_tuples:
            sql = "ALTER TABLE %s.%s ADD COLUMN %s %s" % (
                self.enclose_identifier(db_name),
                self.enclose_identifier(table_name),
                self.enclose_identifier(col_name),
                col_type,
            )
            ddls += self.execute_ddl(sql)
        self.catalog.on_alter_table(db_name, table_name)
        return ddls

    def alter_sort_columns(self, db_name, table_name, sort_column_names, sync=None):
        assert db_name and table_name
        assert isinstance(sort_column_names, list)
        if sort_column_names:
            sort_csv = ",".join([self.enclose_identifier(_) for _ in sort_column_names])
            sql = "ALTER TABLE %s CLUSTER BY (%s)" % (
                self.enclose_object_reference(db_name, table_name),
                sort_csv,
            )
        else:
            sql = "ALTER TABLE %s DROP CLUSTERING KEY" % self.enclose_object_reference(db_name, table_name)
        result = self.execute_ddl(sql, log_level=VERBOSE)
        self.catalog.on_alter_table(db_name, table_name)
        return result

    def backend_report_info(self):
        """Reporting information about the type of backend and how to display
        its configuration details (e.g. Hadoop host:port or BigQuery project).
        """
        return {
            REPORT_ATTR_BACKEND_CLASS: "Cloud Warehouse",
            REPORT_ATTR_BACKEND_TYPE: self._backend_type,
            REPORT_ATTR_BACKEND_DISPLAY_NAME: self.backend_db_name(),
            REPORT_ATTR_BACKEND_HOST_INFO_TYPE: "Snowflake Database",
            REPORT_ATTR_BACKEND_HOST_INFO: self._catalog_name(),
        }

    def backend_version(self):
        """Output some descriptive information about the backend
        This is different to target_version() even though it appears similar in function.
        """
        return self.target_version()

    def check_backend_supporting_objects(self, orchestration_options):
        results = []

        try:
            user = self.get_user_name()
            results.append(
                {
                    CONNECT_TEST: "Test backend user",
                    CONNECT_STATUS: True,
                    CONNECT_DETAIL: "Backend User: %s" % user,
                }
            )
        except Exception:
            self._log(traceback.format_exc(), detail=VVERBOSE)
            results.append(
                {
                    CONNECT_TEST: "Test backend user",
                    CONNECT_STATUS: False,
                    CONNECT_DETAIL: "Unable to obtain backend user",
                }
            )

        if self.role_exists(orchestration_options.snowflake_role):
            if self._role_granted_to_user(
                orchestration_options.snowflake_role,
                orchestration_options.snowflake_user,
            ):
                results.append(
                    {
                        CONNECT_TEST: "Role",
                        CONNECT_STATUS: True,
                        CONNECT_DETAIL: "Role exists and is granted: %s" % orchestration_options.snowflake_role,
                    }
                )
            else:
                results.append(
                    {
                        CONNECT_TEST: "Role",
                        CONNECT_STATUS: False,
                        CONNECT_DETAIL: "Role is not granted to user: %s" % orchestration_options.snowflake_role,
                    }
                )
        else:
            results.append(
                {
                    CONNECT_TEST: "Role",
                    CONNECT_STATUS: False,
                    CONNECT_DETAIL: "Role does not exist: %s" % orchestration_options.snowflake_role,
                }
            )

        if self._warehouse_exists(orchestration_options.snowflake_warehouse):
            results.append(
                {
                    CONNECT_TEST: "Warehouse",
                    CONNECT_STATUS: True,
                    CONNECT_DETAIL: "Warehouse exists: %s" % orchestration_options.snowflake_warehouse,
                }
            )
        else:
            results.append(
                {
                    CONNECT_TEST: "Warehouse",
                    CONNECT_STATUS: False,
                    CONNECT_DETAIL: "Warehouse does not exist: %s" % orchestration_options.snowflake_warehouse,
                }
            )

        if self.snowflake_integration_exists(orchestration_options.snowflake_integration):
            results.append(
                {
                    CONNECT_TEST: "Storage integration",
                    CONNECT_STATUS: True,
                    CONNECT_DETAIL: "Integration exists: %s" % orchestration_options.snowflake_integration,
                }
            )
        else:
            results.append(
                {
                    CONNECT_TEST: "Storage integration",
                    CONNECT_STATUS: False,
                    CONNECT_DETAIL: "Integration does not exist: %s" % orchestration_options.snowflake_integration,
                }
            )

        return results

    def close(self):
        if self._client:
            self._client.close()

    def compute_stats(
        self,
        db_name,
        table_name,
        incremental=None,
        for_columns=False,
        partition_tuples=None,
        sync=None,
    ):
        """No manual controls of stats on Snowflake"""
        raise NotImplementedError("Compute statistics does not apply for Snowflake")

    def create_database(self, db_name, comment=None, properties=None, with_terminator=False):
        """Create a Snowflake schema which is a database in GOE terminology.
        properties["transient"]: Can be used to create a transient schema if value is truthy.
        """
        assert db_name
        if properties:
            assert isinstance(properties, dict)
        if comment:
            assert isinstance(comment, str)

        if properties and properties.get("transient"):
            transient_clause = " TRANSIENT"
            retention_clause = " DATA_RETENTION_TIME_IN_DAYS = 0"
        else:
            transient_clause = retention_clause = ""

        if comment:
            comment_clause = " COMMENT = '%s'" % comment
        else:
            comment_clause = ""

        sql = "CREATE%s SCHEMA IF NOT EXISTS %s%s%s" % (
            transient_clause,
            self.enclose_identifier(db_name),
            retention_clause,
            comment_clause,
        )
        if with_terminator:
            sql += ";"
        return self.execute_ddl(sql)

    def create_table(
        self,
        db_name,
        table_name,
        column_list,
        partition_column_names,
        storage_format=None,
        location=None,
        external=False,
        table_properties=None,
        sort_column_names=None,
        without_db_name=False,
        sync=None,
        with_terminator=False,
    ):
        """Create a Snowflake table
        partition_column_names: Not supported on Snowflake
        location: Ignored for Snowflake
        table_properties: Ignored for Snowflake
        without_db_name: Ignored for Snowflake
        See abstract method for more description
        """
        assert db_name
        assert table_name
        assert column_list
        assert valid_column_list(column_list), "Incorrectly formed column_list: %s" % column_list
        if table_properties:
            assert isinstance(table_properties, dict)
        if sort_column_names:
            assert isinstance(sort_column_names, list)

        if partition_column_names:
            raise NotImplementedError("Partitioning by column is not supported in Snowflake")
        if external:
            raise NotImplementedError("Offload by external table is not supported on Snowflake")

        col_projection = self._create_table_columns_clause_common(column_list, external=external)

        if sort_column_names:
            sort_csv = ",".join([self.enclose_identifier(_) for _ in sort_column_names])
            sort_by_clause = "\nCLUSTER BY (%s)" % sort_csv
        else:
            sort_by_clause = ""

        sql = dedent(
            """\
        CREATE TABLE %(db_table)s (
        %(col_projection)s
        )%(sort_by_clause)s"""
        ) % {
            "db_table": self.enclose_object_reference(db_name, table_name),
            "col_projection": col_projection,
            "sort_by_clause": sort_by_clause,
        }
        if with_terminator:
            sql += ";"
        result = self.execute_ddl(sql, sync=sync)
        self.catalog.on_create_table(db_name, table_name, column_list)
        return result

    def create_view(
        self,
        db_name,
        view_name,
        column_tuples,
        ansi_joined_tables,
        filter_clauses=None,
        sync=None,
    ):
        """Create a Snowflake view
        See create_view() description on interface for parameter descriptions.
        """
        projection = self._format_select_projection(column_tuples)
        where_clause = "\nWHERE  " + "\nAND    ".join(filter_clauses) if filter_clauses else ""
        sql = dedent(
            """\
        CREATE VIEW %(db_view)s AS
        SELECT %(projection)s
        FROM   %(from_tables)s%(where_clause)s"""
        ) % {
            "db_view": self.enclose_object_reference(db_name, view_name),
            "projection": projection,
            "from_tables": ansi_joined_tables,
            "where_clause": where_clause,
        }
        return self.execute_ddl(sql, sync=sync)

    def create_udf(
        self,
        db_name,
        udf_name,
        return_data_type,
        parameter_tuples,
        udf_body,
        or_replace=False,
        spec_as_string=None,
        sync=None,
        log_level=VERBOSE,
    ):
        """Pending implementation due to no current requirement for Snowflake UDF Support in GOE"""
        raise NotImplementedError("create_udf() is not implemented for Snowflake backend")

    def current_date_sql_expression(self):
        return "CURRENT_DATE()"

    def data_type_accepts_length(self, data_type):
        return bool(data_type in [SNOWFLAKE_TYPE_NUMBER, SNOWFLAKE_TYPE_TEXT, SNOWFLAKE_TYPE_BINARY])

    def database_exists(self, db_name):
        return bool(self.list_databases(db_name_filter=db_name))

    def db_name_label(self, initcap=False):
        label = "schema"
        return label.capitalize() if initcap else label

    def default_date_based_partition_granularity(self):
        return None

    def default_storage_compression(self, user_requested_codec, user_requested_format):
        if user_requested_codec in ["HIGH", "MED", "NONE", None]:
            return None
        return user_requested_codec

    @staticmethod
    def default_storage_format():
        return None

    def derive_native_partition_info(self, db_name, table_name, column, position):
        return None

    def detect_column_has_fractional_seconds(self, db_name, table_name, column):
        assert db_name and table_name
        assert isinstance(column, ColumnSpec) and column.dialect is ColumnDialect.SNOWFLAKE
        if column.data_type not in [
            SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
            SNOWFLAKE_TYPE_TIMESTAMP_TZ,
        ]:
            return False
        sql = dedent(
            """\
        SELECT %(col)s
        FROM %(db_table)s
        WHERE EXTRACT(NANOSECOND FROM %(col)s) != 0
        LIMIT 1"""
        ) % {
            "db_table": self.enclose_object_reference(db_name, table_name),
            "col": self.enclose_identifier(column.name),
        }
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return True if row else False

    def drop_state(self):
        self.catalog.clear()

    def drop_table(self, db_name, table_name, purge=False, if_exists=True, sync=None):
        """Drop a table, purge parameter is ignored on Snowflake.
        See abstract method for more description
        """
        assert db_name and table_name
        if_exists_clause = "IF EXISTS " if if_exists else ""
        drop_sql = "DROP TABLE %s%s" % (
            if_exists_clause,
            self.enclose_object_reference(db_name, table_name),
        )
        result = self.execute_ddl(drop_sql, sync=sync)
        self.catalog.on_drop_table(db_name, table_name)
        return result

    def drop_view(self, db_name, view_name, if_exists=True, sync=None):
        """Drop a view, purge parameter is ignored on Snowflake.
        See abstract method for more description
        """
        assert db_name and view_name
        if_exists_clause = "IF EXISTS " if if_exists else ""
        drop_sql = "DROP VIEW %s%s" % (
            if_exists_clause,
            self.enclose_object_reference(db_name, view_name),
        )
        result = self.execute_ddl(drop_sql, sync=sync)
        self.catalog.on_drop_table(db_name, view_name)
        return result

    def enclose_identifier(self, identifier):
        if identifier is None:
            return None
        return backtick_sandwich(identifier, ch=self.enclosure_character())

    def enclose_object_reference(self, db_name, object_name):
        """This only happens during unit tests"""
        assert db_name and object_name
        snowflake_db = self._catalog_name()
        if snowflake_db is None:
            return ".".join([self.enclose_identifier(db_name), self.enclose_identifier(object_name)])
        return ".".join(
            [
                self.enclose_identifier(snowflake_db),
                self.enclose_identifier(db_name),
                self.enclose_identifier(object_name),
            ]
        )

    def enclosure_character(self):
        return '"'

    def execute_query_fetch_all(
        self,
        sql,
        query_options=None,
        log_level=None,
        time_sql=False,
        not_when_dry_running=False,
        query_params=None,
        profile=None,
        as_dict=False,
    ):
        """For parameter descriptions see: _execute_query_fetch_x"""
        return self._execute_query_fetch_x(
            sql,
            fetch_action=FETCH_ACTION_ALL,
            query_options=query_options,
            log_level=log_level,
            time_sql=time_sql,
            profile=profile,
            not_when_dry_running=not_when_dry_running,
            query_params=query_params,
            as_dict=as_dict,
        )

    def execute_query_fetch_one(
        self,
        sql,
        query_options=None,
        log_level=None,
        time_sql=False,
        not_when_dry_running=False,
        query_params=None,
        profile=None,
        as_dict=False,
    ):
        """For parameter descriptions see: _execute_query_fetch_x"""
        return self._execute_query_fetch_x(
            sql,
            fetch_action=FETCH_ACTION_ONE,
            query_options=query_options,
            log_level=log_level,
            time_sql=time_sql,
            profile=profile,
            not_when_dry_running=not_when_dry_running,
            query_params=query_params,
            as_dict=as_dict,
        )

    def execute_query_get_cursor(
        self,
        sql,
        query_options=None,
        log_level=None,
        time_sql=False,
        not_when_dry_running=False,
        query_params=None,
    ):
        """Run a query and return the cursor to allow the calling program to handle fetching"""
        return self._execute_query_fetch_x(
            sql,
            fetch_action=FETCH_ACTION_CURSOR,
            query_options=query_options,
            log_level=log_level,
            time_sql=time_sql,
            not_when_dry_running=not_when_dry_running,
            query_params=query_params,
        )

    def exists(self, db_name, object_name):
        return bool(self.table_exists(db_name, object_name) or self.view_exists(db_name, object_name))

    def format_query_parameter(self, param_name):
        return "?"

    def gen_column_object(self, column_name, **kwargs):
        return ColumnSpec(ColumnDialect.SNOWFLAKE, column_name, **kwargs)

    def gen_copy_into_sql_text(
        self,
        db_name,
        table_name,
        from_object_clause,
        select_expr_tuples,
        filter_clauses=None,
    ):
        """Format COPY INTO from SELECT statement for Snowflake"""
        self._gen_insert_select_sql_assertions(
            db_name,
            table_name,
            None,
            None,
            select_expr_tuples,
            None,
            filter_clauses,
            from_object_clause,
        )
        projection = self._format_select_projection(select_expr_tuples)
        where_clause = ""
        if filter_clauses:
            where_clause = "\nWHERE  " + "\nAND    ".join(filter_clauses)

        insert_sql = dedent(
            """\
        COPY INTO %(db_table)s
        FROM
        (
        SELECT %(proj)s
        FROM   %(from_object_clause)s%(where)s
        )
        """
        ) % {
            "db_table": self.enclose_object_reference(db_name, table_name),
            "proj": projection,
            "from_object_clause": from_object_clause,
            "where": where_clause,
        }
        return insert_sql

    def gen_ctas_sql_text(
        self,
        db_name,
        table_name,
        storage_format,
        column_tuples,
        from_db_name=None,
        from_table_name=None,
        row_limit=None,
        external=False,
        table_properties=None,
    ):
        """See interface description for parameter descriptions.
        Ignoring storage_format on Snowflake.
        """
        assert db_name and table_name
        assert column_tuples
        assert isinstance(column_tuples, list), "%s is not list" % type(column_tuples)
        assert isinstance(column_tuples[0], (tuple, list))
        projection = self._format_select_projection(column_tuples)
        from_clause = (
            f"\nFROM   {self.enclose_object_reference(from_db_name, from_table_name)}"
            if from_db_name and from_table_name
            else ""
        )
        limit_clause = f"\nLIMIT  {row_limit}" if row_limit is not None else ""
        sql = dedent(
            """\
            CREATE TABLE %(db_table)s
            AS
            SELECT %(projection)s%(from_clause)s%(limit_clause)s"""
        ) % {
            "db_table": self.enclose_object_reference(db_name, table_name),
            "projection": projection,
            "from_clause": from_clause,
            "limit_clause": limit_clause,
        }
        return sql

    def gen_default_numeric_column(self, column_name, data_scale=18):
        """Return a default best-fit numeric column for generic usage."""
        return TYPE_REGISTRY.default_numeric_column(
            column_name,
            self.type_mapping_target,
            self.type_mapping_context(),
            data_scale=data_scale,
        )

    def gen_insert_select_sql_text(
        self,
        db_name,
        table_name,
        from_db_name,
        from_table_name,
        select_expr_tuples,
        partition_expr_tuples=None,
        filter_clauses=None,
        sort_expr_list=None,
        distribute_columns=None,
        insert_hint=None,
        from_object_override=None,
    ):
        """Format INSERT from SELECT statement for Snowflake
        Ignores insert_hint, sort_expr_list and distribute_columns
        See abstractmethod spec for parameter descriptions
        """
        self._gen_insert_select_sql_assertions(
            db_name,
            table_name,
            from_db_name,
            from_table_name,
            select_expr_tuples,
            partition_expr_tuples,
            filter_clauses,
            from_object_override,
        )

        projection = self._format_select_projection(select_expr_tuples)
        from_db_table = from_object_override or self.enclose_object_reference(from_db_name, from_table_name)

        where_clause = ""
        if filter_clauses:
            where_clause = "\nWHERE  " + "\nAND    ".join(filter_clauses)

        insert_sql = dedent(
            """\
        INSERT INTO %(db_table)s
        SELECT %(proj)s
        FROM   %(from_db_table)s%(where)s"""
        ) % {
            "db_table": self.enclose_object_reference(db_name, table_name),
            "proj": projection,
            "from_db_table": from_db_table,
            "where": where_clause,
        }
        return insert_sql

    def gen_native_range_partition_key_cast(self, partition_column):
        """No native range partitioning on Snowflake"""
        raise NotImplementedError("Native range partitioning unsupported on Snowflake")

    def gen_sql_text(
        self,
        db_name,
        table_name,
        column_names=None,
        filter_clauses=None,
        measures=None,
        agg_fns=None,
    ):
        return self._gen_sql_text_common(
            db_name,
            table_name,
            column_names=column_names,
            filter_clauses=filter_clauses,
            measures=measures,
            agg_fns=agg_fns,
        )

    def generic_string_data_type(self):
        return SNOWFLAKE_TYPE_TEXT

    def get_columns(self, db_name, table_name):
        """Return cached or freshly queried column metadata for a Snowflake table."""
        assert db_name and table_name
        return self.catalog.get_columns(db_name, table_name, self._fetch_columns)

    def get_distinct_column_values(
        self,
        db_name,
        table_name,
        column_name_list,
        columns_to_cast_to_string=None,
        order_results=False,
        not_when_dry_running=False,
    ):
        """Run SQL to get distinct values for a list of columns.
        See interface description for parameter details.
        """
        assert column_name_list and isinstance(column_name_list, list)
        cast_cols = set(columns_to_cast_to_string or [])
        expression_list = [
            f"CAST({self.enclose_identifier(_)} as TEXT)"
            if self.enclose_identifier(_) in cast_cols
            else self.enclose_identifier(_)
            for _ in column_name_list
        ]
        return self.get_distinct_expressions(
            db_name,
            table_name,
            expression_list,
            order_results=order_results,
            not_when_dry_running=not_when_dry_running,
        )

    def get_max_column_values(
        self,
        db_name,
        table_name,
        column_name_list,
        columns_to_cast_to_string=None,
        optimistic_prune_clause=None,
        not_when_dry_running=False,
    ):
        """Run SQL to get max value for a set of columns.
        See interface description for parameter details.
        """
        return self._get_max_column_values_common(
            db_name,
            table_name,
            column_name_list,
            columns_to_cast_to_string=columns_to_cast_to_string,
            optimistic_prune_clause=optimistic_prune_clause,
            not_when_dry_running=not_when_dry_running,
        )

    def get_partition_columns(self, db_name, table_name):
        """Table partitioning is not supported on Snowflake"""
        return []

    def get_query_plan(self, query_id):
        assert query_id
        sql = dedent(
            """\
             SELECT SYSTEM$EXPLAIN_JSON_TO_TEXT(
                SYSTEM$EXPLAIN_PLAN_JSON('%s')
             )
             """
            % query_id
        )
        try:
            rows = self.execute_query_fetch_all(sql, log_level=VVERBOSE, query_params=[query_id])
            if not rows:
                raise BackendApiException("Query plan not found for query id: %s" % query_id)
            return "\n".join([row[0] for row in rows])
        except _SNOWFLAKE_PROGRAMMING_ERROR:
            raise BackendApiException("Query plan not found for query id: %s" % query_id)
        finally:
            if self._cursor:
                self._close_cursor()

    def get_session_query_profile(self, session_id, query_id):
        assert session_id and query_id
        sql = dedent(
            """\
             SELECT *
             FROM TABLE(
                %s.information_schema.query_history_by_session(end_time_range_end => CURRENT_TIMESTAMP,
                                                               session_id => %s,
                                                               result_limit => 100)
             )
             WHERE query_id = ?"""
            % (self.enclose_identifier(self._catalog_name()), session_id)
        )
        try:
            self.execute_query_get_cursor(sql, log_level=VVERBOSE, query_params=[query_id])
            assert self._cursor is not None
            row = self._cursor.fetchone()
            if not row:
                raise BackendApiException(
                    "Query plan not found for session id: %s, query id: %s" % (session_id, query_id)
                )
            profile_keys = [_[0] for _ in self._cursor.description]
            stats = sorted(zip(profile_keys, list(row)))
            longest_key = max(len(_) for _ in profile_keys)
            formatted_stats = ["{k: <{pad}}: {v}".format(k=k, v=v, pad=longest_key) for k, v in stats]
            return "\n".join(formatted_stats)
        except _SNOWFLAKE_PROGRAMMING_ERROR:
            raise BackendApiException("Query plan not found for session id: %s, query id: %s" % (session_id, query_id))
        finally:
            if self._cursor:
                self._close_cursor()

    def get_session_option(self, option_name):
        """LIKE is case insensitive

        Second field in SHOW PARAMETERS is value
        """
        if not option_name:
            return None
        sql = "SHOW PARAMETERS LIKE '%s'" % option_name
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return row[1] if row else None

    def get_table_ddl(self, db_name, table_name, as_list=False, terminate_sql=False, for_replace=False):
        return self._get_snowflake_ddl(
            db_name,
            table_name,
            "TABLE",
            as_list=as_list,
            terminate_sql=terminate_sql,
            for_replace=for_replace,
        )

    def get_table_location(self, db_name, table_name):
        """There is no load table on Snowflake"""
        return

    def get_table_partition_count(self, db_name, table_name):
        """Table partitioning is not supported on Snowflake"""
        return 0

    def get_table_partitions(self, db_name, table_name):
        """Table partitioning is not supported on Snowflake"""
        return []

    def get_table_row_count(
        self,
        db_name,
        table_name,
        filter_clause=None,
        not_when_dry_running=False,
        log_level=VVERBOSE,
    ):
        sql = self._gen_select_count_sql_text_common(db_name, table_name, filter_clause=filter_clause)
        row = self.execute_query_fetch_one(
            sql,
            log_level=log_level,
            time_sql=True,
            not_when_dry_running=not_when_dry_running,
        )
        return row[0] if row else None

    def get_table_row_count_from_metadata(self, db_name, table_name):
        _, row_count = self.get_table_size_and_row_count(db_name, table_name)
        return row_count

    def get_table_size(self, db_name, table_name, no_cache=False):
        """Return the size in bytes of the Snowflake table."""
        assert db_name and table_name
        if no_cache:
            size_bytes, _ = self._fetch_table_size_and_row_count(db_name, table_name)
            return size_bytes
        size_bytes, _ = self.get_table_size_and_row_count(db_name, table_name)
        return size_bytes

    def get_table_size_and_row_count(self, db_name, table_name):
        """Return (size_bytes, row_count) using the cached backend catalog."""
        assert db_name and table_name
        snap = self.catalog.get_snapshot(db_name, table_name)
        if snap is not None and snap.size_calculated and snap.row_count_calculated:
            return snap.size_bytes, snap.row_count
        size_bytes, row_count = self._fetch_table_size_and_row_count(db_name, table_name)
        now = time.monotonic()
        updated = (
            snap.replace(
                size_bytes=size_bytes,
                size_calculated=True,
                row_count=row_count,
                row_count_calculated=True,
                fetched_at=now,
            )
            if snap is not None
            else BackendTableSnapshot(
                db_name=db_name,
                table_name=table_name,
                exists=size_bytes is not None or row_count is not None,
                size_bytes=size_bytes,
                size_calculated=True,
                row_count=row_count,
                row_count_calculated=True,
                fetched_at=now,
            )
        )
        self.catalog.put_snapshot(updated)
        return size_bytes, row_count

    def get_table_sort_columns(self, db_name, table_name, as_csv=True):
        """Extract cluster key columns from information_schema.
        The regexp_replace was taken from Snowflake documentation:
            https://community.snowflake.com/s/article/LINEAR-keyword-missing-in-clustering-key-column-in-information-schema-table-table
        In Snowflake, cluster keys can be expressions, Offload does not support that therefore we
        filter the results by real table columns.

        Snowflake information_schema queries are faster if database is in FROM clause than when via column predicate
        Drive by cluster key to maintain column order
        """
        assert db_name and table_name
        sql = r"""SELECT REGEXP_REPLACE(clustering_key, '(LINEAR)?\\((.*)\\)','\\2')
                  FROM   %s.information_schema.tables
                  WHERE  table_catalog = ? AND table_schema = ? AND table_name = ?""" % self.enclose_identifier(
            self._catalog_name()
        )
        row = self.execute_query_fetch_one(
            sql,
            log_level=VVERBOSE,
            query_params=[self._catalog_name(), db_name, table_name],
        )
        if not row or not row[0]:
            return []
        cluster_key_expressions = [unsurround(_.upper().strip(), self.enclosure_character()) for _ in row[0].split(",")]
        column_names = set(self.get_column_names(db_name, table_name, conv_fn=lambda x: x.upper()))
        cluster_columns = [_ for _ in cluster_key_expressions if _ in column_names]
        return ",".join(cluster_columns) if as_csv else cluster_columns

    def get_table_stats(self, db_name, table_name, as_dict=False):
        assert db_name and table_name

        if self.table_exists(db_name, table_name):
            num_bytes, num_rows = self.get_table_size_and_row_count(db_name, table_name)
            tab_stats = {"num_rows": num_rows, "num_bytes": num_bytes, "avg_row_len": 0}
        else:
            tab_stats = EMPTY_BACKEND_TABLE_STATS_DICT

        if as_dict:
            return tab_stats, EMPTY_BACKEND_COLUMN_STATS_DICT
        stats_tuple = (
            tab_stats["num_rows"],
            tab_stats["num_bytes"],
            tab_stats["avg_row_len"],
        )
        return stats_tuple, EMPTY_BACKEND_COLUMN_STATS_LIST

    def get_table_and_partition_stats(self, db_name, table_name, as_dict=False):
        tab_stats, _ = self.get_table_stats(db_name, table_name, as_dict=as_dict)
        if as_dict:
            return tab_stats, {}, EMPTY_BACKEND_COLUMN_STATS_DICT
        return tab_stats, [], EMPTY_BACKEND_COLUMN_STATS_LIST

    def get_table_stats_partitions(self, db_name, table_name):
        raise NotImplementedError("Get statistics does not apply for Snowflake")

    def get_user_name(self):
        sql = "SELECT current_user()"
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return row[0] if row else None

    def set_session_db(self, db_name, log_level=VERBOSE):
        assert db_name
        return self.execute_ddl("USE SCHEMA %s" % db_name, log_level=log_level)

    def snowflake_file_format_exists(self, db_name, file_format_name, format_type=None):
        """Check a Snowflake File Format exists. This is Snowflake only, hence snowflake in the method name.
        format_type can optionally be passed in to verify any existing file_format is for the correct file type.
        It is public so that BackendSnowflakeTable can call it.

        We've additionally asked for a check that the file_format_type matches a specific value
        """
        assert self._backend_type == DBTYPE_SNOWFLAKE
        sql = dedent(
            """\
            SELECT file_format_type
            FROM   %s.information_schema.file_formats
            WHERE  file_format_catalog = ? AND file_format_schema = ? AND file_format_name = ?"""
            % self.enclose_identifier(self._catalog_name())
        )
        row = self.execute_query_fetch_one(
            sql,
            log_level=VVERBOSE,
            query_params=[self._catalog_name(), db_name, file_format_name],
        )
        if row and format_type:
            if format_type.upper() != row[0].upper():
                raise BackendApiException(
                    "File format %s has file type mismatch: %s != %s"
                    % (
                        self.enclose_object_reference(db_name, file_format_name),
                        format_type.upper(),
                        row[0].upper(),
                    )
                )
        return bool(row)

    def snowflake_integration_exists(self, integration_name):
        """Check a Snowflake Integration exists. This is Snowflake only, hence snowflake in the method name.
        It is public so that BackendTable can call it.
        """
        assert self._backend_type == DBTYPE_SNOWFLAKE
        sql = "SHOW STORAGE INTEGRATIONS LIKE '%s'" % integration_name
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return bool(row)

    def snowflake_stage_exists(self, db_name, stage_name, url_prefix=None):
        """Check a Snowflake Stage exists. This is Snowflake only, hence snowflake in the method name.
        It is public so that BackendTable can call it.

        We've additionally asked for a check that the stage_url matches a specific value
        """
        assert self._backend_type == DBTYPE_SNOWFLAKE
        sql = dedent(
            """\
            SELECT stage_url
            FROM   %s.information_schema.stages
            WHERE  stage_catalog = ? AND stage_schema = ? AND stage_name = ?"""
            % self.enclose_identifier(self._catalog_name())
        )
        query_params = [self._catalog_name(), db_name, stage_name]
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE, query_params=query_params)
        if row and url_prefix:
            if not row[0].lower().startswith(url_prefix.lower()):
                raise BackendApiException(
                    "Snowflake stage %s has URL mismatch: %s does not start with %s"
                    % (
                        self.enclose_object_reference(db_name, stage_name),
                        row[0].lower(),
                        url_prefix.lower(),
                    )
                )
        return bool(row)

    def is_nan_sql_expression(self, column_expr):
        return "%s = 'NaN'" % column_expr

    def is_valid_partitioning_data_type(self, data_type):
        """On Snowflake there are no partition columns therefore this always returns False"""
        return False

    def is_valid_sort_data_type(self, data_type):
        """Always True on Snowflake.
        From Snowflake docs:
            Where each clustering key consists of one or more table columns/expressions, which can be of any
            data type, except VARIANT, OBJECT, or ARRAY
        """
        return True

    def is_valid_storage_compression(self, user_requested_codec, user_requested_format):
        return bool(user_requested_codec in ["NONE", None])

    def is_valid_storage_format(self, storage_format):
        return bool(storage_format is None)

    def is_view(self, db_name, object_name):
        return self.view_exists(db_name, object_name)

    def length_sql_expression(self, column_expression):
        assert column_expression
        return "LENGTH(%s)" % column_expression

    def list_databases(self, db_name_filter=None, case_sensitive=True):
        sql = (
            """SELECT schema_name FROM %s.information_schema.schemata WHERE catalog_name = ?"""
            % self.enclose_identifier(self._catalog_name())
        )
        query_params = [self._catalog_name()]
        if db_name_filter:
            sql += " AND schema_name %s ?" % ("LIKE" if case_sensitive else "ILIKE")
            query_params.append(db_name_filter.replace("*", "%"))
        rows = self.execute_query_fetch_all(sql, log_level=VVERBOSE, query_params=query_params)
        return [_[0] for _ in rows]

    def list_tables(self, db_name, table_name_filter=None, case_sensitive=True):
        sql = (
            """SELECT table_name FROM %s.information_schema.tables WHERE table_catalog = ? AND table_schema = ?"""
            % self.enclose_identifier(self._catalog_name())
        )
        query_params = [self._catalog_name(), db_name]
        if table_name_filter:
            sql += " AND table_name %s ?" % ("LIKE" if case_sensitive else "ILIKE")
            query_params.append(table_name_filter.replace("*", "%"))
        rows = self.execute_query_fetch_all(sql, log_level=VVERBOSE, query_params=query_params)
        return [_[0] for _ in rows]

    def list_udfs(self, db_name, udf_name_filter=None, case_sensitive=True):
        sql = dedent(
            """\
                SELECT procedure_name, data_type
                FROM  %s.information_schema.procedures
                WHERE procedure_catalog = ?
                AND   procedure_schema = ?"""
        ) % self.enclose_identifier(self._catalog_name())
        query_params = [self._catalog_name(), db_name]
        if udf_name_filter:
            sql += "\nAND   procedure_name %s ?" % ("LIKE" if case_sensitive else "ILIKE")
            query_params.append(udf_name_filter.replace("*", "%"))
        return self.execute_query_fetch_all(sql, log_level=VVERBOSE, query_params=query_params)

    def list_views(self, db_name, view_name_filter=None, case_sensitive=True):
        sql = (
            """SELECT table_name FROM %s.information_schema.views WHERE table_catalog = ? AND table_schema = ?"""
            % self.enclose_identifier(self._catalog_name())
        )
        query_params = [self._catalog_name(), db_name]
        if view_name_filter:
            sql += " AND table_name %s ?" % ("LIKE" if case_sensitive else "ILIKE")
            query_params.append(view_name_filter.replace("*", "%"))
        rows = self.execute_query_fetch_all(sql, log_level=VVERBOSE, query_params=query_params)
        return [_[0] for _ in rows]

    def max_decimal_integral_magnitude(self):
        return SNOWFLAKE_CAPABILITIES.max_decimal_integral_magnitude

    def max_decimal_precision(self):
        return SNOWFLAKE_CAPABILITIES.max_decimal_precision

    def max_decimal_scale(self, data_type=None):
        return SNOWFLAKE_CAPABILITIES.max_decimal_scale

    def max_datetime_value(self):
        return datetime64("99999-12-31T23:59:59.999999")

    def max_datetime_scale(self):
        return 9

    def max_partition_columns(self):
        return SNOWFLAKE_CAPABILITIES.max_partition_columns

    def max_sort_columns(self):
        """Cannot find a documented maximum but tested up to 15 columns and worked. Did find this in docs:
        https://docs.snowflake.com/en/user-guide/tables-clustering-keys.html#strategies-for-selecting-clustering-keys
            For most tables, Snowflake recommends a maximum of 3 or 4 columns (or expressions) per key.
            Adding more than 3-4 columns tends to increase costs more than benefits.
        """
        return SORT_COLUMNS_UNLIMITED

    def max_table_name_length(self):
        return SNOWFLAKE_CAPABILITIES.max_table_name_length

    def min_datetime_value(self):
        return datetime64("0000-01-01")

    def native_integer_types(self):
        return [SNOWFLAKE_TYPE_INTEGER]

    def partition_column_requires_synthetic_column(self, backend_column, granularity):
        return False

    def refresh_table_files(self, db_name, table_name, sync=None):
        """No requirement to re-scan files for a table on Snowflake but drop cache because that will be stale"""
        self.drop_state()

    def regexp_extract_sql_expression(self, subject, pattern):
        return "REGEXP_SUBSTR(%s, '%s', 1, 1, 'e')" % (subject, pattern)

    def rename_table(self, from_db_name, from_table_name, to_db_name, to_table_name, sync=None):
        assert from_db_name and from_table_name
        assert to_db_name and to_table_name

        if not self._dry_run and not self.table_exists(from_db_name, from_table_name):
            raise BackendApiException(
                "Source table does not exist, cannot rename table: %s.%s" % (from_db_name, from_table_name)
            )

        if not self._dry_run and self.exists(to_db_name, to_table_name):
            raise BackendApiException(
                "Target table already exists, cannot rename table to: %s.%s" % (to_db_name, to_table_name)
            )

        rename_sql = f"ALTER TABLE {self.enclose_identifier(from_db_name)}.{self.enclose_identifier(from_table_name)} RENAME TO {self.enclose_identifier(to_db_name)}.{self.enclose_identifier(to_table_name)}"

        executed_sqls = self.execute_ddl(rename_sql, sync=sync)
        self.catalog.on_drop_table(from_db_name, from_table_name)
        self.catalog.invalidate_table(to_db_name, to_table_name)
        return executed_sqls

    def role_exists(self, role_name):
        """Check the role exists, returns True/False"""
        sql = "SHOW ROLES LIKE '%s'" % role_name
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return bool(row)

    def set_column_stats(self, db_name, table_name, new_column_stats, ndv_cap, num_null_factor):
        raise NotImplementedError("Set of table statistics does not apply for Snowflake")

    def set_partition_stats(self, db_name, table_name, new_partition_stats, additive_stats):
        raise NotImplementedError("Set of table statistics does not apply for Snowflake")

    def set_table_stats(self, db_name, table_name, new_table_stats, additive_stats):
        raise NotImplementedError("Set of table statistics does not apply for Snowflake")

    def supported_backend_data_types(self):
        return [
            SNOWFLAKE_TYPE_BINARY,
            SNOWFLAKE_TYPE_DATE,
            SNOWFLAKE_TYPE_FLOAT,
            SNOWFLAKE_TYPE_NUMBER,
            SNOWFLAKE_TYPE_TEXT,
            SNOWFLAKE_TYPE_TIME,
            SNOWFLAKE_TYPE_TIMESTAMP_NTZ,
            SNOWFLAKE_TYPE_TIMESTAMP_TZ,
        ]

    def supported_date_based_partition_granularities(self):
        """No partitioning on Snowflake"""
        return

    def supported_partition_function_parameter_data_types(self):
        """No partitioning on Snowflake"""
        return

    def supported_partition_function_return_data_types(self):
        """No partitioning on Snowflake"""
        return

    def synthetic_partition_numbers_are_string(self):
        """No partitioning on Snowflake"""
        return

    def table_distribution(self, db_name, table_name):
        return None

    def table_exists(self, db_name: str, table_name: str) -> bool:
        """Return True/False if a table exists using the cached backend catalog."""
        return self.catalog.table_exists(db_name, table_name, self._fetch_table_exists)

    def table_has_rows(self, db_name: str, table_name: str) -> bool:
        """Return bool depending whether the table has rows or not."""
        sql = f"SELECT 1 FROM {self.enclose_object_reference(db_name, table_name)} LIMIT 1"
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return bool(row)

    def target_version(self):
        """Return version of the backend SQL engine in x.y.z format that can be used by GOEVersion().
        This is different to backend_version() even though it appears similar in function.
        """
        if self._target_version is None:
            sql = "SELECT current_version()"
            row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
            self._target_version = row[0] if row else None
        return self._target_version

    def to_backend_literal(self, py_val, data_type=None):
        """Translate a Python value to a Snowflake literal"""
        self._debug("Formatting %s literal: %s" % (type(py_val), repr(py_val)))
        self._debug("For backend datatype: %s" % data_type)
        new_py_val = SnowflakeLiteral.format_literal(py_val, data_type=data_type)
        self._debug("Final %s literal: %s" % (type(py_val), str(new_py_val)))
        return new_py_val

    def transform_encrypt_data_type(self):
        return SNOWFLAKE_TYPE_TEXT

    def transform_null_cast(self, backend_column):
        assert isinstance(backend_column, ColumnSpec) and backend_column.dialect is ColumnDialect.SNOWFLAKE
        return "CAST(NULL AS %s)" % (backend_column.format_data_type())

    def transform_tokenize_data_type(self):
        return SNOWFLAKE_TYPE_TEXT

    def transform_regexp_replace_expression(self, backend_column, regexp_replace_pattern, regexp_replace_string):
        return "REGEXP_REPLACE(%s, %s, %s)" % (
            self.enclose_identifier(backend_column.name),
            regexp_replace_pattern,
            regexp_replace_string,
        )

    def transform_translate_expression(self, backend_column, from_string, to_string):
        return "TRANSLATE(%s, %s, %s)" % (
            self.enclose_identifier(backend_column.name),
            from_string,
            to_string,
        )

    def udf_details(self, db_name, udf_name):
        """Get details of a Snowflake UDF

        UDF parameters are embedded in a string, e.g.:
        (ARG1 FLOAT, ARG2 STRING)
        """
        sql = dedent(
            """\
                SELECT data_type, argument_signature
                FROM  %s.information_schema.procedures
                WHERE procedure_catalog = ?
                AND   procedure_schema = ?
                AND   procedure_name = ?"""
        ) % self.enclose_identifier(self._catalog_name())
        query_params = [self._catalog_name(), db_name, udf_name]
        rows = self.execute_query_fetch_all(sql, log_level=VVERBOSE, query_params=query_params)
        udfs = []
        for row in rows:
            return_type = row[0] if row else None
            parameters = []
            if row and row[1]:
                arg_strings = re.findall(r"[A-Z0-9_]+ [A-Z0-9_]+", row[1])
                if arg_strings:
                    parameters = [UdfParameter(*_.split()) for _ in arg_strings]
            udfs.append(UdfDetails(db_name, udf_name, return_type, parameters))
        return udfs

    def valid_canonical_override(self, column, canonical_override):
        target_type = canonical_override.data_type if isinstance(canonical_override, ColumnSpec) else canonical_override
        return TYPE_REGISTRY.valid_canonical_override(
            column,
            target_type,
            self.type_mapping_context(),
        )

    def valid_staging_formats(self):
        return [FILE_STORAGE_FORMAT_AVRO, FILE_STORAGE_FORMAT_PARQUET]

    def view_exists(self, db_name, view_name):
        """Return True/False if a view exists
        See header of table_exists() for rationale for using SHOW VIEWS
        """
        sql = "SHOW TERSE VIEWS LIKE '%s' IN SCHEMA %s.%s STARTS WITH '%s'" % (
            view_name,
            self.enclose_identifier(self._catalog_name()),
            self.enclose_identifier(db_name),
            view_name,
        )
        try:
            cursor = self.execute_query_get_cursor(sql, log_level=None)
            headers = [_[0] for _ in cursor.description]
            assert headers[1] == "name"
            assert headers[3] == "database_name"
            assert headers[4] == "schema_name"
            rows = cursor.fetchall()
            if any((_[3], _[4], _[1]) == (self._catalog_name(), db_name, view_name) for _ in rows):
                return True
        except _SNOWFLAKE_PROGRAMMING_ERROR as exc:
            if "not exist" in (getattr(exc, "msg", None) or ""):
                return False
            raise
        return False

    def to_canonical_column(self, column):
        """Translate a Snowflake column to an internal GOE column."""
        return TYPE_REGISTRY.to_canonical(column, self.type_mapping_context())

    def from_canonical_column(self, column, decimal_padding_digits=0):
        """Translate an internal GOE column to a Snowflake column."""
        context = msgspec.structs.replace(self.type_mapping_context(), decimal_padding_digits=decimal_padding_digits)
        return TYPE_REGISTRY.from_canonical(column, self.type_mapping_target, context)

    def _backend_capabilities(self):
        return SNOWFLAKE_CAPABILITIES.to_capability_dict()

    def _fetch_table_exists(self, db_name: str, table_name: str) -> bool:
        """Uncached check for whether a Snowflake table exists using SHOW TERSE TABLES."""
        sql = "SHOW TERSE TABLES LIKE '%s' IN SCHEMA %s.%s STARTS WITH '%s'" % (
            table_name,
            self.enclose_identifier(self._catalog_name()),
            self.enclose_identifier(db_name),
            table_name,
        )
        try:
            cursor = self.execute_query_get_cursor(sql, log_level=None)
            headers = [_[0] for _ in cursor.description]
            assert headers[1] == "name"
            assert headers[3] == "database_name"
            assert headers[4] == "schema_name"
            rows = cursor.fetchall()
            if any((_[3], _[4], _[1]) == (self._catalog_name(), db_name, table_name) for _ in rows):
                return True
        except _SNOWFLAKE_PROGRAMMING_ERROR as exc:
            if "not exist" in (getattr(exc, "msg", None) or ""):
                return False
            raise
        return False

    def _fetch_table_size_and_row_count(self, db_name: str, table_name: str) -> tuple[int | None, int | None]:
        """Uncached lookup of (bytes, row_count) from information_schema.tables."""
        sql = dedent(
            """\
                SELECT bytes, row_count
                FROM   %s.information_schema.tables
                WHERE  table_catalog = ? AND table_schema = ? AND table_name = ?"""
            % self.enclose_identifier(self._catalog_name())
        )
        row = self.execute_query_fetch_one(
            sql,
            log_level=VVERBOSE,
            query_params=[self._catalog_name(), db_name, table_name],
        )
        return row or (None, None)

    def _get_binary_lengths_from_desc(self, db_name: str, table_name: str) -> dict[str, int]:
        """Extract BINARY column lengths from DESCRIBE TABLE or DESCRIBE VIEW."""
        if self.is_view(db_name, table_name):
            sql = "DESCRIBE VIEW %s" % self.enclose_object_reference(db_name, table_name)
        else:
            sql = "DESCRIBE TABLE %s" % self.enclose_object_reference(db_name, table_name)
        data_type_decode_re = re.compile(r"^([a-z0-9_]+)[\(]?([0-9]*)?[\)]?$", re.IGNORECASE)
        byte_lengths: dict[str, int] = {}
        for row in [_ for _ in self.execute_query_fetch_all(sql, log_level=VVERBOSE) if SNOWFLAKE_TYPE_BINARY in _[1]]:
            m = data_type_decode_re.match(row[1])
            if m:
                byte_length = int(m.group(2))
                byte_lengths[row[0]] = byte_length
        return byte_lengths

    def _fetch_columns(self, db_name: str, table_name: str) -> list[ColumnSpec]:
        """Uncached fetch of Snowflake table columns from information_schema.columns."""
        backend_columns: list[ColumnSpec] = []
        binary_byte_lengths: dict[str, int] = {}

        sql = dedent(
            """\
            SELECT column_name, data_type, is_nullable, character_maximum_length, character_octet_length
            ,      numeric_precision, numeric_scale, datetime_precision
            FROM   %s.information_schema.columns
            WHERE  table_catalog = ? AND table_schema = ? AND table_name = ?
            ORDER BY ordinal_position"""
            % self.enclose_identifier(self._catalog_name())
        )
        col_rows = self.execute_query_fetch_all(
            sql,
            log_level=VVERBOSE,
            query_params=[self._catalog_name(), db_name, table_name],
        )
        if any(_[1] == SNOWFLAKE_TYPE_BINARY for _ in col_rows):
            binary_byte_lengths = self._get_binary_lengths_from_desc(db_name, table_name)
        for col in col_rows:
            (
                col_name,
                data_type,
                is_nullable,
                char_length,
                byte_length,
                num_precision,
                num_scale,
                time_scale,
            ) = col
            data_scale = time_scale if time_scale is not None else num_scale
            if data_type == SNOWFLAKE_TYPE_BINARY:
                self._debug("Overriding byte_length for column %s with: %s" % (col_name, binary_byte_lengths[col_name]))
                char_length = byte_length = binary_byte_lengths[col_name]
            backend_columns.append(
                ColumnSpec(
                    ColumnDialect.SNOWFLAKE,
                    col_name,
                    data_type,
                    data_length=byte_length,
                    char_length=char_length,
                    data_precision=num_precision,
                    data_scale=data_scale,
                    nullable=is_nullable,
                )
            )
        return backend_columns

    def _catalog_name(self):
        """Using "catalog" because used in INFORMATION_SCHEMA to avoid confusion of using term "database" """
        if self._client:
            return self._client.database
        return self._connection_options.snowflake_database

    def _close_cursor(self):
        if self._client and self._cursor:
            try:
                self._cursor.close()
            except Exception as exc:
                self._log("Exception closing cursor:\n%s" % str(exc), detail=VVERBOSE)

    def _execute_ddl_or_dml(
        self,
        sql,
        sync=None,
        query_options=None,
        log_level=VERBOSE,
        profile=None,
        no_log_items=None,
    ):
        """See interface for parameter descriptions.
        sync is ignored on Snowflake.
        """
        assert sql
        assert isinstance(sql, (str, list))

        self._open_cursor()
        run_opts = self._execute_session_options(query_options, log_level=log_level)
        run_sqls = self._execute_sqls(sql, log_level=log_level, profile=profile, no_log_items=no_log_items)
        self._close_cursor()
        return run_opts + run_sqls

    def _execute_global_session_parameters(self, log_level=VVERBOSE):
        """On Snowflake we do not need to execute these, just return them to be used during connection."""
        return self._global_session_parameters

    def _execute_query_fetch_x(
        self,
        sql,
        fetch_action=FETCH_ACTION_ALL,
        query_options=None,
        log_level=None,
        time_sql=False,
        not_when_dry_running=False,
        query_params=None,
        profile=None,
        as_dict=False,
    ):
        """Run a query and fetch results
        query_options: key/value pairs for session settings
        query_params: list of bind values for 1..n params in sql as described in:
                      https://docs.snowflake.com/en/user-guide/python-connector-example.html#binding-data
        log_level: None = no logging. Otherwise VERBOSE/VVERBOSE etc
        time_sql: If logging then log SQL elapsed time
        not_when_dry_running: Some SQL will only work in execute mode, such as queries on a load table
        as_dict: When True each row is returned as a dict keyed by column name rather than a tuple/list.
        """
        assert sql

        if self._dry_run and not_when_dry_running:
            self._log_or_not("%s SQL: %s" % (self._sql_engine_name, sql), log_level=log_level)
            return None

        t1 = datetime.now().replace(microsecond=0)

        self._open_cursor()
        assert self._cursor is not None
        try:
            self._execute_session_options(query_options, log_level=log_level)
            self._log_or_not("%s SQL: %s" % (self._sql_engine_name, sql), log_level=log_level)
            self._cursor.execute(sql, query_params)
            if fetch_action == FETCH_ACTION_ALL:
                rows = self._cursor.fetchall()
                if as_dict:
                    columns = self._cursor_projection(self._cursor)
                    rows = [self._cursor_row_to_dict(columns, _) for _ in rows]
            elif fetch_action == FETCH_ACTION_ONE:
                rows = self._cursor.fetchone()
                if as_dict:
                    columns = self._cursor_projection(self._cursor)
                    rows = self._cursor_row_to_dict(columns, rows)
            else:
                rows = None

            if profile:
                self._log(self._get_query_profile(), detail=VVERBOSE)
        finally:
            if fetch_action in (FETCH_ACTION_ALL, FETCH_ACTION_ONE):
                self._close_cursor()

        if time_sql:
            t2 = datetime.now().replace(microsecond=0)
            self._log("Elapsed time: %s" % (t2 - t1), detail=VVERBOSE)

        if fetch_action == FETCH_ACTION_CURSOR:
            return self._cursor
        return rows

    def _execute_session_options(self, query_options, log_level):
        return_list = []
        if query_options:
            for prep_sql in self._format_query_options(query_options):
                self._log_or_not(
                    "%s SQL: %s" % (self._sql_engine_name, prep_sql),
                    log_level=log_level,
                )
                if self._client:
                    assert self._cursor is not None
                    self._cursor.execute(prep_sql)
                return_list.append(prep_sql)
        return return_list

    def _execute_sqls(self, sql, log_level=VERBOSE, profile=None, no_log_items=None):
        return_list = []
        sqls = [sql] if isinstance(sql, str) else sql
        self._open_cursor()
        try:
            for i, run_sql in enumerate(sqls):
                self._log_or_not(
                    "%s SQL: %s" % (self._sql_engine_name, run_sql),
                    log_level=log_level,
                    no_log_items=no_log_items,
                )
                return_list.append(run_sql)
                if not self._dry_run:
                    assert self._cursor is not None
                    self._cursor.execute(run_sql)
                    if profile:
                        self._log(self._get_query_profile(), detail=VVERBOSE)
        finally:
            self._close_cursor()
        return return_list

    @staticmethod
    def _fixed_session_parameters():
        """Dictionary of fixed session parameters for Snowflake"""
        return {
            "AUTOCOMMIT": "TRUE",
            "QUERY_TAG": "GOE",
            "TIMESTAMP_NTZ_OUTPUT_FORMAT": "YYYY-MM-DD HH24:MI:SS.FF9",
            "TIMESTAMP_TZ_OUTPUT_FORMAT": "YYYY-MM-DD HH24:MI:SS.FF9 TZHTZM",
            "TIME_OUTPUT_FORMAT": "HH24:MI:SS.FF9",
        }

    @staticmethod
    def _prep_param_value(v):
        if isinstance(v, str):
            return backtick_sandwich(v, ch="'")
        if isinstance(v, float):
            return repr(v)
        return str(v)

    @staticmethod
    def _format_query_options(query_options=None):
        """Format SET commands for Snowflake.
        query_options: key/value pairs for session settings.
        """
        if not query_options:
            return []
        assert isinstance(query_options, dict)
        return [f"ALTER SESSION SET {k}={BackendSnowflakeApi._prep_param_value(v)}" for k, v in query_options.items()]

    def _get_private_key_from_pemfile(self, pem_file, pem_passphrase):
        pass_tool = PasswordTools()
        return pass_tool.get_private_key_from_pkcs8_pem_file(pem_file, passphrase=pem_passphrase)

    def _gen_sample_stats_sql_sample_clause(self, db_name, table_name, sample_perc=None):
        assert db_name and table_name
        if sample_perc is not None and sample_perc >= 0 and self.query_sample_clause_supported():
            if self.is_view(db_name, table_name):
                return "SAMPLE ROW (%s)" % sample_perc
            return "SAMPLE BLOCK (%s)" % sample_perc
        return ""

    def _get_query_history_after_delay(self, wait_seconds):
        time.sleep(wait_seconds)
        sql = dedent(
            """\
             SELECT *
             FROM TABLE(
                %s.information_schema.query_history_by_session(end_time_range_end => CURRENT_TIMESTAMP,
                                                               result_limit => 1)
             )
             WHERE query_id = ?"""
            % self.enclose_identifier(self._catalog_name())
        )
        assert self._cursor is not None
        self._cursor.execute(sql, [self._cursor.sfqid])
        return self._cursor.fetchone()

    def _get_query_profile(self, query_identifier=None):
        """On Snowflake query_identifier is not used.
        We look for a query using the existing cursor.
        From Snowflake docs re QUERY_HISTORY view:
            Latency for the view may be up to 45 minutes.
        We don't see the same comment for QUERY_HISTORY table function.
        There's no query id parameter to functions so we filter on result set.
        This function has a built in retry because, in testing, we've frequently seen a delay of 1s in seeing data.

        Found the data was not always there instantly, so added a brief pause
        """
        assert self._cursor
        assert not self._cursor.is_closed()
        self._log("Fetching query history for id: %s" % self._cursor.sfqid, detail=VVERBOSE)
        row = self._get_query_history_after_delay(0.5)
        if not row:
            self._log("Query history not found (after attempt 1)", detail=VVERBOSE)
            row = self._get_query_history_after_delay(2)
        if not row:
            self._log("Query history not found (after attempt 2)", detail=VVERBOSE)
            return ""
        profile_keys = [_[0] for _ in self._cursor.description]
        stats = [("Statistic", "Value")]
        stats.extend(sorted(zip(profile_keys, [(_ if isinstance(_, str) else str(_)) for _ in row])))
        return format_list_for_logging(stats)

    def _get_snowflake_ddl(
        self,
        db_name,
        object_name,
        object_type,
        as_list=False,
        terminate_sql=False,
        for_replace=False,
    ):
        assert db_name and object_name
        self._log("Fetching DDL: %s.%s" % (db_name, object_name), detail=VVERBOSE)
        sql = "SELECT get_ddl('%s', '%s')" % (
            object_type,
            self.enclose_object_reference(db_name, object_name),
        )
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        if not row:
            raise BackendApiException("Object does not exist for DDL retrieval: %s.%s" % (db_name, object_name))
        ddl_str = row[0]
        self._debug("Object DDL: %s" % ddl_str)
        if not terminate_sql:
            ddl_str = ddl_str.rstrip(";")
        if as_list:
            return ddl_str.split("\n")
        return ddl_str

    def _invalid_identifier_character_re(self):
        return SNOWFLAKE_INVALID_IDENTIFIER_CHARS_RE

    def _open_cursor(self):
        self._cursor = self._client.cursor() if self._client else None

    def _role_granted_to_user(self, role_name, user_name):
        """Check if the role is granted to user, returns True/False"""
        assert role_name
        assert user_name
        sql = (
            "SELECT role_name FROM %s.information_schema.applicable_roles WHERE role_name = ? AND grantee = ?"
            % self.enclose_identifier(self._catalog_name())
        )
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE, query_params=[role_name, user_name])
        return bool(row)

    def _use_warehouse(self, warehouse_name, log_level=VERBOSE):
        assert warehouse_name
        try:
            return self.execute_ddl("USE WAREHOUSE %s" % warehouse_name, log_level=log_level)
        except _SNOWFLAKE_PROGRAMMING_ERROR as exc:
            self._log(traceback.format_exc(), detail=VVERBOSE)
            raise BackendApiException("Snowflake warehouse %s is not usable: %s" % (warehouse_name, str(exc)))

    def _warehouse_exists(self, warehouse_name):
        """Check the Warehouse exists, returns True/False"""
        sql = "SHOW WAREHOUSES LIKE '%s'" % warehouse_name
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return bool(row)
