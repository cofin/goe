# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Spark Thrift Server offload transport and connectivity canary implementations."""

from typing import TYPE_CHECKING, Optional

from goe.config import orchestration_defaults
from goe.offload.frontend_api import FRONTEND_TRACE_MODULE
from goe.offload.offload_constants import (
    DBTYPE_SPARK,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_transport_functions import (
    hs2_connection_log_message,
)
from goe.offload.offload_transport_rdbms_api import (
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
)
from goe.offload.registry import create_backend_api, create_transport_rdbms_api
from goe.offload.transport.base import (
    OffloadTransportSpark,
)
from goe.offload.transport.constants import (
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    SPARK_THRIFT_SERVER_PROPERTY_EXCLUDE_LIST,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
)
from goe.orchestration import command_steps
from goe.util.string_utils import (
    id_generator,
)

if TYPE_CHECKING:
    from goe.offload.offload_source_data import OffloadSourcePartitions


class OffloadTransportSparkThrift(OffloadTransportSpark):
    """Use Spark Thrift Server to transport data"""

    def __init__(
        self,
        offload_source_table,
        offload_target_table,
        offload_operation,
        offload_options,
        messages,
        dfs_client,
    ):
        """CONSTRUCTOR

        spark.jdbc.password is not retrievable in pure Spark SQL so remove from properties
        """
        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        assert (
            offload_options.offload_transport_spark_thrift_host and offload_options.offload_transport_spark_thrift_port
        )

        self._load_table_compression_spark_sql_settings()

        if "spark.jdbc.password" in self._spark_config_properties:
            del self._spark_config_properties["spark.jdbc.password"]

    def transport(self, partition_chunk: Optional["OffloadSourcePartitions"] = None) -> int | None:
        """Spark Thriftserver transport"""
        self._reset_transport_context()

        def step_fn():
            row_count = self._spark_thrift_import(partition_chunk)
            staged_bytes = self._check_and_log_transported_files(row_count)
            self._transport_context[TRANSPORT_CXT_BYTES] = staged_bytes
            self._transport_context[TRANSPORT_CXT_ROWS] = row_count
            self._target_table.post_transport_tasks(self._staging_file)
            return row_count

        return self._messages.offload_step(command_steps.STEP_STAGING_TRANSPORT, step_fn, execute=(not self._dry_run))

    def ping_source_rdbms(self):
        return self._verify_rdbms_connectivity()

    def _log_connection_details(self):
        self.log(
            hs2_connection_log_message(
                self._spark_thrift_host,
                self._spark_thrift_port,
                self._offload_options,
                service_name="Spark Thrift Server",
            ),
            detail=VVERBOSE,
        )

    def _get_create_temp_view_sql(
        self,
        temp_vw_name,
        rdbms_source_query,
        spark_api,
        custom_schema_clause=None,
        connectivity_test_only=False,
    ):
        """Generate text for a Spark session temporary view which will contain details of where to get data from and
        how to partition the workload
        When defining the parallel chunks we set the upperBound (batch_col_max) one higher than the actual value.
        This is because Spark SQL defines the number of partitions using logic below and we always end up in the
        "else" if we tell the truth:
            val numPartitions =
                if ((upperBound - lowerBound) >= requestedPartitions) {
                    requestedPartitions
                } else {
                    upperBound - lowerBound
                }
        Unable to find a way to hook into credential API when using the thrift server

        batch_col_max is one higher than reality, see header comment
        """
        self.debug("_get_create_temp_view_sql()")

        session_init_statements = "".join(
            self._get_rdbms_session_setup_commands(for_plsql=True, escape_semi_colons=True)
        )

        if self._offload_transport_auth_using_oracle_wallet:
            rdbms_app_user_opt = ""
            rdbms_app_pass_opt = ""
        else:
            rdbms_app_user_opt = "\n  user='%s'," % self._offload_options.rdbms_app_user
            rdbms_app_pass_opt = "\n  password '%s'," % self._spark_sql_option_safe(
                self._offload_options.rdbms_app_pass
            )
        quoted_name = spark_api.enclose_identifier(temp_vw_name)
        params = {
            "temp_vw_name": quoted_name,
            "rdbms_app_user_opt": rdbms_app_user_opt,
            "rdbms_app_pass_opt": rdbms_app_pass_opt,
            "rdbms_jdbc_url": self._rdbms_api.jdbc_url(),
            "rdbms_jdbc_driver_name": self._rdbms_api.jdbc_driver_name(),
            "rdbms_source_query": self._spark_sql_option_safe(rdbms_source_query),
            "batch_col": TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
            "batch_col_max": self._offload_transport_parallelism,
            "parallelism": self._offload_transport_parallelism,
            "custom_schema_clause": ((",\n " + custom_schema_clause) if custom_schema_clause else ""),
            "fetch_size": self._offload_transport_fetch_size,
            "session_init_statements": self._spark_sql_option_safe(session_init_statements),
        }
        if connectivity_test_only:
            temp_vw_sql = (
                """CREATE TEMPORARY VIEW %(temp_vw_name)s
    USING org.apache.spark.sql.jdbc
    OPTIONS (
      driver '%(rdbms_jdbc_driver_name)s',
      url '%(rdbms_jdbc_url)s',%(rdbms_app_user_opt)s%(rdbms_app_pass_opt)s
      sessionInitStatement 'BEGIN %(session_init_statements)s END\\;',
      dbtable '%(rdbms_source_query)s'
    )"""
                % params
            )
        else:
            temp_vw_sql = (
                """CREATE TEMPORARY VIEW %(temp_vw_name)s
    USING org.apache.spark.sql.jdbc
    OPTIONS (
      driver '%(rdbms_jdbc_driver_name)s',
      url '%(rdbms_jdbc_url)s',%(rdbms_app_user_opt)s%(rdbms_app_pass_opt)s
      sessionInitStatement 'BEGIN %(session_init_statements)s END\\;',
      dbtable '%(rdbms_source_query)s',
      fetchSize '%(fetch_size)s',
      partitionColumn '%(batch_col)s',
      lowerBound 0,
      upperBound %(batch_col_max)s,
      numPartitions %(parallelism)s%(custom_schema_clause)s
    )"""
                % params
            )
        return temp_vw_sql

    def _spark_thrift_import(self, partition_chunk=None):
        """Transport data using the Spark2 Thrift Server

        For stand-alone Spark we need a load db and table in the Derby DB in order to stage to cloud storage We don't want passwords on screen so request API to sub the password for ? These need to be executed together to ensure they are on the same cursor otherwise the temporary view disappears. Drop the Spark stand alone load table
        """
        self.debug("_spark_thrift_import(%s, %s)" % (self._spark_thrift_host, self._spark_thrift_port))
        self._log_connection_details()

        if self._nothing_to_do(partition_chunk):
            return 0

        self._refresh_rdbms_action()
        id_str = id_generator()
        rows_imported = None

        temp_vw_name = "goe_%s_%s_%s_jdbc_vw" % (
            self._rdbms_owner.lower(),
            self._rdbms_table_name.lower(),
            id_str,
        )
        hive_sql_projection = "\n,      ".join(_.name for _ in self._rdbms_columns)
        split_row_source_by = self._get_transport_split_type(partition_chunk)
        id_range_column = self._get_id_column_for_range_splitting()
        split_row_source_by, id_col_min, id_col_max = self._get_id_range(
            split_row_source_by, id_range_column, partition_chunk
        )
        rdbms_source_query = self._get_spark_jdbc_query_text(
            split_row_source_by,
            partition_chunk,
            sql_comment=self._rdbms_action,
            id_col_min=id_col_min,
            id_col_max=id_col_max,
        )
        custom_schema_clause = self._column_type_read_remappings()

        spark_api = create_backend_api(DBTYPE_SPARK, self._offload_options, self._messages, dry_run=self._dry_run)

        temp_vw_sql = self._get_create_temp_view_sql(
            temp_vw_name,
            rdbms_source_query,
            spark_api,
            custom_schema_clause=custom_schema_clause,
        )

        ins_sql = """INSERT INTO %(load_db)s.%(table_name)s
SELECT %(hive_projection)s
FROM   %(temp_vw_name)s""" % {
            "temp_vw_name": spark_api.enclose_identifier(temp_vw_name),
            "load_db": spark_api.enclose_identifier(self._load_db_name),
            "table_name": spark_api.enclose_identifier(self._load_table_name),
            "hive_projection": hive_sql_projection,
        }

        if self._standalone_spark():
            self.log("%s: START Prepare Spark load table" % self._str_time(), detail=VVERBOSE)
            if not spark_api.database_exists(self._load_db_name):
                spark_api.create_database(self._load_db_name)
            if spark_api.table_exists(self._load_db_name, self._load_table_name):
                spark_api.drop_table(self._load_db_name, self._load_table_name)
            spark_columns = [
                spark_api.from_canonical_column(_) for _ in self._staging_file.get_canonical_staging_columns()
            ]
            spark_api.create_table(
                self._load_db_name,
                self._load_table_name,
                spark_columns,
                None,
                storage_format=self._staging_format,
                location=self._target_table.get_staging_table_location(),
                external=True,
            )
            self.log("%s: END Prepare Spark load table" % self._str_time(), detail=VVERBOSE)

        query_options = self._spark_properties_thrift_server_exclusions()

        hive_jdbc_pass_clause = "password '%s'" % self._spark_sql_option_safe(self._offload_options.rdbms_app_pass)

        self._start_validation_polling_thread()

        transport_sqls = [temp_vw_sql, ins_sql]
        spark_api.execute_ddl(
            transport_sqls,
            query_options=query_options,
            log_level=VERBOSE,
            no_log_items={"item": hive_jdbc_pass_clause, "sub": "password '?'"},
        )

        self._stop_validation_polling_thread()

        if not self._dry_run:
            rows_imported = self._rdbms_api.log_sql_stats(
                self._rdbms_module,
                self._rdbms_action,
                self._drain_validation_polling_thread_queue(),
                validation_polling_interval=self._validation_polling_interval,
            )

        if self._standalone_spark() and not self._preserve_load_table:
            self.log("%s: START Remove Spark load table" % self._str_time(), detail=VVERBOSE)
            spark_api.drop_table(self._load_db_name, self._load_table_name)
            self.log("%s: END Remove Spark load table" % self._str_time(), detail=VVERBOSE)

        self._check_rows_imported(rows_imported)
        return rows_imported

    def _spark_properties_thrift_server_exclusions(self, with_warnings=True):
        """In truth many settings are ignored but we'll still go through the motions as some, compression for example, do work Remove any properties we know to be incompatible with the Thrift Server"""
        query_options = {}
        if self._spark_config_properties:
            if bool([_ for _ in self._spark_config_properties if "memory" in _.lower()]) and with_warnings:
                self._messages.warning("Memory configuration overrides are ignored when using Thrift Server")
            for property_name in [
                _ for _ in self._spark_config_properties if _ not in SPARK_THRIFT_SERVER_PROPERTY_EXCLUDE_LIST
            ]:
                query_options[property_name] = self._spark_config_properties[property_name]
        return query_options

    def _verify_rdbms_connectivity(self):
        """Use a simple canary query for verification test

        Do not log temp_vw_sql - it may contain a password
        """
        rdbms_source_query = "(%s) v" % self._rdbms_api.get_rdbms_canary_query()
        temp_vw_name = "goe_canary_jdbc_vw"
        spark_api = create_backend_api(DBTYPE_SPARK, self._offload_options, self._messages, dry_run=self._dry_run)
        temp_vw_sql = self._get_create_temp_view_sql(
            temp_vw_name, rdbms_source_query, spark_api, connectivity_test_only=True
        )
        hive_jdbc_pass_clause = "password '%s'" % self._spark_sql_option_safe(self._offload_options.rdbms_app_pass)
        test_sql = "SELECT COUNT(*) FROM %s" % temp_vw_name
        query_options = self._spark_properties_thrift_server_exclusions(with_warnings=False)
        spark_api.execute_ddl(
            temp_vw_sql,
            query_options=query_options,
            log_level=VVERBOSE,
            no_log_items={"item": hive_jdbc_pass_clause, "sub": "password '?'"},
        )
        row = spark_api.execute_query_fetch_one(test_sql, log_level=VERBOSE)
        return True if row[0] == 1 else False


class OffloadTransportSparkThriftCanary(OffloadTransportSparkThrift):
    """Validate Spark Thrift Server connectivity"""

    def __init__(self, offload_options, messages):
        """CONSTRUCTOR
        This does not call up the stack to parent constructor because we only want a subset of functionality

        The canary is unaware of any tables
        """
        assert offload_options.offload_transport_spark_thrift_host
        assert offload_options.offload_transport_spark_thrift_port
        self._offload_options = offload_options
        self._messages = messages
        self._dry_run = False

        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT

        self._create_basic_connectivity_attributes(offload_options)

        self._offload_transport_consistent_read = orchestration_defaults.bool_option_from_string(
            "OFFLOAD_TRANSPORT_CONSISTENT_READ",
            orchestration_defaults.offload_transport_consistent_read_default(),
        )
        self._offload_transport_fetch_size = orchestration_defaults.offload_transport_fetch_size_default()
        self._offload_transport_jvm_overrides = orchestration_defaults.offload_transport_spark_overrides_default()
        self._offload_transport_queue_name = orchestration_defaults.offload_transport_spark_queue_name_default()
        self._offload_transport_parallelism = 1
        self._validation_polling_interval = (
            orchestration_defaults.offload_transport_validation_polling_interval_default()
        )
        self._spark_config_properties = self._prepare_spark_config_properties(
            orchestration_defaults.offload_transport_spark_properties_default()
        )

        self._rdbms_api = create_transport_rdbms_api(
            "dummy_owner",
            "dummy_table",
            self._offload_options,
            self._messages,
            dry_run=self._dry_run,
        )

        self._rdbms_module = FRONTEND_TRACE_MODULE
        self._rdbms_action = self._rdbms_api.generate_transport_action()

        self._target_table = None
        self._rdbms_table = None
        self._staging_format = None

    def ping_source_rdbms(self):
        return self._verify_rdbms_connectivity()
