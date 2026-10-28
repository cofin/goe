# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""BackendHadoopApi: BackendApi implementation for a Hadoop backend, Hive and Impala are subclasses of this.

Comment from nj@2019-11-06:
  The attraction in creating this module is that, at the time of writing, better_impyla
  has a rich and robust set of methods but I don't know what needs an equivalent in each new
  backend we introduce.
  Via this interface we can get a clear picture of the top level methods required and ensure,
  by using abstractmethod, that all backends offer the same functionality.

  Justification for not dismantling better_impyla from PR:

    better_impyla is not only used by our main orchestration tools. It is also used by other
    tools we have in the repo, such as cloud_sync. Retiring better_impyla completely would
    extend the scope to these other scripts. That was only a secondary consideration though.
    When I decided to use better_impyla as a lower level API rather than try and eliminate it
    the decision was based on there being zero contribution towards the goal of easing
    implementation of other backends. It was all risk and no reward. So I decided to treat that
    as a lower level API, just like Google's big query python module.

    Same for HiveStats & HiveTableStats which are based on better_impyla. There's a lot of
    mature/reliable code in there that contains branches between Hive and Impala but I’ve used
    those as valid building blocks rather than try to move logic away from them.
"""

import logging
import re
import time
import traceback
from datetime import datetime
from typing import ClassVar

import msgspec

from goe.filesystem.goe_dfs import (
    OFFLOAD_FS_SCHEME_S3A,
    get_scheme_from_location_uri,
)
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
    BackendApiConnectionException,
    BackendApiException,
    BackendApiInterface,
)
from goe.offload.backend_cache import BackendTableSnapshot
from goe.offload.hadoop.better_impyla import (
    BetterImpylaException,
    HiveConnection,
    HiveTable,
)
from goe.offload.hadoop.hive_table_stats import HiveTableStats
from goe.offload.hadoop.hs2_connection import HS2_OPTIONS, hs2_connection
from goe.offload.offload_constants import (
    DBTYPE_HIVE,
    DBTYPE_IMPALA,
    EMPTY_BACKEND_COLUMN_STATS_DICT,
    EMPTY_BACKEND_COLUMN_STATS_LIST,
    EMPTY_BACKEND_TABLE_STATS_DICT,
    EMPTY_BACKEND_TABLE_STATS_LIST,
    FILE_STORAGE_COMPRESSION_CODEC_GZIP,
    FILE_STORAGE_COMPRESSION_CODEC_SNAPPY,
    FILE_STORAGE_COMPRESSION_CODEC_ZLIB,
    FILE_STORAGE_FORMAT_AVRO,
    FILE_STORAGE_FORMAT_ORC,
    FILE_STORAGE_FORMAT_PARQUET,
    PART_COL_GRANULARITY_DAY,
    PART_COL_GRANULARITY_MONTH,
    PART_COL_GRANULARITY_YEAR,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.schema.column_spec import (
    HADOOP_TYPE_BIGINT,
    HADOOP_TYPE_CHAR,
    HADOOP_TYPE_DECIMAL,
    HADOOP_TYPE_DOUBLE,
    HADOOP_TYPE_FLOAT,
    HADOOP_TYPE_INT,
    HADOOP_TYPE_REAL,
    HADOOP_TYPE_SMALLINT,
    HADOOP_TYPE_STRING,
    HADOOP_TYPE_TIMESTAMP,
    HADOOP_TYPE_TINYINT,
    HADOOP_TYPE_VARCHAR,
    ColumnDialect,
    ColumnSpec,
    match_table_column,
)
from goe.offload.schema.type_registry import TYPE_REGISTRY, MappingTarget
from goe.offload.sql_ast.dialect_engine import DialectSqlEngine
from goe.util.module_loader import import_optional
from goe.util.string_utils import backtick_sandwich

_impala_hs2 = import_optional("impala.hiveserver2")
TTransportException: type[Exception] = _impala_hs2.TTransportException if _impala_hs2 is not None else OSError

HADOOP_DECIMAL_MAX_PRECISION = 38

HADOOP_DATA_TYPE_DECODE_RE = re.compile(r"^([a-z0-9_]+)[\(]?([0-9]*)?[\,]?([0-9]*)?[\)]?$", re.IGNORECASE)

HADOOP_INVALID_IDENTIFIER_CHARS_RE = re.compile(r"[^A-Z0-9_]", re.IGNORECASE)

IMPALA_PROFILE_LOG_LENGTH = 1024 * 32


def format_hive_set_command(attribute, value):
    return "SET %s=%s" % (attribute, value)


def hive_enable_dynamic_partitions_for_insert_sqls(
    max_dynamic_partitions=None, max_dynamic_partitions_pernode=None, as_dict=False
):
    """Hive session options for use when inserting into a partitioned table."""
    hive_settings: dict[str, str | int] = {
        "hive.exec.dynamic.partition": "true",
        "hive.exec.dynamic.partition.mode": "nonstrict",
    }

    if max_dynamic_partitions:
        hive_settings["hive.exec.max.dynamic.partitions"] = int(max_dynamic_partitions)
    if max_dynamic_partitions_pernode:
        hive_settings["hive.exec.max.dynamic.partitions.pernode"] = int(max_dynamic_partitions_pernode)

    if as_dict:
        return hive_settings
    sqls = [format_hive_set_command(k, v) for k, v in hive_settings.items()]
    return sqls


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class BackendHadoopApi(BackendApiInterface):
    """Common Hadoop backend implementation
    Impala and Hive share a lot of functionality, this class holds those
    common methods. Also Hadoop specifics, such as HDFS, should be found
    in this Hadoop class.
    """

    type_mapping_target: ClassVar[MappingTarget] = MappingTarget.HIVE

    def __init__(
        self,
        connection_options,
        backend_type,
        messages,
        dry_run=False,
        no_caching=False,
        do_not_connect=False,
    ):
        """CONSTRUCTOR"""
        super().__init__(
            connection_options,
            backend_type,
            messages,
            dry_run=dry_run,
            no_caching=no_caching,
            do_not_connect=do_not_connect,
        )

        self._sql_engine_name = "Hadoop"
        self._sql_engine = DialectSqlEngine("hive")

        self._target_version = None

        if do_not_connect:
            self._hive_conn = None
        else:
            self._validate_connection_options(HS2_OPTIONS)
            self._hive_conn = self._connect_to_backend()
            self._execute_global_session_parameters()

        self._cached_hive_tables = {}
        self._cached_hive_table_stats = {}

    def add_columns(self, db_name, table_name, column_tuples, sync=None):
        """See interface spec for description"""
        assert db_name and table_name
        assert column_tuples
        assert isinstance(column_tuples, list), "%s is not list" % type(column_tuples)
        assert isinstance(column_tuples[0], (tuple, list))
        column_clause = ", ".join(
            f"{self.enclose_identifier(col_name.lower())} {col_type.lower()}" for col_name, col_type in column_tuples
        )
        sql = "ALTER TABLE %s.%s ADD COLUMNS (%s)" % (
            self.enclose_identifier(db_name),
            self.enclose_identifier(table_name),
            column_clause,
        )
        result = self.execute_ddl(sql, sync=sync)
        self.catalog.on_alter_table(db_name, table_name)
        self._cached_hive_tables.pop((db_name + "_" + table_name).lower(), None)
        return result

    def backend_report_info(self):
        """Reporting information about the type of backend and how to display
        its configuration details (e.g. Hadoop host:port or BigQuery project).
        """
        return {
            REPORT_ATTR_BACKEND_CLASS: "Hadoop",
            REPORT_ATTR_BACKEND_TYPE: self._backend_type,
            REPORT_ATTR_BACKEND_DISPLAY_NAME: self.backend_db_name(),
            REPORT_ATTR_BACKEND_HOST_INFO_TYPE: "Host:port",
            REPORT_ATTR_BACKEND_HOST_INFO: "%s:%s"
            % (
                self._connection_options.hadoop_host,
                self._connection_options.hadoop_port,
            ),
        }

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
        except Exception as exc:
            self._log(traceback.format_exc(), detail=VVERBOSE)
            results.append(
                {
                    CONNECT_TEST: "Test backend user",
                    CONNECT_STATUS: False,
                    CONNECT_DETAIL: "Unable to obtain backend user: %s" % str(exc),
                }
            )

        try:
            v = self.backend_version()
            if v:
                results.append(
                    {
                        CONNECT_TEST: "Backend version",
                        CONNECT_STATUS: True,
                        CONNECT_DETAIL: v,
                    }
                )
            else:
                results.append(
                    {
                        CONNECT_TEST: "Backend version",
                        CONNECT_STATUS: False,
                        CONNECT_DETAIL: None,
                    }
                )
        except Exception as exc:
            self._log(traceback.format_exc(), detail=VVERBOSE)
            results.append(
                {
                    CONNECT_TEST: "Backend version",
                    CONNECT_STATUS: False,
                    CONNECT_DETAIL: "Unable to query version: %s" % str(exc),
                }
            )

        return results

    def close(self):
        if self._hive_conn:
            self.drop_state()

    def create_database(self, db_name, comment=None, properties=None, with_terminator=False):
        """Create a Hadoop database.
        properties: Allows properties["location"] to specify a DFS location
        """
        assert db_name
        if properties:
            assert isinstance(properties, dict)
        if comment:
            assert isinstance(comment, str)

        sql = "CREATE DATABASE IF NOT EXISTS %s" % self.enclose_identifier(db_name)
        if comment:
            sql += " COMMENT '%s'" % comment
        if properties and properties.get("location"):
            sql += " LOCATION '%s'" % properties["location"]
        if with_terminator:
            sql += ";"

        return self.execute_ddl(sql)

    def create_view(
        self,
        db_name,
        view_name,
        column_tuples,
        ansi_joined_tables,
        filter_clauses=None,
        sync=None,
    ):
        """Create a Hadoop view.
        See create_view() description for parameter descriptions.
        """
        projection = self._format_select_projection(column_tuples)
        where_clause = "\nWHERE  " + "\nAND    ".join(filter_clauses) if filter_clauses else ""
        sql = """CREATE VIEW %(db)s.%(view)s AS
SELECT %(projection)s
FROM   %(from_tables)s%(where_clause)s""" % {
            "db": self.enclose_identifier(db_name),
            "view": self.enclose_identifier(view_name),
            "projection": projection,
            "from_tables": ansi_joined_tables,
            "where_clause": where_clause,
        }
        return self.execute_ddl(sql, sync=sync)

    def data_type_accepts_length(self, data_type):
        return bool(data_type in [HADOOP_TYPE_CHAR, HADOOP_TYPE_DECIMAL, HADOOP_TYPE_VARCHAR])

    def database_exists(self, db_name):
        assert db_name
        assert self._hive_conn is not None
        return self._hive_conn.database_exists(db_name.lower())

    def db_name_label(self, initcap=False):
        label = "database"
        return label.capitalize() if initcap else label

    def default_date_based_partition_granularity(self):
        return PART_COL_GRANULARITY_MONTH

    def default_storage_compression(self, user_requested_codec, user_requested_format):
        codec = user_requested_codec or FILE_STORAGE_COMPRESSION_CODEC_SNAPPY
        if codec == "HIGH" and user_requested_format == FILE_STORAGE_FORMAT_ORC:
            codec = FILE_STORAGE_COMPRESSION_CODEC_ZLIB
        elif codec == "HIGH" and user_requested_format == FILE_STORAGE_FORMAT_PARQUET:
            codec = FILE_STORAGE_COMPRESSION_CODEC_GZIP
        elif codec == "MED":
            codec = FILE_STORAGE_COMPRESSION_CODEC_SNAPPY
        return codec

    def derive_native_partition_info(self, db_name, table_name, column, position):
        """Return a ColumnPartitionSpec object (or None) based on native partition settings.
        No such thing on Hadoop.
        """
        return

    def detect_column_has_fractional_seconds(self, db_name, table_name, column):
        assert db_name and table_name
        assert isinstance(column, ColumnSpec) and column.dialect is ColumnDialect.HADOOP
        if column.data_type != HADOOP_TYPE_TIMESTAMP:
            return False
        sql = """SELECT %(col)s
FROM %(db_table)s
WHERE UNIX_TIMESTAMP(%(col)s) >= 0 AND %(col)s != FROM_UNIXTIME(UNIX_TIMESTAMP(%(col)s))
LIMIT 1""" % {
            "db_table": self.enclose_object_reference(db_name, table_name),
            "col": self.enclose_identifier(column.name),
        }
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return True if row else False

    def drop_state(self):
        """Drop any cached state so values are refreshed on next request."""
        self.catalog.clear()
        self._cached_hive_tables = {}
        self._cached_hive_table_stats = {}

    def drop_table(self, db_name, table_name, purge=False, if_exists=True, sync=None):
        """Drop a table and cater for backend specific details
        See abstract method for more description
        """
        assert db_name and table_name
        if_exists_clause = "IF EXISTS " if if_exists else ""
        drop_sql = "DROP TABLE %s%s" % (
            if_exists_clause,
            self.enclose_object_reference(db_name, table_name),
        )
        if purge:
            drop_sql += " PURGE"
        result = self.execute_ddl(drop_sql, sync=sync)
        self.catalog.on_drop_table(db_name, table_name)
        self._cached_hive_tables.pop((db_name + "_" + table_name).lower(), None)
        return result

    def drop_view(self, db_name, view_name, if_exists=True, sync=None):
        assert db_name and view_name
        if_exists_clause = "IF EXISTS " if if_exists else ""
        drop_sql = "DROP VIEW %s%s" % (
            if_exists_clause,
            self.enclose_object_reference(db_name, view_name),
        )
        return self.execute_ddl(drop_sql, sync=sync)

    def enclose_identifier(self, identifier):
        """Backtick identifiers on Hadoop, also lower case them for historical reasons."""
        if identifier is None:
            return None
        return backtick_sandwich(identifier.lower(), ch=self.enclosure_character())

    def enclose_object_reference(self, db_name, object_name):
        """Backtick identifiers on Hadoop, also lower case them for historical reasons."""
        assert db_name and object_name
        return self.enclose_identifier(db_name.lower()) + "." + self.enclose_identifier(object_name.lower())

    def enclosure_character(self):
        return "`"

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
        """Does the table/view exist.
        When using impyla module table_exists() is for views too.
        """
        assert db_name
        assert object_name
        return self.catalog.table_exists(
            db_name,
            object_name,
            self._fetch_table_exists,
        )

    def format_hadoop_partition_clause(self, partition_tuples, sep_char="/"):
        """Hadoop specific function call for use from Hadoop specific BackendTable function
        of Hadoop specific BackendTestingApi.
        There is no abstractmethod for this function
        """
        assert self._backend_type in [DBTYPE_HIVE, DBTYPE_IMPALA]
        return self._format_partition_clause(partition_tuples, sep_char=sep_char)

    def format_query_parameter(self, param_name):
        return param_name

    def gen_column_object(self, column_name, **kwargs):
        return ColumnSpec(ColumnDialect.HADOOP, column_name, **kwargs)

    def gen_default_numeric_column(self, column_name, data_scale=18):
        """Return a default best-fit numeric column for generic usage."""
        return TYPE_REGISTRY.default_numeric_column(
            column_name,
            self.type_mapping_target,
            self.type_mapping_context(),
            data_scale=data_scale,
        )

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
        """See interface description for parameter descriptions"""
        assert db_name and table_name
        assert storage_format
        assert column_tuples
        assert isinstance(column_tuples, list), "%s is not list" % type(column_tuples)
        assert isinstance(column_tuples[0], (tuple, list))

        external_clause = " EXTERNAL" if external else ""
        projection = self._format_select_projection(column_tuples)
        from_clause = (
            f"\nFROM   {self.enclose_object_reference(from_db_name, from_table_name)}"
            if from_db_name and from_table_name
            else ""
        )
        limit_clause = f"\nLIMIT  {row_limit}" if row_limit is not None else ""
        if table_properties:
            table_prop_clause = "\nTBLPROPERTIES (%s)" % ", ".join(
                "%s=%s" % (self.to_backend_literal(k), self.to_backend_literal(v)) for k, v in table_properties.items()
            )
        else:
            table_prop_clause = ""
        sql = """CREATE%(external_clause)s TABLE %(db_table)s STORED AS %(storage)s%(table_prop_clause)s AS
SELECT %(projection)s%(from_clause)s%(limit_clause)s""" % {
            "external_clause": external_clause,
            "db_table": self.enclose_object_reference(db_name, table_name),
            "storage": storage_format,
            "table_prop_clause": table_prop_clause,
            "projection": projection,
            "from_clause": from_clause,
            "limit_clause": limit_clause,
        }
        return sql

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
        return HADOOP_TYPE_STRING

    def get_columns(self, db_name, table_name):
        assert db_name and table_name
        return list(
            self.catalog.get_columns(
                db_name,
                table_name,
                self._fetch_columns,
            )
        )

    def gen_copy_into_sql_text(
        self,
        db_name,
        table_name,
        from_object_clause,
        select_expr_tuples,
        filter_clauses=None,
    ):
        raise NotImplementedError("COPY INTO does not exist in Hadoop SQL")

    def get_distinct_column_values(
        self,
        db_name,
        table_name,
        column_name_list,
        columns_to_cast_to_string=None,
        order_results=False,
        not_when_dry_running=False,
    ):
        """Run SQL to get distinct values for a list of columns
        The columns_to_cast_to_string parameter is because our HiveServer2 DBAPI does not support nanoseconds
        therefore we bring certain data types back as strings to avoid truncating to milliseconds
        """

        def add_sql_cast(col):
            return ("CAST(%s as STRING)" % col) if col in (columns_to_cast_to_string or []) else col

        assert column_name_list and isinstance(column_name_list, list)
        assert isinstance(column_name_list[0], str)
        expression_list = [add_sql_cast(self.enclose_identifier(_)) for _ in column_name_list]
        return self.get_distinct_expressions(
            db_name,
            table_name,
            expression_list,
            order_results=order_results,
            not_when_dry_running=not_when_dry_running,
        )

    def gen_native_range_partition_key_cast(self, partition_column):
        """No native range partitioning on Hadoop"""
        raise NotImplementedError("Native range partitioning unsupported on Snowflake")

    def get_hive_conn(self):
        return self._hive_conn

    def get_partition_columns(self, db_name, table_name):
        assert db_name and table_name
        return list(
            self.catalog.get_partition_columns(
                db_name,
                table_name,
                self._fetch_partition_columns,
            )
        )

    def get_session_option(self, option_name):
        raise NotImplementedError("get_session_option() is not implemented for common Hadoop class")

    def get_table_ddl(self, db_name, table_name, as_list=False, terminate_sql=False, for_replace=False):
        """Return table DDL as a string (or a list of strings split on CR if as_list=True)
        for_replace ignored on Hadoop

        Convert BetterImpylaExceptions to BackendApi
        """
        assert db_name and table_name
        self._log("Fetching table DDL: %s.%s" % (db_name, table_name), detail=VVERBOSE)
        try:
            hive_table = self._get_hive_table(db_name, table_name)
        except BetterImpylaException as exc:
            raise BackendApiException(str(exc)) from exc
        ddl_str = hive_table.table_ddl(terminate_sql=terminate_sql)
        if not ddl_str:
            raise BackendApiException("Table does not exist for DDL retrieval: %s.%s" % (db_name, table_name))
        self._debug("Table DDL: %s" % ddl_str)
        if as_list:
            return ddl_str.split("\n")
        return ddl_str

    def get_table_location(self, db_name, table_name):
        if self.table_exists(db_name, table_name):
            hive_table = self._get_hive_table(db_name, table_name)
            return hive_table.table_location()
        return None

    def get_table_partition_count(self, db_name, table_name):
        assert db_name and table_name
        hive_table = self._get_hive_table(db_name, table_name)
        return len(hive_table.table_partitions())

    def get_table_partitions(self, db_name, table_name):
        raise NotImplementedError("get_table_partitions() is not implemented for common Hadoop class")

    def get_table_row_count_from_metadata(self, db_name, table_name):
        hive_table = self._get_hive_table(db_name, table_name)
        return hive_table.num_rows()

    def get_table_size_and_row_count(self, db_name, table_name):
        return (
            self.get_table_size(db_name, table_name),
            self.get_table_row_count_from_metadata(db_name, table_name),
        )

    def get_table_stats(self, db_name, table_name, as_dict=False):
        if self.table_exists(db_name, table_name) and self.table_stats_get_supported():
            hive_stats = self._get_hive_stats_table(db_name, table_name)
            tab_stats, _, col_stats = self._get_table_stats(hive_stats, as_dict=as_dict)
            return tab_stats, col_stats
        if as_dict:
            return EMPTY_BACKEND_TABLE_STATS_DICT, EMPTY_BACKEND_COLUMN_STATS_DICT
        return EMPTY_BACKEND_TABLE_STATS_LIST, EMPTY_BACKEND_COLUMN_STATS_LIST

    def get_table_and_partition_stats(self, db_name, table_name, as_dict=False):
        """This has been broken out from get_table_stats() because the output looks pretty Hadoop specific
        If we decide we need this functionality for another backend then we should look at the format
        and decide what to do
        """
        if self.table_exists(db_name, table_name) and self.table_stats_get_supported():
            hive_stats = self._get_hive_stats_table(db_name, table_name)
            return self._get_table_stats(hive_stats, as_dict=as_dict, part_stats=True)
        if as_dict:
            return (
                EMPTY_BACKEND_TABLE_STATS_DICT,
                {},
                EMPTY_BACKEND_COLUMN_STATS_DICT,
            )
        return (
            EMPTY_BACKEND_TABLE_STATS_LIST,
            [],
            EMPTY_BACKEND_COLUMN_STATS_LIST,
        )

    def get_table_stats_partitions(self, db_name, table_name):
        if not self.table_stats_get_supported():
            return []
        hive_stats = self._get_hive_stats_table(db_name, table_name)
        return hive_stats.table_partitions()

    def is_valid_partitioning_data_type(self, data_type):
        """TODO Add HADOOP_TYPE_DATE to list below when GOE-1458 is complete"""
        if not data_type:
            return False
        return bool(
            data_type.upper()
            in [
                HADOOP_TYPE_BIGINT,
                HADOOP_TYPE_CHAR,
                HADOOP_TYPE_DECIMAL,
                HADOOP_TYPE_DOUBLE,
                HADOOP_TYPE_FLOAT,
                HADOOP_TYPE_INT,
                HADOOP_TYPE_REAL,
                HADOOP_TYPE_STRING,
                HADOOP_TYPE_SMALLINT,
                HADOOP_TYPE_TIMESTAMP,
                HADOOP_TYPE_TINYINT,
                HADOOP_TYPE_VARCHAR,
            ]
        )

    def is_valid_sort_data_type(self, data_type):
        """No known data type restrictions for sorting in Hadoop."""
        return True

    def is_valid_storage_compression(self, user_requested_codec, user_requested_format):
        if user_requested_codec == "NONE":
            return True
        if user_requested_format == FILE_STORAGE_FORMAT_ORC and user_requested_codec in [
            FILE_STORAGE_COMPRESSION_CODEC_SNAPPY,
            FILE_STORAGE_COMPRESSION_CODEC_ZLIB,
        ]:
            return True
        if user_requested_format == FILE_STORAGE_FORMAT_PARQUET and user_requested_codec in [
            FILE_STORAGE_COMPRESSION_CODEC_SNAPPY,
            FILE_STORAGE_COMPRESSION_CODEC_GZIP,
        ]:
            return True
        return False

    def is_view(self, db_name, object_name):
        """view does not exist"""
        try:
            hive_table = self._get_hive_table(db_name, object_name)
            return hive_table.is_view()
        except BetterImpylaException:
            return False

    def length_sql_expression(self, column_expression):
        assert column_expression
        return "LENGTH(%s)" % column_expression

    def list_databases(self, db_name_filter=None, case_sensitive=True):
        """In Impala all object names are lower case so case_sensitive does not apply."""
        self._debug("list_databases(%s)" % db_name_filter)
        if db_name_filter:
            sql = "SHOW DATABASES LIKE '%s'" % db_name_filter.lower()
        else:
            sql = "SHOW DATABASES"
        rows = self.execute_query_fetch_all(sql, log_level=VVERBOSE)
        if rows:
            return [_[0] for _ in rows]
        return []

    def list_tables(self, db_name, table_name_filter=None, case_sensitive=True):
        """In Hadoop all object names are lower case so case_sensitive does not apply."""
        assert db_name
        if table_name_filter:
            sql = "SHOW TABLES IN %s LIKE '%s'" % (db_name, table_name_filter.lower())
        else:
            sql = "SHOW TABLES IN %s" % db_name
        rows = self.execute_query_fetch_all(sql, log_level=VVERBOSE)
        if rows:
            return [_[0] for _ in rows]
        return []

    def list_udfs(self, db_name, udf_name_filter=None, case_sensitive=True):
        raise NotImplementedError("list_udfs() is not implemented for common Hadoop class")

    def list_views(self, db_name, view_name_filter=None, case_sensitive=True):
        """In Hadoop list tables/views is the same command.
        Filtering afterwards is too inefficient therefore NotImplementedError
        """
        raise NotImplementedError("list_views() is not implemented for Hadoop")

    def max_decimal_integral_magnitude(self):
        return HADOOP_DECIMAL_MAX_PRECISION

    def max_decimal_precision(self):
        return HADOOP_DECIMAL_MAX_PRECISION

    def max_decimal_scale(self, data_type=None):
        return 38

    def max_datetime_scale(self):
        """Hive & Impala support nanoseconds"""
        return 9

    def max_partition_columns(self):
        """Returning 100 as an extremely unlikely to be a factor limit.
        Previously we had no check for a limit but needed to introduce something
        because on BigQuery
        """
        return 100

    def max_sort_columns(self):
        """Returning SORT_COLUMNS_UNLIMITED as an extremely unlikely to be a factor limit.
        Previously we had no check for a limit but needed to introduce something because of BigQuery.
        """
        return SORT_COLUMNS_UNLIMITED

    def native_integer_types(self):
        return [
            HADOOP_TYPE_BIGINT,
            HADOOP_TYPE_INT,
            HADOOP_TYPE_SMALLINT,
            HADOOP_TYPE_TINYINT,
        ]

    def partition_column_requires_synthetic_column(self, backend_column, granularity):
        """On Hadoop all partition columns currently require a synthetic column."""
        return True

    def regexp_extract_sql_expression(self, subject, pattern):
        return "REGEXP_EXTRACT(%s, '%s', 1)" % (subject, pattern)

    def rename_table(self, from_db_name, from_table_name, to_db_name, to_table_name, sync=None):
        """Rename a Hive/Impala table
        If the table is stored in S3 then we need to switch the table to be an external table before renaming
        """
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

        table_location = self.get_table_location(from_db_name, from_table_name)
        fs_scheme = get_scheme_from_location_uri(table_location) if table_location else None
        if fs_scheme == OFFLOAD_FS_SCHEME_S3A and not self.transactional_tables_default():
            self._log(
                "Renaming S3 based table using external table management: %s.%s" % (from_db_name, from_table_name),
                detail=VERBOSE,
            )
            self._alter_table_external(from_db_name, from_table_name, external=True)

        executed_sqls = self.execute_ddl(rename_sql, sync=sync)

        if fs_scheme == OFFLOAD_FS_SCHEME_S3A and not self.transactional_tables_default():
            self._alter_table_external(to_db_name, to_table_name, external=False)

        self.catalog.on_drop_table(from_db_name, from_table_name)
        self.catalog.on_alter_table(to_db_name, to_table_name)
        self._cached_hive_tables.pop((from_db_name + "_" + from_table_name).lower(), None)
        self._cached_hive_tables.pop((to_db_name + "_" + to_table_name).lower(), None)

        return executed_sqls

    def role_exists(self, role_name):
        """No roles in Hadoop"""

    def set_column_stats(self, db_name, table_name, new_column_stats, ndv_cap, num_null_factor):
        if not self.table_stats_get_supported():
            return
        hive_stats = self._get_hive_stats_table(db_name, table_name)
        hive_stats.set_column_stats(
            new_column_stats,
            self._backend_type,
            ndv_cap=ndv_cap,
            num_null_factor=num_null_factor,
            dry_run=self._dry_run,
            messages=self._messages,
        )

    def set_partition_stats(self, db_name, table_name, new_partition_stats, additive_stats):
        if not self.table_stats_get_supported():
            return
        hive_stats = self._get_hive_stats_table(db_name, table_name)
        hive_stats.set_partition_stats(
            new_partition_stats,
            self._backend_type,
            additive=additive_stats,
            dry_run=self._dry_run,
            messages=self._messages,
        )

    def set_session_db(self, db_name, log_level=VERBOSE):
        assert db_name
        return self.execute_ddl("USE %s" % db_name, log_level=log_level)

    def set_table_stats(self, db_name, table_name, new_table_stats, additive_stats):
        if not self.table_stats_get_supported():
            return
        hive_stats = self._get_hive_stats_table(db_name, table_name)
        hive_stats.set_table_stats(
            new_table_stats,
            self._backend_type,
            additive=additive_stats,
            dry_run=self._dry_run,
            messages=self._messages,
        )

    def supported_date_based_partition_granularities(self):
        return [
            PART_COL_GRANULARITY_YEAR,
            PART_COL_GRANULARITY_MONTH,
            PART_COL_GRANULARITY_DAY,
        ]

    def supported_partition_function_parameter_data_types(self):
        return [HADOOP_TYPE_DECIMAL, HADOOP_TYPE_BIGINT, HADOOP_TYPE_STRING]

    def supported_partition_function_return_data_types(self):
        return [
            HADOOP_TYPE_BIGINT,
            HADOOP_TYPE_INT,
            HADOOP_TYPE_SMALLINT,
            HADOOP_TYPE_TINYINT,
        ]

    def synthetic_partition_numbers_are_string(self):
        return True

    def table_distribution(self, db_name, table_name):
        return None

    def table_exists(self, db_name: str, table_name: str) -> bool:
        return self.exists(db_name, table_name)

    def table_has_rows(self, db_name: str, table_name: str) -> bool:
        """Return bool depending whether the table has rows or not."""
        sql = f"SELECT 1 FROM {self.enclose_object_reference(db_name, table_name)} LIMIT 1"
        row = self.execute_query_fetch_one(sql, log_level=VVERBOSE)
        return bool(row)

    def target_version(self):
        """Only get sql_engine_version if _hive_conn is set, won't be in unit tests"""
        if self._target_version is None:
            if self._hive_conn is None:
                self._target_version = "0.0.0"
            else:
                self._target_version = self._hive_conn.sql_engine_version()
        return self._target_version

    def transactional_tables_default(self):
        """Whether a CREATE TABLE statement would create a Hive3 based transactional table by default"""
        return False

    def transform_encrypt_data_type(self):
        return HADOOP_TYPE_STRING

    def transform_null_cast(self, backend_column):
        assert isinstance(backend_column, ColumnSpec) and backend_column.dialect is ColumnDialect.HADOOP
        return "CAST(NULL AS %s)" % (backend_column.format_data_type())

    def transform_tokenize_data_type(self):
        return HADOOP_TYPE_STRING

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

    def udf_exists(self, db_name, udf_name):
        try:
            return bool(self.list_udfs(db_name, udf_name))
        except BetterImpylaException as exc:
            if "does not exist" in str(exc):
                return False
            raise

    def valid_canonical_override(self, column, canonical_override):
        target_type = canonical_override.data_type if isinstance(canonical_override, ColumnSpec) else canonical_override
        return TYPE_REGISTRY.valid_canonical_override(
            column,
            target_type,
            self.type_mapping_context(),
        )

    def valid_staging_formats(self):
        return [FILE_STORAGE_FORMAT_AVRO]

    def view_exists(self, db_name, view_name):
        return self.exists(db_name, view_name)

    def to_canonical_column(self, column):
        """Translate a Hive/Impala column to an internal GOE column."""
        return TYPE_REGISTRY.to_canonical(column, self.type_mapping_context())

    def from_canonical_column(self, column, decimal_padding_digits=0):
        """Translate an internal GOE column to a Hadoop column."""
        context = msgspec.structs.replace(self.type_mapping_context(), decimal_padding_digits=decimal_padding_digits)
        return TYPE_REGISTRY.from_canonical(column, self.type_mapping_target, context)

    def warm_schema(self, db_name: str) -> int:
        """Warm the catalog cache for all tables in a Hadoop database."""
        assert db_name
        table_names = self.list_tables(db_name)
        now = time.monotonic()
        snapshots: list[BackendTableSnapshot] = []
        for table_name in table_names:
            snapshots.append(
                BackendTableSnapshot(
                    db_name=db_name.lower(),
                    table_name=table_name.lower(),
                    exists=True,
                    fetched_at=now,
                )
            )
        return self.catalog.warm_schema(db_name, snapshots)

    def _fetch_table_exists(self, db_name: str, object_name: str) -> bool:
        assert self._hive_conn is not None
        return bool(self._hive_conn.table_exists(db_name.lower(), object_name.lower()))

    def _fetch_columns(self, db_name: str, table_name: str) -> list[ColumnSpec]:
        hive_table = self._get_hive_table(db_name, table_name)
        legacy_columns = hive_table.all_columns()
        return self._legacy_column_list_to_type(legacy_columns)

    def _fetch_partition_columns(self, db_name: str, table_name: str) -> list[ColumnSpec]:
        hive_table = self._get_hive_table(db_name, table_name)
        part_cols_as_list = hive_table.partition_columns()
        return self._legacy_column_list_to_type(part_cols_as_list)

    def _alter_table_external(self, db_name, table_name, external=True):
        """Execute Hive SQL to switch a table to external or managed"""
        assert db_name and table_name
        alter_sql = "ALTER TABLE {}.{} SET TBLPROPERTIES ('EXTERNAL'='{}')".format(
            self.enclose_identifier(db_name),
            self.enclose_identifier(table_name),
            "TRUE" if external else "FALSE",
        )
        return self.execute_ddl(alter_sql)

    def _backend_capabilities(self):
        raise NotImplementedError("_backend_capabilities() is not implemented for common Hadoop class")

    def _connect_to_backend(self, host_override=None, port_override=None):
        host = host_override or self._connection_options.hadoop_host
        port = port_override or self._connection_options.hadoop_port
        try:
            return HiveConnection.fromconnection(
                hs2_connection(self._connection_options, host_override=host, port_override=port),
                db_type=self._backend_type,
            )
        except (OSError, TTransportException) as exc:
            self._log(traceback.format_exc(), detail=VERBOSE)
            if "TSocket read 0 bytes" in str(exc) or "Bad status: 3 (Error validating the login)" in str(exc):
                encryption_text = "ly encrypted" if self._connection_options.password_key_file else ""
                raise BackendApiConnectionException(
                    self._get_hadoop_connection_exception_message_template()
                    % {"host": host, "port": port, "enc_text": encryption_text}
                )
            if "Credentials cache file" in str(exc):
                raise BackendApiConnectionException(
                    "Check klist output - orchestration tools require a kerberos authenticated session"
                )
            raise

    def _decode_hadoop_data_type_spec(self, data_type_spec):
        """Takes a data type spec as output by DESCRIBE, e.g. DECIMAL(10,2), and
        returns 4 components:
            (data type, data_length, data_precision, data_scale)
        """
        m = HADOOP_DATA_TYPE_DECODE_RE.match(data_type_spec.upper())
        if not m:
            raise NotImplementedError("Unsupported backend datatype: %s" % data_type_spec.upper())
        data_type, precision, scale = m.groups()
        precision = None if precision == "" else precision
        scale = None if scale == "" else scale
        if not self.is_supported_data_type(data_type):
            raise NotImplementedError("Unsupported backend datatype: %s" % data_type)
        if data_type == HADOOP_TYPE_DECIMAL:
            return (data_type, None, int(precision or 0), int(scale or 0))
        if data_type in (HADOOP_TYPE_VARCHAR, HADOOP_TYPE_CHAR):
            return (data_type, int(precision or 0), None, None)
        return (data_type, None, None, None)

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
        query_params: Not applicable on Hadoop
        log_level: None = no logging. Otherwise VERBOSE/VVERBOSE etc
        time_sql: If logging then log SQL elapsed time
        not_when_dry_running: Some SQL will only work in execute mode, such as queries on a load table
        as_dict: When True each row is returned as a dict keyed by column name rather than a tuple/list.
        """
        assert sql

        self._execute_session_options(query_options, log_level=log_level)

        self._log_or_not("%s SQL: %s" % (self._sql_engine_name, sql), log_level=log_level)

        if self._dry_run and not_when_dry_running:
            return None

        t1 = datetime.now().replace(microsecond=0)
        if fetch_action == FETCH_ACTION_ALL:
            cursor_fn = lambda c: c.fetchall()
        elif fetch_action == FETCH_ACTION_ONE:
            cursor_fn = lambda c: c.fetchone()
        else:
            cursor_fn = lambda c: c

        assert self._hive_conn is not None
        rows = self._hive_conn.execute(sql, cursor_fn=cursor_fn)

        if as_dict:
            columns = self._cursor_projection(self._hive_conn.cursor)
            if fetch_action == FETCH_ACTION_ALL:
                rows = [self._cursor_row_to_dict(columns, _) for _ in rows]
            else:
                rows = self._cursor_row_to_dict(columns, rows)

        if time_sql:
            t2 = datetime.now().replace(microsecond=0)
            self._log("Elapsed time: %s" % (t2 - t1), detail=VVERBOSE)

        if profile:
            sql_profile = self._get_query_profile()
            if sql_profile:
                self._log(sql_profile[:IMPALA_PROFILE_LOG_LENGTH], detail=VVERBOSE)
        return rows

    def _execute_global_session_parameters(self, log_level=VVERBOSE):
        """Execute global backend session parameters.
        We do this outside of _execute_session_options() so that global settings can be applied before any
        localised requirements. If we merged the dicts we would lose the order, I (NJ) made the call that localised
        settings should take precedence over global settings, this may prove to be the wrong way around, only
        time will tell.
        """
        if self._global_session_parameters:
            if log_level is not None:
                self._log("Setting global session options:", detail=log_level)
            return self._execute_session_options(self._global_session_parameters, log_level=log_level)
        return []

    def _execute_session_options(self, query_options, log_level):
        """Sharing code between Hive and Impala"""
        return_list = []
        if query_options:
            for prep_sql in self._format_query_options(query_options):
                self._log_or_not(
                    "%s SQL: %s" % (self._sql_engine_name, prep_sql),
                    log_level=log_level,
                )
                if self._hive_conn:
                    self._hive_conn.execute(prep_sql)
                return_list.append(prep_sql)
            if self._hive_conn:
                self._hive_conn._cursor.execute("set")
        return return_list

    def _execute_sqls(self, sql, log_level=VERBOSE, profile=None, no_log_items=None):
        """Sharing code between Hive and Impala"""
        return_list = []
        sqls = [sql] if isinstance(sql, str) else sql
        for i, run_sql in enumerate(sqls):
            self._log_or_not(
                "%s SQL: %s" % (self._sql_engine_name, run_sql),
                log_level=log_level,
                no_log_items=no_log_items,
            )
            return_list.append(run_sql)
            if not self._dry_run:
                assert self._hive_conn is not None
                self._hive_conn.execute(run_sql)
                if profile and i == 0:
                    sql_profile = self._get_query_profile()
                    if sql_profile:
                        self._log(sql_profile[:IMPALA_PROFILE_LOG_LENGTH], detail=VVERBOSE)
                    return_list.append("PROFILE")
        return return_list

    def _format_partition_clause(self, partition_tuples, sep_char="/"):
        """Formats a partition clause as a HDFS style string"""

        def str_value_fn(val):
            return self._partition_clause_null_constant() if val is None else val

        if not partition_tuples:
            return None
        return sep_char.join(f"{_[0]}={str_value_fn(_[1])}" for _ in partition_tuples)

    def _format_partition_clause_for_sql(self, db_name, table_name, partition_tuples):
        """Formats a partition clause as a SQL style string
        Requires db/table info in order to get the data types and format the literal correctly
        """
        assert db_name and table_name
        if not partition_tuples:
            return None
        assert isinstance(partition_tuples, list)
        assert isinstance(partition_tuples[0], tuple), "%s is not tuple" % type(partition_tuples[0])

        part_cols = self.get_partition_columns(db_name, table_name)
        formatted_partition_tuples = []
        for part_name, part_val in partition_tuples:
            part_col = match_table_column(part_name, part_cols)
            part_val = self.to_backend_literal(part_val) if (part_col and part_col.is_string_based()) else part_val
            formatted_partition_tuples.append((backtick_sandwich(part_name), part_val))
        return self._format_partition_clause(formatted_partition_tuples, sep_char=",")

    def _format_query_options(self, query_options=None):
        """Format options for Hive & Impala
        query_options: key/value pairs for session settings
        """
        if not query_options:
            return []
        assert isinstance(query_options, dict)
        return [format_hive_set_command(k, v) for k, v in query_options.items()]

    def _gen_sample_stats_sql_sample_clause(self, db_name, table_name, sample_perc=None):
        """No Query SAMPLE clause on Hadoop"""
        return

    def _get_hive_stats_table(self, db_name, table_name):
        """Instantiates HiveTableStats if required or retrieves from cache"""
        ht_id = (db_name + "_" + table_name).lower()
        if ht_id not in self._cached_hive_table_stats:
            assert self._hive_conn is not None
            self._hive_conn.refresh_cursor()
            hive_stats = HiveTableStats.construct(db_name, table_name, self._hive_conn)
            if self._no_caching:
                return hive_stats
            self._cached_hive_table_stats[ht_id] = hive_stats
        return self._cached_hive_table_stats[ht_id]

    def _get_hadoop_connection_exception_message_template(self):
        raise NotImplementedError(
            "_get_hadoop_connection_exception_message_template() is not implemented for common Hadoop class"
        )

    def _get_hive_table(self, db_name, table_name, no_cache=False):
        """Instantiates HiveTable if required or retrieves from cache"""
        ht_id = (db_name + "_" + table_name).lower()
        if ht_id not in self._cached_hive_tables or no_cache:
            hive_table = HiveTable(db_name, table_name, self._hive_conn)
            if self._no_caching:
                return hive_table
            self._cached_hive_tables[ht_id] = hive_table
        return self._cached_hive_tables[ht_id]

    def _get_query_profile(self, query_identifier=None):
        raise NotImplementedError("_get_query_profile() is not implemented for common Hadoop class")

    def _get_table_stats(self, hive_stats, as_dict=False, part_stats=False):
        raise NotImplementedError("_get_table_stats() is not implemented for common Hadoop class")

    def _invalid_identifier_character_re(self):
        return HADOOP_INVALID_IDENTIFIER_CHARS_RE

    def _legacy_column_list_to_type(self, legacy_columns):
        backend_columns: list = []
        if not legacy_columns:
            return backend_columns
        for col_name, data_type_spec, _ in legacy_columns:
            (
                data_type,
                data_length,
                precision,
                scale,
            ) = self._decode_hadoop_data_type_spec(data_type_spec)
            backend_columns.append(
                ColumnSpec(
                    ColumnDialect.HADOOP,
                    col_name,
                    data_type=data_type,
                    data_length=data_length,
                    data_precision=precision,
                    data_scale=scale,
                    nullable=None,
                    data_default=None,
                )
            )
        return backend_columns

    def _partition_clause_null_constant(self):
        raise NotImplementedError("_partition_clause_null_constant() is not implemented for common Hadoop class")
