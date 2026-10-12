# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Base OffloadTransport and OffloadTransportSpark classes and shared helpers."""

import json
import os
import re
import traceback
from abc import ABCMeta, abstractmethod
from datetime import datetime
from socket import gethostname
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Optional

from goe.filesystem.goe_dfs import DFS_TYPE_FILE
from goe.offload.column_metadata import match_table_column
from goe.offload.factory.offload_transport_rdbms_api_factory import (
    offload_transport_rdbms_api_factory,
)
from goe.offload.factory.staging_file_factory import staging_file_factory
from goe.offload.frontend_api import FRONTEND_TRACE_MODULE
from goe.offload.offload_constants import (
    DBTYPE_ORACLE,
    DBTYPE_SYNAPSE,
    FILE_STORAGE_FORMAT_AVRO,
    HADOOP_BASED_BACKEND_DISTRIBUTIONS,
    OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED,
)
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_transport_functions import (
    credential_provider_path_jvm_override,
    run_os_cmd,
    running_as_same_user_and_host,
    scp_to_cmd,
    ssh_cmd_prefix,
)
from goe.offload.offload_transport_rdbms_api import (
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_NATIVE_RANGE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
)
from goe.offload.offload_xform_functions import apply_transformation
from goe.offload.operation.data_type_controls import char_semantics_override_map
from goe.offload.spark.pyspark_literal import PysparkLiteral
from goe.offload.transport.constants import (
    GOE_LISTENER_JAR,
    GOE_LISTENER_NAME,
    MISSING_ROWS_IMPORTED_WARNING,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_METHOD_SQOOP,
    OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY,
    OFFLOAD_TRANSPORT_SPARK_METHODS,
    OFFLOAD_TRANSPORT_SQOOP_METHODS,
    POLLING_VALIDATION_TEXT,
    SPARK_LOG_ROW_COUNT_PATTERN,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
    YARN_TRANSPORT_NAME,
)
from goe.util.misc_functions import (
    ansi_c_string_safe,
    bytes_to_human_size,
    get_os_username,
    get_temp_path,
)
from goe.util.polling_thread import PollingThread

if TYPE_CHECKING:
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.column_metadata import ColumnMetadataInterface
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_data import OffloadSourcePartitions
    from goe.offload.offload_source_table import OffloadSourceTableInterface


class OffloadTransportException(Exception):
    pass


def derive_rest_api_verify_value_from_url(url):
    """Define whether to verify SSL certificates:
    False: Use SSL but no verification
    None: No SSL
    """
    if url and url[:6] == "https:":
        return False
    return None


def convert_nans_to_nulls(offload_target_table, offload_operation):
    """If the backend does not support NaN values and the --allow-floating-point-conversions parameter is set,
    we must convert any 'NaN','Infinity','-Infinity' values in RDBMS nan capable columns to NULL
    """
    return bool(not offload_target_table.nan_supported() and offload_operation.allow_floating_point_conversions)


def get_offload_transport_value(
    offload_transport_method: str,
    dedicated_value: Any,
    sqoop_specific_value: Any,
    spark_specific_value: Any,
) -> Any:
    if dedicated_value:
        return dedicated_value
    if offload_transport_method in OFFLOAD_TRANSPORT_SQOOP_METHODS and sqoop_specific_value:
        return sqoop_specific_value
    if offload_transport_method in OFFLOAD_TRANSPORT_SPARK_METHODS and spark_specific_value:
        return spark_specific_value
    return None


class OffloadTransport(metaclass=ABCMeta):
    """Interface for classes transporting data from an RDBMS frontend to storage that can be accessed by a backend.
    Overloads by different transport methods, such a Spark, Sqoop, etc
    (abstract parent class)
    """

    _offload_transport_method: Any
    _canonical_columns: list[Any] | None
    _transport_context: dict[str, Any]
    _column_transformations: dict[str, Any]
    _target_table: Any
    _rdbms_table: Any

    def __init__(
        self,
        offload_source_table: "OffloadSourceTableInterface",
        offload_target_table: "BackendTableInterface",
        offload_operation: Any,
        offload_options: Any,
        messages: "OffloadMessages",
        dfs_client: Any,
    ) -> None:
        """not decided how to deal with offload_options, below is a temporary measure Details of the source of the offload Details of the target of the offload Config relating to the transport method For a full list of properties see: http://spark.apache.org/docs/latest/configuration.html#available-properties Details relating to a load table"""
        self._offload_options = offload_options
        self._messages = messages
        self._dfs_client = dfs_client
        self._backend_dfs = self._dfs_client.backend_dfs
        self._dry_run = bool(not offload_operation.execute)
        self._rdbms_owner = offload_source_table.owner
        self._rdbms_table_name = offload_source_table.table_name
        self._rdbms_columns = offload_source_table.columns
        self._rdbms_is_iot = offload_source_table.is_iot()
        self._rdbms_partition_type = offload_source_table.partition_type
        self._rdbms_pk_cols = offload_source_table.get_primary_key_columns()
        self._fetchmany_takes_fetch_size = offload_source_table.fetchmany_takes_fetch_size()
        if offload_operation.offload_transport_snapshot:
            self._offload_transport_snapshot = offload_operation.offload_transport_snapshot
        else:
            self._offload_transport_snapshot = offload_source_table.get_current_scn()
        self._offload_by_subpartition = offload_operation.offload_by_subpartition
        self._rdbms_table = offload_source_table
        self._rdbms_offload_predicate = offload_operation.inflight_offload_predicate
        self._canonical_columns = None
        self._target = offload_options.target
        self._target_owner = offload_operation.target_owner
        self._target_db_name = offload_target_table.db_name
        self._target_table_name = offload_target_table.table_name
        self._target_table = offload_target_table
        self._staging_table_location = self._target_table.get_staging_table_location()
        self._offload_transport_consistent_read = offload_operation.offload_transport_consistent_read
        self._offload_transport_fetch_size = offload_operation.offload_transport_fetch_size
        self._offload_transport_queue_name = get_offload_transport_value(
            self._offload_transport_method,
            offload_operation.offload_transport_queue_name,
            offload_options.sqoop_queue_name,
            offload_options.offload_transport_spark_queue_name,
        )
        self._offload_transport_jvm_overrides = get_offload_transport_value(
            self._offload_transport_method,
            offload_operation.offload_transport_jvm_overrides,
            offload_options.sqoop_overrides,
            offload_options.offload_transport_spark_overrides,
        )
        self._offload_transport_parallelism = int(offload_operation.offload_transport_parallelism)
        self._validation_polling_interval = offload_operation.offload_transport_validation_polling_interval
        self._create_basic_connectivity_attributes(offload_options)
        self._transport_context: dict[str, Any] = {}
        self._spark_config_properties = self._prepare_spark_config_properties(
            offload_operation.offload_transport_spark_properties
        )
        self._bucket_hash_col = offload_operation.bucket_hash_col
        self._column_transformations: dict[str, Any] = {}
        self._unicode_string_columns_csv = offload_operation.unicode_string_columns_csv
        self._convert_nans_to_nulls = False
        self._compress_load_table = offload_operation.compress_load_table
        self._preserve_load_table = offload_operation.preserve_load_table
        self._compute_load_table_stats = offload_operation.compute_load_table_stats
        self._load_db_name = self._target_table.get_load_db_name()
        self._load_table_name = self._target_table.table_name
        self._staging_format = offload_options.offload_staging_format
        self._staging_file = staging_file_factory(
            self._load_db_name,
            self._load_table_name,
            self._staging_format,
            self._get_canonical_columns(),
            offload_options,
            bool(self._target_table and self._target_table.transport_binary_data_in_base64()),
            messages,
            dry_run=self._dry_run,
        )

        self._rdbms_api = offload_transport_rdbms_api_factory(
            self._rdbms_owner,
            self._rdbms_table_name,
            self._offload_options,
            self._messages,
            dry_run=self._dry_run,
        )

        self._rdbms_module = FRONTEND_TRACE_MODULE
        self._rdbms_action = self._rdbms_api.generate_transport_action()

    def debug(self, msg):
        self._messages.debug(msg)

    def log(self, msg, detail=None):
        self._messages.log(msg, detail=detail)

    def log_dfs_cmd(self, msg, detail=VERBOSE):
        self._messages.log("%s cmd: %s" % (self._backend_dfs, msg), detail=detail)

    def notice(self, msg):
        self._messages.notice(msg)

    def warning(self, msg):
        self._messages.warning(msg)

    def get_transport_bytes(self) -> int | None:
        """Return a dict used to pass contextual information back from transport()"""
        return self._transport_context.get(TRANSPORT_CXT_BYTES)

    def get_transport_snapshot(self) -> int | None:
        """Return RDBMS SCN applied to this operation."""
        return self._offload_transport_snapshot

    def get_staging_file(self):
        return self._staging_file

    def transport(self, partition_chunk: Optional["OffloadSourcePartitions"] = None) -> int | None:
        """Run data transport for the implemented transport method and return the number of rows transported."""

    @abstractmethod
    def ping_source_rdbms(self):
        """Test connectivity from the Offload Transport tool back to the source RDBMS"""

    def _base64_staged_columns(self):
        """Return a list of columns that should be staged as Base64.
        We drive this from the canonical type being binary because the staging schema will be string if
        we are staging in base64, which is exactly what we are doing here.
        """
        if self._target_table and self._target_table.transport_binary_data_in_base64():
            base64_columns = []
            staging_columns = self._staging_file.get_staging_columns()
            for column in [_ for _ in self._get_canonical_columns() if _.is_binary()]:
                staging_column = match_table_column(column.name, staging_columns)
                base64_columns.append(staging_column)
            return base64_columns
        return []

    def _get_canonical_columns(self):
        """Map source RDBMS columns to canonical columns so they can then be converted to staging columns"""
        if not self._canonical_columns:
            assert self._rdbms_table is not None
            assume_all_staging_columns_nullable = bool(
                self._offload_transport_method in OFFLOAD_TRANSPORT_SQOOP_METHODS
            )
            char_semantics_map = char_semantics_override_map(self._unicode_string_columns_csv, self._rdbms_columns)
            canonical_columns = []
            for tab_col in self._rdbms_columns:
                canonical_column = self._rdbms_table.to_canonical_column(tab_col)
                if assume_all_staging_columns_nullable:
                    canonical_column.nullable = True
                if tab_col.name in char_semantics_map:
                    canonical_column.char_semantics = char_semantics_map[tab_col.name]
                canonical_columns.append(canonical_column)
            self._canonical_columns = canonical_columns
        return self._canonical_columns

    def _create_basic_connectivity_attributes(self, offload_options):
        self._offload_transport_auth_using_oracle_wallet = offload_options.offload_transport_auth_using_oracle_wallet
        self._offload_transport_cmd_host = offload_options.offload_transport_cmd_host
        self._offload_transport_credential_provider_path = offload_options.offload_transport_credential_provider_path
        self._offload_transport_dsn = offload_options.offload_transport_dsn
        self._offload_transport_password_alias = offload_options.offload_transport_password_alias
        self._offload_transport_rdbms_session_parameters = (
            json.loads(offload_options.offload_transport_rdbms_session_parameters)
            if offload_options.offload_transport_rdbms_session_parameters
            else {}
        )
        self._spark_thrift_host = offload_options.offload_transport_spark_thrift_host
        self._spark_thrift_port = offload_options.offload_transport_spark_thrift_port

    def _get_transport_app_name(self, sep: str = ".", ts: bool = False, name_override: str | None = None) -> str:
        """Get a name suitable for the transport method in use.
        For most transports this will include the table name,  but some may choose to overload this
        If adding any punctuation, stick to underscores and dots below due to Java name rules
        Using target info because it is possible to offload RDBMS to different name which would then
        have an inaccurate name if we used RDBMS names
        """
        tokens = [YARN_TRANSPORT_NAME]
        if name_override:
            tokens.append(name_override)
        else:
            tokens.extend([self._target_db_name.lower(), self._load_table_name.lower()])
        if ts:
            tokens.append(self._str_time(name_safe=True))
        return sep.join(tokens)

    def _nothing_to_do(self, partition_chunk):
        """If partition_chunk is None then we are offloading everything
        If partition_chunk is of type OffloadSourcePartitions but with no partitions then there's nothing to do
        """
        if partition_chunk and partition_chunk.count() == 0:
            self.log("No partitions to export to Hadoop")
            return True
        return False

    def _prepare_spark_config_properties(self, offload_transport_spark_properties):
        spark_config_properties = {}
        if offload_transport_spark_properties:
            spark_config_properties = json.loads(offload_transport_spark_properties)
        if not self._offload_transport_password_alias:
            spark_config_properties.update({"spark.jdbc.password": self._offload_options.rdbms_app_pass})
        return spark_config_properties

    def _reset_transport_context(self):
        self._transport_context = {
            TRANSPORT_CXT_BYTES: None,
            TRANSPORT_CXT_ROWS: None,
        }

    def _ssh_cmd_prefix(self, host=None):
        """Many calls to ssh_cmd_prefix() in this class use std inputs therefore abstract in this method"""
        host = host or self._offload_transport_cmd_host
        return ssh_cmd_prefix(self._offload_options.offload_transport_user, host)

    def _ssh_cli_safe_value(self, cmd_option_string):
        """If we are invoking Sqoop via SSH then we need extra protection for special characters on the command line
        Without SSH the protection added by subprocess module is sufficient
        """
        if self._ssh_cmd_prefix():
            return ansi_c_string_safe(cmd_option_string)
        return cmd_option_string

    def _spark_sql_option_safe(self, opt_val):
        """options in spark sql are wrapped in single quotes and need protecting"""
        return opt_val.replace("'", "\\'") if opt_val else opt_val

    def _str_time(self, name_safe=False):
        if name_safe:
            return datetime.now().strftime("%Y%m%d%H%M%S")
        return str(datetime.now().replace(microsecond=0))

    def _run_os_cmd(self, cmd, optional=False, no_log_items=[]):
        """Run an os command and:
          - Throw an exception if the return code is non-zero (and optional=False)
          - Put a dot on stdout for each line logged to give the impression of progress
          - Logs all command output at VVERBOSE level
        silent: No stdout unless vverbose is requested
        """
        return run_os_cmd(
            cmd,
            self._messages,
            self._offload_options,
            dry_run=self._dry_run,
            optional=optional,
            silent=bool(self._offload_options.suppress_stdout),
            no_log_items=no_log_items,
        )

    def _refresh_rdbms_action(self):
        self._rdbms_action = self._rdbms_api.generate_transport_action()

    def _get_max_ts_scale(self):
        if self._target_table and self._target_table:
            return min(
                self._target_table.max_datetime_scale(),
                self._rdbms_table.max_datetime_scale(),
            )
        return None

    def _get_rdbms_session_setup_commands(
        self,
        include_fixed_sqoop=True,
        for_plsql=False,
        include_semi_colons=False,
        escape_semi_colons=False,
    ):
        max_ts_scale = self._get_max_ts_scale()
        return self._rdbms_api.get_rdbms_session_setup_commands(
            self._rdbms_module,
            self._rdbms_action,
            self._offload_transport_rdbms_session_parameters,
            include_fixed_sqoop=include_fixed_sqoop,
            for_plsql=for_plsql,
            include_semi_colons=include_semi_colons,
            escape_semi_colons=escape_semi_colons,
            max_ts_scale=max_ts_scale,
        )

    def _check_rows_imported(self, rows_imported):
        """Log a warning if we weren't able to identify the number of rows imported
        the main benefit to this is being able to check for the warning during automated tests
        """
        if rows_imported is None and not self._dry_run:
            self._messages.warning(MISSING_ROWS_IMPORTED_WARNING)

    def _remote_copy_transport_control_file(self, options_file_local_path, target_host, prefix="", suffix=""):
        """Copies a control file to Offload Transport host which will be used to run a command.
        If SSH short-circuit is in play then no copy is made, we just return the name of the local file.
        Returns commands to be used to remove the files, we do this because the control files can contain
        sensitive information so we want to clean them up even though they are in /tmp.

        Copy the control file to the target host
        """
        ssh_user = self._offload_options.offload_transport_user
        self.debug("_remote_copy_transport_control_file(%s, %s, %s)" % (options_file_local_path, ssh_user, target_host))
        rm_commands = [["rm", "-f", options_file_local_path]]
        if running_as_same_user_and_host(ssh_user, target_host):
            self.log(
                "Local host (%s@%s) and remote host (%s@%s) are the same therefore no file copy required"
                % (get_os_username(), gethostname(), ssh_user, target_host),
                detail=VVERBOSE,
            )
            options_file_remote_path = options_file_local_path
        else:
            options_file_remote_path = get_temp_path(prefix=prefix, suffix=suffix)
            self.log(
                "Copying local file (%s) to remote (%s)" % (options_file_local_path, options_file_remote_path),
                detail=VVERBOSE,
            )
            scp_cmd = scp_to_cmd(ssh_user, target_host, options_file_local_path, options_file_remote_path)
            self._run_os_cmd(scp_cmd)
            rm_commands.append(ssh_cmd_prefix(ssh_user, target_host) + ["rm", "-f", options_file_remote_path])
        return rm_commands, options_file_remote_path

    def _remote_copy_transport_file(self, local_path: str, target_host: str) -> str:
        """Copies a file required by Offload Transport to a remote host.
        If SSH short-circuit is in play then no copy is made, we just return the name of the local file.
        No effort is made to remove the remote file, this is because we put the file in /tmp and we could have a
        situation where concurrent offloads want to use the same file, removing it could cause problems. Copying
        the file to a unique name just so we can remove it seems overkill when the file is in /tmp anyway.
        TODO NJ@2021-08-23 This is very similar to _remote_copy_transport_control_file() but different enough
             to not want to destabilise _remote_copy_transport_control_file() for a patch release. We probably
             want to revisit this to try and merge the methods.

        Copy the file to the target host
        """
        ssh_user = self._offload_options.offload_transport_user
        self.debug("_remote_copy_transport_file(%s, %s, %s)" % (local_path, ssh_user, target_host))
        if running_as_same_user_and_host(ssh_user, target_host):
            self.log(
                "Local host (%s@%s) and remote host (%s@%s) are the same therefore no file copy required"
                % (get_os_username(), gethostname(), ssh_user, target_host),
                detail=VVERBOSE,
            )
            remote_path = local_path
        else:
            remote_name = os.path.basename(local_path)
            remote_path = os.path.join("/tmp", remote_name)
            self.log(
                "Copying local file (%s) to remote (%s)" % (local_path, remote_path),
                detail=VVERBOSE,
            )
            scp_cmd = scp_to_cmd(ssh_user, target_host, local_path, remote_path)
            self._run_os_cmd(scp_cmd)
        return remote_path

    def _remote_copy_transport_files(self, local_paths: list, target_host: str) -> list:
        """Calls _remote_copy_transport_file() for all files in a list and returns new list of paths."""
        remote_paths = []
        for local_path in local_paths:
            if local_path:
                remote_paths.append(self._remote_copy_transport_file(local_path, target_host))
        return remote_paths

    def _remote_copy_transport_file_csv(self, local_path_csv: str, target_host: str) -> str:
        """Calls _remote_copy_transport_files() for all file paths in a CSV and returns new list of paths."""
        if not local_path_csv:
            return local_path_csv
        remote_files = self._remote_copy_transport_files(local_path_csv.split(","), self._offload_transport_cmd_host)
        return ",".join(remote_files)

    def _spark_listener_included_in_config(self):
        """Used to get truthy True when extra Spark listeners are configured.
        Search is case-insensitive but returns the config name in correct case.
        """
        for k, v in self._spark_config_properties.items():
            if k.lower() == "spark.extralisteners" and isinstance(v, str) and GOE_LISTENER_NAME in v:
                self.log("%s configured: %s: %s" % (GOE_LISTENER_NAME, k, v), detail=VVERBOSE)
                return k
        return None

    def _credential_provider_path_jvm_override(self):
        return credential_provider_path_jvm_override(self._offload_transport_credential_provider_path)

    def _get_mod_column(self) -> str:
        """Pick a column suitable for MOD splitting

        Return any column
        """
        if self._bucket_hash_col:
            return self._bucket_hash_col
        if self._rdbms_pk_cols:
            return self._rdbms_pk_cols[0]
        return self._rdbms_columns[0].name

    def _get_transport_row_source_query(
        self,
        partition_by: str,
        partition_chunk: Any = None,
        pad: Any = None,
        id_col_min: Any = None,
        id_col_max: Any = None,
    ) -> str:
        assert self._rdbms_table is not None
        if self._rdbms_offload_predicate:
            self.log(
                "Offloading with offload predicate:\n%s" % str(self._rdbms_offload_predicate),
                detail=VVERBOSE,
            )
        predicate_offload_clause = self._rdbms_table.predicate_to_where_clause(self._rdbms_offload_predicate)
        mod_column = self._get_mod_column()
        return self._rdbms_api.get_transport_row_source_query(
            partition_by,
            self._rdbms_table,
            self._offload_transport_consistent_read,
            self._offload_transport_snapshot,
            self._offload_transport_parallelism,
            self._offload_by_subpartition,
            mod_column,
            predicate_offload_clause,
            partition_chunk=partition_chunk,
            pad=pad,
            id_col_min=id_col_min,
            id_col_max=id_col_max,
        )

    def _get_spark_jdbc_query_text(
        self,
        split_type: str,
        partition_chunk: Any,
        sql_comment: Any = None,
        id_col_min: Any = None,
        id_col_max: Any = None,
    ) -> str:
        """Adds an outer query around the row source query produced by get_transport_row_source_query."""
        assert self._rdbms_table is not None
        self.debug(
            "_get_spark_jdbc_query_text(%s, %s, %s)"
            % (TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN, split_type, sql_comment)
        )
        colexpressions, colnames = self._build_offload_query_lists(for_spark=True)
        rdbms_sql_projection = self._sql_projection_from_offload_query_expression_list(
            colexpressions,
            colnames,
            extra_cols=[TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN],
        )
        row_source_subquery = self._get_transport_row_source_query(
            split_type,
            partition_chunk=partition_chunk,
            pad=6,
            id_col_min=id_col_min,
            id_col_max=id_col_max,
        )
        rdbms_source_query = """(SELECT %(row_source_hint)s%(sql_comment)s %(rdbms_projection)s
FROM (%(row_source_subquery)s) %(table_alias)s) v2""" % {
            "row_source_subquery": row_source_subquery,
            "rdbms_projection": rdbms_sql_projection,
            "row_source_hint": self._rdbms_api.get_transport_row_source_query_hint_block(),
            "sql_comment": f" /* {sql_comment} */" if sql_comment else "",
            "table_alias": self._rdbms_table.enclose_identifier(self._rdbms_table_name),
        }
        return rdbms_source_query

    def _get_transport_split_type(self, partition_chunk: Any, native_range_split_available: bool = False) -> str:
        assert self._rdbms_table is not None
        predicate_offload_clause = self._rdbms_table.predicate_to_where_clause(self._rdbms_offload_predicate)
        (
            split_row_source_by,
            tuned_parallelism,
        ) = self._rdbms_api.get_transport_split_type(
            partition_chunk,
            self._rdbms_table,
            self._offload_transport_parallelism,
            self._rdbms_partition_type,
            self._offload_by_subpartition,
            predicate_offload_clause,
            native_range_split_available=native_range_split_available,
        )
        if tuned_parallelism and tuned_parallelism != self._offload_transport_parallelism:
            self.notice(
                f"Overriding transport parallelism: {self._offload_transport_parallelism} -> {tuned_parallelism}"
            )
            self._offload_transport_parallelism = tuned_parallelism
        return split_row_source_by

    def _build_offload_query_lists(self, convert_expressions_on_rdbms_side=None, for_spark=False, for_qi=False):
        """Returns a tuple containing:
        A list of column expressions to build an RDBMS projection.
        A list of column names for the projection (useful for aliases if above has anonymous CAST()s),
          this list is the names of the staging columns rather than the original source RDBMS columns.
          Nearly always the same but sometimes not.
        """
        assert self._rdbms_table is not None
        self.debug("_build_offload_query_lists()")
        colnames, colexpressions = [], []
        staging_columns = self._staging_file.get_staging_columns()
        if convert_expressions_on_rdbms_side is None:
            assert self._target_table is not None
            convert_expressions_on_rdbms_side = bool(self._target_table.backend_type() == DBTYPE_SYNAPSE)
        for rdbms_col in self._rdbms_columns:
            cast_column = apply_transformation(
                self._column_transformations,
                rdbms_col,
                self._rdbms_table,
                self._messages,
            )
            staging_column = match_table_column(rdbms_col.name, staging_columns)
            assert staging_column is not None

            colnames.append(staging_column.staging_file_column_name)

            cast_column = cast_column or self._rdbms_table.enclose_identifier(rdbms_col.name)

            cast_column = self._rdbms_api.get_rdbms_query_cast(
                cast_column,
                rdbms_col,
                staging_column,
                self._get_max_ts_scale(),
                convert_expressions_on_rdbms_side=convert_expressions_on_rdbms_side,
                for_spark=for_spark,
                for_qi=for_qi,
                nan_values_as_null=self._convert_nans_to_nulls,
            )
            colexpressions.append(cast_column)

        return colexpressions, colnames

    def _sql_projection_from_offload_query_expression_list(
        self, colexpressions, colnames, no_newlines=False, extra_cols=[]
    ):
        """Function for formatted results of _build_offload_query_lists() into a SQL projection"""
        if extra_cols:
            colexpressions = colexpressions + extra_cols
            colnames = colnames + extra_cols
        if no_newlines:
            sql_projection = ",".join(['%s "%s"' % (expr, cname) for expr, cname in zip(colexpressions, colnames)])
        else:
            max_expr_len = max(len(_) for _ in colexpressions)
            project_pattern = "%-" + str(max_expr_len or 32) + 's AS "%s"'
            sql_projection = "\n,      ".join(
                [project_pattern % (expr, cname) for expr, cname in zip(colexpressions, colnames)]
            )
        return sql_projection

    def _offload_transport_type_remappings(self, return_as_list=True, remap_sep=" "):
        """Returns a list or string containing a parameter and values, or an empty list/string:
        Sqoop:
            ['--map-column-java', 'a value for --map-column-java that maps columns appropriately']
        Spark:
            ['customSchema', 'a value for customSchema that maps columns appropriately']
        """
        assert self._offload_transport_method in (
            OFFLOAD_TRANSPORT_METHOD_SQOOP,
            OFFLOAD_TRANSPORT_METHOD_SQOOP_BY_QUERY,
            OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
            OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
            OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
            OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
        ), f"Transport method {self._offload_transport_method} should not reach this code"

        remap = []
        for col in self._staging_file.get_staging_columns():
            java_primitive = self._staging_file.get_java_primitive(col)
            if java_primitive:
                remap.append((col.staging_file_column_name, java_primitive))

        if remap:
            if self._offload_transport_method in OFFLOAD_TRANSPORT_SQOOP_METHODS:
                remap_strings = ",".join("%s=%s" % (col_name, remap_type) for col_name, remap_type in remap)
                remap_prefix = "--map-column-java"
            elif self._offload_transport_method in OFFLOAD_TRANSPORT_SPARK_METHODS:
                remap_strings = "'%s'" % ",".join("%s %s" % (col_name, remap_type) for col_name, remap_type in remap)
                remap_prefix = "customSchema"
            else:
                raise NotImplementedError(
                    "_offload_transport_type_remappings: unknown remap type %s" % self._offload_transport_method
                )

            self.log(
                "Mapped staging columns to Java primitives: %s" % remap_strings,
                detail=VVERBOSE,
            )

            if return_as_list:
                return [remap_prefix, remap_strings]
            return remap_prefix + remap_sep + remap_strings
        return [] if return_as_list else ""

    def _check_and_log_transported_files(self, row_count: Any) -> int | None:
        """Check and list contents of target location.
        This interface level method assumes we can list contents via GOEDfs and is particularly useful when
        writing to cloud storage by ensuring filesystems with eventual consistency have made the files visible.
        target_uri: a file or a directory path, this method will only go one level down, we do not recurse.
        row_count: If this is 0 then we don't expect to find any files.
        Individual transport implementations may override this if it is not suitable.
        Returns the collective size in bytes of all files found.

        This logging is totally a nice-to-have and therefore we move on if it fails
        """

        def log_file_size(path: Any, uri_attribs: Any) -> int | None:
            self.log("Staged path: %s" % path, detail=VVERBOSE)
            if uri_attribs.get("length") is None:
                size_str = "Unknown"
            else:
                size_str = bytes_to_human_size(uri_attribs["length"])
            self.log("Staged size: %s" % size_str, detail=VVERBOSE)
            return uri_attribs.get("length")

        if not row_count:
            self.debug("Not logging contents of URI for row count: %s" % row_count)
            return None

        self.debug("Logging contents of URI: %s" % self._staging_table_location)
        if self._dry_run:
            return None

        try:
            total_size = 0
            for file_path in self._dfs_client.list_dir_and_wait_for_contents(self._staging_table_location):
                uri_attribs = self._dfs_client.stat(file_path)
                self.debug("%s attributes: %s" % (file_path, uri_attribs))
                file_bytes = None
                if uri_attribs["type"] == DFS_TYPE_FILE:
                    file_bytes = log_file_size(file_path, uri_attribs)
                else:
                    for sub_path in self._dfs_client.list_dir(file_path):
                        uri_attribs = self._dfs_client.stat(sub_path)
                        self.debug("%s attributes: %s" % (sub_path, uri_attribs))
                        if uri_attribs["type"] == DFS_TYPE_FILE:
                            file_bytes = log_file_size(sub_path, uri_attribs)
                if file_bytes:
                    total_size += file_bytes
            return total_size
        except Exception as exc:
            self.log(traceback.format_exc(), detail=VVERBOSE)
            self.log(str(exc), detail=VVERBOSE)
            return None


class OffloadTransportSpark(OffloadTransport, metaclass=ABCMeta):
    """Parent class for Spark methods"""

    def __init__(
        self,
        offload_source_table,
        offload_target_table,
        offload_operation,
        offload_options,
        messages,
        dfs_client,
    ):
        """CONSTRUCTOR"""
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        self._OffloadTransportSqlStatsThread = None
        self._convert_nans_to_nulls = convert_nans_to_nulls(offload_target_table, offload_operation)
        self._spark_files_csv = offload_options.offload_transport_spark_files
        self._spark_jars_csv = offload_options.offload_transport_spark_jars

    def _column_type_read_remappings(self):
        return self._offload_transport_type_remappings(return_as_list=False)

    def _standalone_spark(self) -> bool:
        return bool(self._offload_options.backend_distribution not in HADOOP_BASED_BACKEND_DISTRIBUTIONS)

    def _option_from_properties(self, option_name: Any, property_name: Any) -> list:
        """Small helper function to pluck a property value from self._spark_config_properties"""
        if property_name in self._spark_config_properties:
            return [option_name, self._spark_config_properties[property_name]]
        return []

    def _jdbc_option_clauses(self) -> str:
        jdbc_option_clauses = ""
        if self._offload_options.db_type == DBTYPE_ORACLE:
            jdbc_option_clauses = ".option('oracle.jdbc.timezoneAsRegion', 'false')"
        return jdbc_option_clauses

    def _get_id_range(self, split_row_source_by: Any, id_range_column: Any, partition_chunk: Any) -> tuple:
        assert self._rdbms_table is not None
        col_name = id_range_column if isinstance(id_range_column, str) else id_range_column.name
        predicate_offload_clause = self._rdbms_table.predicate_to_where_clause(self._rdbms_offload_predicate)
        id_col_min, id_col_max = self._rdbms_api.get_id_range(
            col_name, predicate_offload_clause, partition_chunk=partition_chunk
        )
        if id_col_min is None or id_col_max is None:
            self.log(
                f"Switching from range to mod data split due to blank values: {id_col_min} -> {id_col_max}",
                detail=VVERBOSE,
            )
            split_row_source_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD
            id_col_min = None
            id_col_max = None
        return split_row_source_by, id_col_min, id_col_max

    def _get_id_column_for_range_splitting(self) -> "ColumnMetadataInterface":
        assert self._rdbms_table is not None
        return self._rdbms_api.get_id_column_for_range_splitting(self._rdbms_table)

    def _get_pyspark_body(
        self, partition_chunk: Any = None, create_spark_context: bool = True, canary_query: Any = None
    ) -> str:
        """Return pyspark code to copy data to the load table.
        Shared by multiple sub-classes.
        When defining the parallel chunks we set the upperBound (batch_col_max) one higher than the actual value.
        This is because Spark SQL defines the number of partitions using logic below and we always end up in the
        "else" if we tell the truth:
            val numPartitions =
                if ((upperBound - lowerBound) >= requestedPartitions) {
                    requestedPartitions
                } else {
                    upperBound - lowerBound
                }
        canary_query allows us to pass in a specific test query and not use one based on an offload table

        Certain config should not be logged batch_col_max is one higher than reality, see header comment On HDP2 Livy the UTF coding is causing errors submitting the script: SyntaxError: encoding declaration in Unicode string We want UTF coding just in case we have PBO with a unicode predicate but decided to exclude line below for Livy only. In reality no-one is using Livy with GOE in the near future. We might have to revisit. Just testing connectivity and will drop out with no write of data Using saveAsTable because, unlike insertInto, it will use the column names to find the correct column positions which then allows it to skip TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN In the code below, after loading the data from the RDBMS we use select() to only project table columns and not the split column. Remove any synthetic split/partition column from the projection.
        """

        def get_password_snippet():
            """provider_path is optional because a customer may define it in their Hadoop config rather than GOE config"""
            password_python = []
            if self._offload_transport_password_alias:
                password_python.append("hconf = spark.sparkContext._jsc.hadoopConfiguration()")
                if self._offload_transport_credential_provider_path:
                    password_python.append(
                        "hconf.set('hadoop.security.credential.provider.path', '%s')"
                        % self._offload_transport_credential_provider_path
                    )
                password_python.append("pw = hconf.getPassword('%s')" % self._offload_transport_password_alias)
                password_python.append(
                    "assert pw, 'Unable to retrieve password for alias: %s'" % self._offload_transport_password_alias
                )
                password_python.append("jdbc_password = ''.join(str(pw.__getitem__(i)) for i in range(pw.__len__()))")
            else:
                password_python.append("jdbc_password = spark.conf.get('spark.jdbc.password')")
            return "\n".join(password_python)

        batch_col_min = 0
        batch_col_max = self._offload_transport_parallelism
        id_col_min = None
        id_col_max = None
        if canary_query:
            custom_schema_clause = ""
            rdbms_source_query = canary_query
            transport_app_name = "GOE Connect"
            load_db_name, load_table_name = "", ""
        else:
            split_row_source_by = self._get_transport_split_type(partition_chunk, native_range_split_available=True)
            if split_row_source_by in (
                TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
                TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_NATIVE_RANGE,
            ):
                id_range_column = self._get_id_column_for_range_splitting()
                split_row_source_by, id_col_min, id_col_max = self._get_id_range(
                    split_row_source_by, id_range_column, partition_chunk
                )

                if split_row_source_by == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_NATIVE_RANGE:
                    batch_col_min = id_col_min
                    batch_col_max = id_col_max

            custom_schema_clause = self._column_type_read_remappings()
            rdbms_source_query = self._get_spark_jdbc_query_text(
                split_row_source_by,
                partition_chunk,
                sql_comment=self._rdbms_action,
                id_col_min=id_col_min,
                id_col_max=id_col_max,
            )
            transport_app_name = self._get_transport_app_name()
            load_db_name, load_table_name = self._load_db_name, self._load_table_name

        session_init_statements = "".join(self._get_rdbms_session_setup_commands(for_plsql=True))
        session_init_statement_opt = ""
        if session_init_statements:
            session_init_statement_opt = "\n    sessionInitStatement='BEGIN %s END;'," % self._spark_sql_option_safe(
                session_init_statements
            )

        jdbc_option_clauses = self._jdbc_option_clauses()

        if self._offload_transport_auth_using_oracle_wallet:
            rdbms_app_user_opt = rdbms_app_pass_opt = password_snippet = ""
        else:
            rdbms_app_user_opt = "\n    user='%s'," % self._offload_options.rdbms_app_user
            rdbms_app_pass_opt = "\n    password=jdbc_password,"
            password_snippet = get_password_snippet()

        config_nolog = [
            "spark.jdbc.password",
            "spark.authenticate.secret",
            "spark.hadoop.fs.gs.auth.service.account.private.key",
            "spark.hadoop.fs.gs.auth.service.account.private.key.id",
            "spark.hadoop.fs.s3a.access.key",
            "spark.hadoop.fs.s3a.secret.key",
            "spark.ssl.keyPassword",
            "spark.ssl.keyStorePassword",
            "spark.ssl.trustStorePassword",
            "spark.com.goe.SparkBasicAuth.params",
        ]
        debug_conf_snippet = dedent(
            """\
                                    config_nolog = %s
                                    for kv in sorted(spark.sparkContext.getConf().getAll()):
                                        if kv[0] in config_nolog:
                                            print(kv[0], '?')
                                        else:
                                            print(kv)"""
            % repr(config_nolog)
        )

        params = {
            "load_db": load_db_name,
            "table_name": load_table_name,
            "rdbms_jdbc_url": self._rdbms_api.jdbc_url(),
            "rdbms_jdbc_driver_name": self._rdbms_api.jdbc_driver_name(),
            "rdbms_app_user_opt": rdbms_app_user_opt,
            "rdbms_app_pass_opt": rdbms_app_pass_opt,
            "get_password_snippet": password_snippet,
            "rdbms_source_query": self._spark_sql_option_safe(rdbms_source_query),
            "batch_col": TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
            "batch_col_min": PysparkLiteral.format_literal(batch_col_min),
            "batch_col_max": PysparkLiteral.format_literal(batch_col_max),
            "parallelism": self._offload_transport_parallelism,
            "custom_schema_clause": ((",\n    " + custom_schema_clause) if custom_schema_clause else ""),
            "write_format": self._staging_format,
            "uri": ("" if canary_query or not self._target_table else self._target_table.get_staging_table_location()),
            "fetch_size": self._offload_transport_fetch_size,
            "session_init_statement_opt": session_init_statement_opt,
            "debug_conf_snippet": debug_conf_snippet,
            "jdbc_option_clauses": jdbc_option_clauses,
        }

        pyspark_body = ""

        if self._offload_transport_method != OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY:
            pyspark_body += dedent(
                """\
                   # -*- coding: UTF-8 -*-
                   """
            )

        pyspark_body += dedent(
            """\
            # GOE Spark Transport
            """
        )

        if self._base64_staged_columns():
            pyspark_body += dedent(
                """\
                from pyspark.sql.functions import base64
                """
            )

        if create_spark_context:
            pyspark_body += dedent(
                """\
                                   from pyspark.sql import SparkSession
                                   spark = SparkSession.builder.appName('%(app_name)s')%(hive_support)s.getOrCreate()
                                   """
            ) % {
                "app_name": transport_app_name,
                "hive_support": ("" if self._standalone_spark() else ".enableHiveSupport()"),
            }

        if canary_query:
            pyspark_body += (
                dedent(
                    """\
                %(get_password_snippet)s
                df = spark.read.format('jdbc').options(
                    driver='%(rdbms_jdbc_driver_name)s',
                    url='%(rdbms_jdbc_url)s',%(rdbms_app_user_opt)s%(rdbms_app_pass_opt)s%(session_init_statement_opt)s
                    dbtable=\"\"\"%(rdbms_source_query)s\"\"\",
                )%(jdbc_option_clauses)s.load().show()
                """
                )
                % params
            )
            return pyspark_body

        pyspark_body += (
            dedent(
                """\
            %(debug_conf_snippet)s
            %(get_password_snippet)s
            df = spark.read.format('jdbc').options(
                driver='%(rdbms_jdbc_driver_name)s',
                url='%(rdbms_jdbc_url)s',%(rdbms_app_user_opt)s%(rdbms_app_pass_opt)s%(session_init_statement_opt)s
                dbtable=\"\"\"%(rdbms_source_query)s\"\"\",
                fetchSize=%(fetch_size)s,
                partitionColumn='%(batch_col)s',
                lowerBound=%(batch_col_min)s,
                upperBound=%(batch_col_max)s,
                numPartitions=%(parallelism)s%(custom_schema_clause)s
            )%(jdbc_option_clauses)s.load()
            df.printSchema()
            """
            )
            % params
        )

        if self._base64_staged_columns():

            def proj_col(col_name):
                if match_table_column(col_name, self._base64_staged_columns()):
                    return "base64(df.%(col)s).alias('%(col)s')" % {"col": col_name}
                return "'%s'" % col_name

            pyspark_body += dedent(
                """\
            projection = [%s]
            """
            ) % ",".join(proj_col(_.name) for _ in self._rdbms_columns)
        else:
            pyspark_body += (
                dedent(
                    """\
            projection = [_ for _ in df.columns if _.upper() != '%(batch_col)s'.upper()]
            """
                )
                % params
            )

        if self._standalone_spark():
            pyspark_body += (
                dedent(
                    """\
            df.select(projection).write.format('%(write_format)s').save('%(uri)s')
            """
                )
                % params
            )
        else:
            pyspark_body += (
                dedent(
                    """\
            df.select(projection).write.mode('append').format('hive').saveAsTable('`%(load_db)s`.`%(table_name)s`')
            """
                )
                % params
            )
        return pyspark_body

    def _get_rows_imported_from_spark_log(self, spark_log_text):
        """Scrape spark_log_text searching for rows imported information

        Now look for the row count marker
        """
        self.debug("_get_rows_imported_from_spark_log()")
        if not spark_log_text:
            return None
        assert isinstance(spark_log_text, str), f"{type(spark_log_text)} is not str"
        m = re.findall(SPARK_LOG_ROW_COUNT_PATTERN, spark_log_text, re.IGNORECASE | re.MULTILINE)
        if m:
            self.log(
                f"Found {len(m)} recordsWritten matches in Spark log: {m!s}",
                detail=VVERBOSE,
            )
            records_written = sum([int(_) for _ in m if _])
            self.log(
                f"Spark recordsWritten total: {records_written!s}",
                detail=VVERBOSE,
            )
            return records_written
        return None

    def _load_table_compression_pyspark_settings(self):
        """Spark is part of Hadoop"""
        if self._compress_load_table:
            codec = "snappy"
            true_or_false = "true"
        else:
            codec = "uncompressed"
            true_or_false = "false"
        prm_format = "avro" if self._staging_format == FILE_STORAGE_FORMAT_AVRO else "parquet"
        if self._standalone_spark():
            self._spark_config_properties.update({"spark.sql.%s.compression.codec" % prm_format: codec})
        else:
            self._spark_config_properties.update(
                {
                    "spark.hadoop.%s.output.codec" % prm_format: codec,
                    "spark.hadoop.hive.exec.compress.output": true_or_false,
                }
            )

    def _load_table_compression_spark_sql_settings(self):
        """These settings work whether Spark is stand-alone or part of Hadoop"""
        if self._compress_load_table:
            codec = "snappy"
            true_or_false = "true"
        else:
            codec = "uncompressed"
            true_or_false = "false"
        prm_format = "avro" if self._staging_format == FILE_STORAGE_FORMAT_AVRO else "parquet"
        self._spark_config_properties.update(
            {
                "%s.output.codec" % prm_format: codec,
                "hive.exec.compress.output": true_or_false,
            }
        )

    def _local_goe_listener_jar(self):
        """Returns path to GOETaskListener jar file in $OFFLOAD_HOME/lib directory

        We should never be missing the JAR file as it is bundled with the code that we are part of.
        """
        offload_home = os.environ.get("OFFLOAD_HOME")
        assert offload_home, "OFFLOAD_HOME is not set, environment is not correct"
        jar_path = os.path.join(offload_home, "lib", GOE_LISTENER_JAR)
        assert os.path.exists(jar_path), f"{jar_path} cannot be found, environment is not correct"
        return jar_path

    def _start_validation_polling_thread(self):
        if (
            self._validation_polling_interval
            and self._validation_polling_interval != OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED
        ):
            self._OffloadTransportSqlStatsThread = PollingThread(
                run_function=self._rdbms_api.get_offload_transport_sql_stats_function(
                    self._rdbms_module,
                    self._rdbms_action,
                    "OffloadTransportSqlStatsThread",
                ),
                name="OffloadTransportSqlStatsThread",
                interval=self._validation_polling_interval,
            )
            self._OffloadTransportSqlStatsThread.start()

    def _stop_validation_polling_thread(self):
        if self._OffloadTransportSqlStatsThread and self._OffloadTransportSqlStatsThread.is_alive():
            self._OffloadTransportSqlStatsThread.stop()

    def _drain_validation_polling_thread_queue(self):
        if self._OffloadTransportSqlStatsThread:
            if self._OffloadTransportSqlStatsThread.is_alive():
                self._stop_validation_polling_thread()
            if self._OffloadTransportSqlStatsThread.exception:
                self.log(
                    "Exception in %s polling method:\n%s"
                    % (
                        self._OffloadTransportSqlStatsThread.name,
                        self._OffloadTransportSqlStatsThread.exception,
                    ),
                    VVERBOSE,
                )
                return None
            if self._OffloadTransportSqlStatsThread.get_queue_length() == 0:
                self.log(
                    "Empty results queue from %s polling method" % self._OffloadTransportSqlStatsThread.name,
                    VVERBOSE,
                )
                return None
            self.log(
                POLLING_VALIDATION_TEXT % self._OffloadTransportSqlStatsThread.name,
                VVERBOSE,
            )
            self.debug(
                "Parsing %s snapshots taken at %s second intervals"
                % (
                    self._OffloadTransportSqlStatsThread.get_queue_length(),
                    self._OffloadTransportSqlStatsThread.interval,
                )
            )
            return self._OffloadTransportSqlStatsThread.drain_queue()
