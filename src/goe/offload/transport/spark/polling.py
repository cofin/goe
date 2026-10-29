# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared Spark transport base classes, PySpark codegen, polling thread, and helpers."""

from __future__ import annotations

import os
import queue
import re
import threading
import traceback
from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from datetime import datetime
from socket import gethostname
from textwrap import dedent
from typing import TYPE_CHECKING, Any

from goe.filesystem.goe_dfs import DFS_TYPE_FILE
from goe.observability.db import build_transport_sql_comment
from goe.observability.transport import inject_spark_trace_properties
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
from goe.offload.registry import create_staging_file, create_transport_rdbms_api
from goe.offload.schema.column_spec import match_table_column
from goe.offload.spark.pyspark_literal import PysparkLiteral
from goe.offload.transport.constants import (
    GOE_LISTENER_JAR,
    GOE_LISTENER_NAME,
    MISSING_ROWS_IMPORTED_WARNING,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OFFLOAD_TRANSPORT_SPARK_METHODS,
    POLLING_VALIDATION_TEXT,
    SPARK_LOG_ROW_COUNT_PATTERN,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
    YARN_TRANSPORT_NAME,
)
from goe.offload.transport.protocol import OffloadTransportException
from goe.serializers import decode_json, encode_json
from goe.typing import FrozenBaseStruct
from goe.util.string_utils import (
    ansi_c_string_safe,
    bytes_to_human_size,
    get_os_username,
    get_temp_path,
)

if TYPE_CHECKING:
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_data import OffloadSourcePartitions
    from goe.offload.offload_source_table import OffloadSourceTableInterface
    from goe.offload.schema.column_spec import ColumnSpec

CONFIG_NOLOG_KEYS: list[str] = [
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


def derive_rest_api_verify_value_from_url(url: str | None) -> bool | None:
    """Return False when URL uses HTTPS (disable certificate verification) or None otherwise."""
    if url and url[:6] == "https:":
        return False
    return None


def convert_nans_to_nulls(offload_target_table: Any, offload_operation: Any) -> bool:
    """Return True when NaN/Infinity values should be converted to NULL for the target table."""
    return bool(not offload_target_table.nan_supported() and offload_operation.allow_floating_point_conversions)


def get_offload_transport_value(
    offload_transport_method: str,
    dedicated_value: Any,
    spark_specific_value: Any,
) -> Any:
    """Return dedicated transport setting if set, falling back to Spark-specific value."""
    if dedicated_value:
        return dedicated_value
    if offload_transport_method in OFFLOAD_TRANSPORT_SPARK_METHODS and spark_specific_value:
        return spark_specific_value
    return None


class PySparkJobSpec(FrozenBaseStruct, frozen=True):
    """Specification for generating a PySpark JDBC extraction script."""

    app_name: str
    jdbc_url: str
    jdbc_driver_name: str
    source_query: str
    write_format: str = "parquet"
    target_uri: str = ""
    load_db: str = ""
    table_name: str = ""
    parallelism: int = 1
    fetch_size: int = 1000
    batch_col: str = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN
    batch_col_min: int | str = 0
    batch_col_max: int | str = 1
    rdbms_app_user: str | None = None
    password_alias: str | None = None
    credential_provider_path: str | None = None
    auth_using_oracle_wallet: bool = False
    session_init_statement: str = ""
    custom_schema_clause: str = ""
    jdbc_option_clauses: str = ""
    base64_columns: tuple[str, ...] = ()
    all_columns: tuple[str, ...] = ()
    standalone_spark: bool = True
    create_spark_context: bool = True
    include_utf8_header: bool = True
    canary_only: bool = False


class PySparkCodegen:
    """Generator for PySpark JDBC data transport and canary scripts."""

    @staticmethod
    def serialize_spec(spec: PySparkJobSpec) -> str:
        """Serialize a PySparkJobSpec to JSON via centralized msgspec serializer."""
        return encode_json(spec)

    @staticmethod
    def generate(spec: PySparkJobSpec) -> str:
        """Render a complete PySpark script from a PySparkJobSpec."""
        password_snippet = PySparkCodegen._build_password_snippet(spec)
        if spec.auth_using_oracle_wallet:
            rdbms_app_user_opt = ""
            rdbms_app_pass_opt = ""
            password_snippet = ""
        else:
            rdbms_app_user_opt = f"\n    user='{spec.rdbms_app_user}'," if spec.rdbms_app_user is not None else ""
            rdbms_app_pass_opt = "\n    password=jdbc_password,"

        session_init_statement_opt = ""
        if spec.session_init_statement:
            escaped_session = spec.session_init_statement.replace("'", "\\'")
            session_init_statement_opt = f"\n    sessionInitStatement='BEGIN {escaped_session} END;',"

        debug_conf_snippet = dedent(
            """\
                                    config_nolog = %s
                                    for kv in sorted(spark.sparkContext.getConf().getAll()):
                                        if kv[0] in config_nolog:
                                            print(kv[0], '?')
                                        else:
                                            print(kv)"""
            % repr(CONFIG_NOLOG_KEYS)
        )

        params = {
            "load_db": spec.load_db,
            "table_name": spec.table_name,
            "rdbms_jdbc_url": spec.jdbc_url,
            "rdbms_jdbc_driver_name": spec.jdbc_driver_name,
            "rdbms_app_user_opt": rdbms_app_user_opt,
            "rdbms_app_pass_opt": rdbms_app_pass_opt,
            "get_password_snippet": password_snippet,
            "rdbms_source_query": spec.source_query.replace("'", "\\'") if spec.source_query else "",
            "batch_col": spec.batch_col,
            "batch_col_min": PysparkLiteral.format_literal(spec.batch_col_min),
            "batch_col_max": PysparkLiteral.format_literal(spec.batch_col_max),
            "parallelism": spec.parallelism,
            "custom_schema_clause": (",\n    " + spec.custom_schema_clause) if spec.custom_schema_clause else "",
            "write_format": spec.write_format,
            "uri": "" if spec.canary_only else spec.target_uri,
            "fetch_size": spec.fetch_size,
            "session_init_statement_opt": session_init_statement_opt,
            "debug_conf_snippet": debug_conf_snippet,
            "jdbc_option_clauses": spec.jdbc_option_clauses,
        }

        pyspark_body = ""
        if spec.include_utf8_header:
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

        if spec.base64_columns:
            pyspark_body += dedent(
                """\
                from pyspark.sql.functions import base64
                """
            )

        if spec.create_spark_context:
            pyspark_body += dedent(
                """\
                                   from pyspark.sql import SparkSession
                                   spark = SparkSession.builder.appName('%(app_name)s')%(hive_support)s.getOrCreate()
                                   """
            ) % {
                "app_name": spec.app_name,
                "hive_support": "" if spec.standalone_spark else ".enableHiveSupport()",
            }

        if spec.canary_only:
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

        if spec.base64_columns:
            base64_upper = {c.upper() for c in spec.base64_columns}
            projected = [
                f"base64(df.{col_name}).alias('{col_name}')" if col_name.upper() in base64_upper else f"'{col_name}'"
                for col_name in spec.all_columns
            ]
            pyspark_body += dedent(
                """\
            projection = [%s]
            """
            ) % ",".join(projected)
        else:
            pyspark_body += (
                dedent(
                    """\
            projection = [_ for _ in df.columns if _.upper() != '%(batch_col)s'.upper()]
            """
                )
                % params
            )

        if spec.standalone_spark:
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

    @staticmethod
    def _build_password_snippet(spec: PySparkJobSpec) -> str:
        password_python: list[str] = []
        if spec.password_alias:
            password_python.append("hconf = spark.sparkContext._jsc.hadoopConfiguration()")
            if spec.credential_provider_path:
                password_python.append(
                    f"hconf.set('hadoop.security.credential.provider.path', '{spec.credential_provider_path}')"
                )
            password_python.append(f"pw = hconf.getPassword('{spec.password_alias}')")
            password_python.append(f"assert pw, 'Unable to retrieve password for alias: {spec.password_alias}'")
            password_python.append("jdbc_password = ''.join(str(pw.__getitem__(i)) for i in range(pw.__len__()))")
        else:
            password_python.append("jdbc_password = spark.conf.get('spark.jdbc.password')")
        return "\n".join(password_python)


class PollingThread(threading.Thread):
    """Background daemon thread that invokes a callable on a fixed interval and buffers results/exceptions."""

    def __init__(
        self,
        run_function: Callable[..., Any] | None = None,
        name: str | None = None,
        interval: float = 1.0,
        *,
        target: Callable[..., Any] | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        callback = run_function or target
        if not callable(callback):
            raise ValueError("PollingThread requires a callable run_function or target")
        super().__init__(name=name, daemon=True)
        self._run_function = callback
        self._call_args = args
        self._call_kwargs = kwargs or {}
        self.interval = interval
        self.event = threading.Event()
        self.exception: str | None = None
        self._queue: queue.Queue[Any] = queue.Queue()
        self._exceptions: queue.Queue[BaseException] = queue.Queue()

    def add_to_queue(self, item: Any) -> None:
        """Enqueue a polled result item."""
        self._queue.put(item)

    def drain_queue(self) -> list[Any]:
        """Drain and return all queued result items in FIFO order."""
        items: list[Any] = []
        while not self._queue.empty():
            try:
                items.append(self._queue.get(block=False))
            except queue.Empty:
                break
        return items

    def get_queue_length(self) -> int:
        """Return the approximate number of queued items."""
        return self._queue.qsize()

    def get_exceptions(self) -> list[BaseException]:
        """Return a snapshot list of captured exceptions without draining."""
        return list(self._exceptions.queue)

    def drain_exceptions(self) -> list[BaseException]:
        """Drain and return all captured exceptions."""
        items: list[BaseException] = []
        while not self._exceptions.empty():
            try:
                items.append(self._exceptions.get(block=False))
            except queue.Empty:
                break
        return items

    def DrainExceptions(self) -> list[BaseException]:
        """Alias for drain_exceptions."""
        return self.drain_exceptions()

    def run(self) -> None:
        """Execute the polling loop until stop() sets the termination event."""
        try:
            while not self.event.is_set():
                result = self._run_function(*self._call_args, **self._call_kwargs)
                if result is not None:
                    self.add_to_queue(result)
                self.event.wait(self.interval)
        except Exception as exc:
            self.exception = traceback.format_exc()
            self._exceptions.put(exc)

    def stop(self) -> None:
        """Signal the polling loop to exit and join if the thread was started."""
        self.event.set()
        if self.ident is not None and self.is_alive():
            self.join(timeout=max(1.0, float(self.interval) * 2.0))


class RdbmsTransportStatsPoller:
    """Lifecycle wrapper around PollingThread for RDBMS SQL statistics snapshots."""

    def __init__(
        self,
        rdbms_api: Any,
        rdbms_module: str,
        rdbms_action: str,
        polling_interval: float,
        messages: Any,
        thread_name: str = "OffloadTransportSqlStatsThread",
    ) -> None:
        self._rdbms_api = rdbms_api
        self._rdbms_module = rdbms_module
        self._rdbms_action = rdbms_action
        self._polling_interval = polling_interval
        self._messages = messages
        self._thread_name = thread_name
        self.thread: PollingThread | None = None

    def start(self) -> PollingThread | None:
        """Start the background SQL stats polling thread when enabled."""
        if self._polling_interval and self._polling_interval != OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED:
            self.thread = PollingThread(
                run_function=self._rdbms_api.get_offload_transport_sql_stats_function(
                    self._rdbms_module,
                    self._rdbms_action,
                    self._thread_name,
                ),
                name=self._thread_name,
                interval=self._polling_interval,
            )
            self.thread.start()
        return self.thread

    def stop(self) -> None:
        """Stop the active polling thread if running."""
        if self.thread and self.thread.is_alive():
            self.thread.stop()

    def drain(self) -> list[Any] | None:
        """Stop the polling thread and return collected snapshots, or None on error/empty."""
        if not self.thread:
            return None
        if self.thread.is_alive():
            self.stop()
        if self.thread.exception:
            self._messages.log(
                f"Exception in {self.thread.name} polling method:\n{self.thread.exception}",
                VVERBOSE,
            )
            return None
        if self.thread.get_queue_length() == 0:
            self._messages.log(
                f"Empty results queue from {self.thread.name} polling method",
                VVERBOSE,
            )
            return None
        self._messages.log(
            POLLING_VALIDATION_TEXT % self.thread.name,
            VVERBOSE,
        )
        self._messages.debug(
            f"Parsing {self.thread.get_queue_length()} snapshots taken at {self.thread.interval} second intervals"
        )
        return self.thread.drain_queue()


class TransportSplitPlanner:
    """Helper for planning RDBMS row-source split strategy and ID range bounds."""

    @staticmethod
    def resolve_id_range(
        rdbms_api: Any,
        rdbms_table: Any,
        offload_predicate: Any,
        split_row_source_by: str,
        id_range_column: Any,
        partition_chunk: Any,
        messages: Any,
    ) -> tuple[str, Any, Any]:
        """Resolve min/max ID bounds or fall back to MOD splitting when bounds are NULL."""
        col_name = id_range_column if isinstance(id_range_column, str) else id_range_column.name
        predicate_offload_clause = rdbms_table.predicate_to_where_clause(offload_predicate)
        id_col_min, id_col_max = rdbms_api.get_id_range(
            col_name, predicate_offload_clause, partition_chunk=partition_chunk
        )
        if id_col_min is None or id_col_max is None:
            messages.log(
                f"Switching from range to mod data split due to blank values: {id_col_min} -> {id_col_max}",
                detail=VVERBOSE,
            )
            return TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD, None, None
        return split_row_source_by, id_col_min, id_col_max


class SparkCommandRunner:
    """Single canonical SSH/SCP file transfer and command execution helper for Spark transports."""

    def __init__(self, ssh_user: str, run_cmd_fn: Callable[..., Any], messages: Any) -> None:
        self._ssh_user = ssh_user
        self._run_cmd_fn = run_cmd_fn
        self._messages = messages

    def scp_to_host(self, target_host: str, local_path: str, remote_path: str) -> str:
        """Copy a local file to a target host via SCP unless running as same user and host."""
        if running_as_same_user_and_host(self._ssh_user, target_host):
            self._messages.log(
                f"Local host ({get_os_username()}@{gethostname()}) and remote host ({self._ssh_user}@{target_host}) "
                "are the same therefore no file copy required",
                detail=VVERBOSE,
            )
            return local_path
        self._messages.log(
            f"Copying local file ({local_path}) to remote ({remote_path})",
            detail=VVERBOSE,
        )
        self._run_cmd_fn(scp_to_cmd(self._ssh_user, target_host, local_path, remote_path))
        return remote_path

    def scp_from_host(self, source_host: str, remote_path: str, local_path: str) -> str:
        """Copy a remote file from a source host via SCP unless running as same user and host."""
        if running_as_same_user_and_host(self._ssh_user, source_host):
            self._messages.log(
                f"Local host ({get_os_username()}@{gethostname()}) and remote host ({self._ssh_user}@{source_host}) "
                "are the same therefore no file copy required",
                detail=VVERBOSE,
            )
            return remote_path
        self._messages.log(
            f"Copying remote file ({remote_path}) to local ({local_path})",
            detail=VVERBOSE,
        )
        self._run_cmd_fn(["scp", f"{self._ssh_user}@{source_host}:{remote_path}", local_path])
        return local_path


class OffloadTransport(metaclass=ABCMeta):
    """Abstract base class for transporting data from an RDBMS frontend to backend staging."""

    _offload_transport_method: Any
    _canonical_columns: list[Any] | None
    _transport_context: dict[str, Any]
    _column_transformations: dict[str, Any]
    _target_table: Any
    _rdbms_table: Any

    def __init__(
        self,
        offload_source_table: OffloadSourceTableInterface,
        offload_target_table: BackendTableInterface,
        offload_operation: Any,
        offload_options: Any,
        messages: OffloadMessages,
        dfs_client: Any,
    ) -> None:
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
            offload_options.offload_transport_spark_queue_name,
        )
        self._offload_transport_jvm_overrides = get_offload_transport_value(
            self._offload_transport_method,
            offload_operation.offload_transport_jvm_overrides,
            offload_options.offload_transport_spark_overrides,
        )
        self._offload_transport_parallelism = int(offload_operation.offload_transport_parallelism)
        self._validation_polling_interval = offload_operation.offload_transport_validation_polling_interval
        self._create_basic_connectivity_attributes(offload_options)
        self._transport_context = {}
        self._spark_config_properties = self._prepare_spark_config_properties(
            offload_operation.offload_transport_spark_properties
        )
        self._bucket_hash_col = offload_operation.bucket_hash_col
        self._column_transformations = {}
        self._unicode_string_columns_csv = offload_operation.unicode_string_columns_csv
        self._convert_nans_to_nulls = False
        self._compress_load_table = offload_operation.compress_load_table
        self._preserve_load_table = offload_operation.preserve_load_table
        self._compute_load_table_stats = offload_operation.compute_load_table_stats
        self._load_db_name = self._target_table.get_load_db_name()
        self._load_table_name = self._target_table.table_name
        self._staging_format = offload_options.offload_staging_format
        self._staging_file = create_staging_file(
            self._load_db_name,
            self._load_table_name,
            self._staging_format,
            self._get_canonical_columns(),
            offload_options,
            bool(self._target_table and self._target_table.transport_binary_data_in_base64()),
            messages,
            dry_run=self._dry_run,
        )

        self._rdbms_api = create_transport_rdbms_api(
            self._rdbms_owner,
            self._rdbms_table_name,
            self._offload_options,
            self._messages,
            dry_run=self._dry_run,
        )

        self._rdbms_module = FRONTEND_TRACE_MODULE
        self._rdbms_action = self._rdbms_api.generate_transport_action()

    def debug(self, msg: Any) -> None:
        """Log a debug message."""
        self._messages.debug(msg)

    def log(self, msg: Any, detail: Any = None) -> None:
        """Log an informational message at the given detail level."""
        self._messages.log(msg, detail=detail)

    def log_dfs_cmd(self, msg: Any, detail: Any = VERBOSE) -> None:
        """Log a DFS command message."""
        self._messages.log("%s cmd: %s" % (self._backend_dfs, msg), detail=detail)

    def notice(self, msg: Any) -> None:
        """Log a notice message."""
        self._messages.notice(msg)

    def warning(self, msg: Any) -> None:
        """Log a warning message."""
        self._messages.warning(msg)

    def get_transport_bytes(self) -> int | None:
        """Return the number of bytes staged during transport()."""
        return self._transport_context.get(TRANSPORT_CXT_BYTES)

    def get_transport_method(self) -> str:
        """Return the transport method constant."""
        return getattr(self, "_offload_transport_method", None) or type(self).__name__

    def get_telemetry_attributes(self) -> dict[str, str | int]:
        """Return span attributes describing this transport for goe.transport.* spans."""
        attributes: dict[str, str | int] = {"goe.transport.method": self.get_transport_method()}
        parallelism = getattr(self, "_offload_transport_parallelism", None)
        if parallelism is not None:
            attributes["goe.transport.parallelism"] = int(parallelism)
        options = getattr(self, "_offload_options", None)
        staging_format = getattr(options, "offload_staging_format", None)
        if staging_format:
            attributes["goe.transport.staging_format"] = str(staging_format)
        staging_location = getattr(self, "_staging_table_location", None)
        if staging_location:
            attributes["goe.transport.staging_location"] = str(staging_location)
        snapshot = getattr(self, "_offload_transport_snapshot", None)
        if snapshot is not None:
            attributes["goe.transport.scn"] = str(snapshot)
        return attributes

    def get_transport_snapshot(self) -> int | None:
        """Return RDBMS SCN applied to this operation."""
        return self._offload_transport_snapshot

    def get_staging_file(self) -> Any:
        """Return the staging file metadata helper."""
        return self._staging_file

    def transport(self, partition_chunk: OffloadSourcePartitions | None = None) -> int | None:
        """Run data transport for the implemented transport method and return transported row count."""

    @abstractmethod
    def ping_source_rdbms(self) -> Any:
        """Test connectivity from the Offload Transport tool back to the source RDBMS."""

    def _base64_staged_columns(self) -> list[Any]:
        if self._target_table and self._target_table.transport_binary_data_in_base64():
            base64_columns = []
            staging_columns = self._staging_file.get_staging_columns()
            for column in [_ for _ in self._get_canonical_columns() if _.is_binary()]:
                staging_column = match_table_column(column.name, staging_columns)
                base64_columns.append(staging_column)
            return base64_columns
        return []

    def _get_canonical_columns(self) -> list[Any]:
        if not self._canonical_columns:
            assert self._rdbms_table is not None
            char_semantics_map = char_semantics_override_map(self._unicode_string_columns_csv, self._rdbms_columns)
            canonical_columns = []
            for tab_col in self._rdbms_columns:
                canonical_column = self._rdbms_table.to_canonical_column(tab_col)
                if tab_col.name in char_semantics_map:
                    canonical_column = canonical_column.replace(char_semantics=char_semantics_map[tab_col.name])
                canonical_columns.append(canonical_column)
            self._canonical_columns = canonical_columns
        return self._canonical_columns

    def _create_basic_connectivity_attributes(self, offload_options: Any) -> None:
        self._offload_transport_auth_using_oracle_wallet = offload_options.offload_transport_auth_using_oracle_wallet
        self._offload_transport_cmd_host = offload_options.offload_transport_cmd_host
        self._offload_transport_credential_provider_path = offload_options.offload_transport_credential_provider_path
        self._offload_transport_dsn = offload_options.offload_transport_dsn
        self._offload_transport_password_alias = offload_options.offload_transport_password_alias
        self._offload_transport_rdbms_session_parameters = (
            decode_json(offload_options.offload_transport_rdbms_session_parameters)
            if offload_options.offload_transport_rdbms_session_parameters
            else {}
        )
        self._spark_thrift_host = offload_options.offload_transport_spark_thrift_host
        self._spark_thrift_port = offload_options.offload_transport_spark_thrift_port

    def _get_transport_app_name(self, sep: str = ".", ts: bool = False, name_override: str | None = None) -> str:
        tokens = [YARN_TRANSPORT_NAME]
        if name_override:
            tokens.append(name_override)
        else:
            tokens.extend([self._target_db_name.lower(), self._load_table_name.lower()])
        if ts:
            tokens.append(self._str_time(name_safe=True))
        return sep.join(tokens)

    def _nothing_to_do(self, partition_chunk: Any) -> bool:
        if partition_chunk and partition_chunk.count() == 0:
            self.log("No partitions to export to Hadoop")
            return True
        return False

    def _prepare_spark_config_properties(self, offload_transport_spark_properties: Any) -> dict[str, Any]:
        spark_config_properties: dict[str, Any] = {}
        if offload_transport_spark_properties:
            spark_config_properties = decode_json(offload_transport_spark_properties)
        if not self._offload_transport_password_alias:
            spark_config_properties.update({"spark.jdbc.password": self._offload_options.rdbms_app_pass})
        return inject_spark_trace_properties(spark_config_properties)

    def _reset_transport_context(self) -> None:
        self._transport_context = {
            TRANSPORT_CXT_BYTES: None,
            TRANSPORT_CXT_ROWS: None,
        }

    def _ssh_cmd_prefix(self, host: str | None = None) -> list[str]:
        host = host or self._offload_transport_cmd_host
        return ssh_cmd_prefix(self._offload_options.offload_transport_user, host)

    def _ssh_cli_safe_value(self, cmd_option_string: str) -> str:
        if self._ssh_cmd_prefix():
            return ansi_c_string_safe(cmd_option_string)
        return cmd_option_string

    def _spark_sql_option_safe(self, opt_val: str | None) -> str | None:
        return opt_val.replace("'", "\\'") if opt_val else opt_val

    def _str_time(self, name_safe: bool = False) -> str:
        if name_safe:
            return datetime.now().strftime("%Y%m%d%H%M%S")
        return str(datetime.now().replace(microsecond=0))

    def _run_os_cmd(
        self,
        cmd: list[Any],
        optional: bool = False,
        no_log_items: list[Any] | None = None,
    ) -> Any:
        return run_os_cmd(
            cmd,
            self._messages,
            self._offload_options,
            dry_run=self._dry_run,
            optional=optional,
            silent=bool(self._offload_options.suppress_stdout),
            no_log_items=no_log_items or [],
        )

    def _refresh_rdbms_action(self) -> None:
        self._rdbms_action = self._rdbms_api.generate_transport_action()

    def _get_max_ts_scale(self) -> int | None:
        if self._target_table and self._rdbms_table:
            return min(
                self._target_table.max_datetime_scale(),
                self._rdbms_table.max_datetime_scale(),
            )
        return None

    def _get_rdbms_session_setup_commands(
        self,
        for_plsql: bool = False,
        include_semi_colons: bool = False,
        escape_semi_colons: bool = False,
    ) -> list[str]:
        max_ts_scale = self._get_max_ts_scale()
        return self._rdbms_api.get_rdbms_session_setup_commands(
            self._rdbms_module,
            self._rdbms_action,
            self._offload_transport_rdbms_session_parameters,
            for_plsql=for_plsql,
            include_semi_colons=include_semi_colons,
            escape_semi_colons=escape_semi_colons,
            max_ts_scale=max_ts_scale,
        )

    def _check_rows_imported(self, rows_imported: int | None) -> None:
        if rows_imported is None and not self._dry_run:
            self._messages.warning(MISSING_ROWS_IMPORTED_WARNING)

    def _remote_copy_transport_control_file(
        self,
        options_file_local_path: str,
        target_host: str,
        prefix: str = "",
        suffix: str = "",
    ) -> tuple[list[list[str]], str]:
        ssh_user = self._offload_options.offload_transport_user
        self.debug(f"_remote_copy_transport_control_file({options_file_local_path}, {ssh_user}, {target_host})")
        rm_commands = [["rm", "-f", options_file_local_path]]
        if running_as_same_user_and_host(ssh_user, target_host):
            self.log(
                f"Local host ({get_os_username()}@{gethostname()}) and remote host ({ssh_user}@{target_host}) "
                "are the same therefore no file copy required",
                detail=VVERBOSE,
            )
            options_file_remote_path = options_file_local_path
        else:
            options_file_remote_path = get_temp_path(prefix=prefix, suffix=suffix)
            self.log(
                f"Copying local file ({options_file_local_path}) to remote ({options_file_remote_path})",
                detail=VVERBOSE,
            )
            scp_cmd = scp_to_cmd(ssh_user, target_host, options_file_local_path, options_file_remote_path)
            self._run_os_cmd(scp_cmd)
            rm_commands.append(ssh_cmd_prefix(ssh_user, target_host) + ["rm", "-f", options_file_remote_path])
        return rm_commands, options_file_remote_path

    def _remote_copy_transport_file(self, local_path: str, target_host: str) -> str:
        ssh_user = self._offload_options.offload_transport_user
        self.debug(f"_remote_copy_transport_file({local_path}, {ssh_user}, {target_host})")
        if running_as_same_user_and_host(ssh_user, target_host):
            self.log(
                f"Local host ({get_os_username()}@{gethostname()}) and remote host ({ssh_user}@{target_host}) "
                "are the same therefore no file copy required",
                detail=VVERBOSE,
            )
            remote_path = local_path
        else:
            remote_name = os.path.basename(local_path)
            remote_path = os.path.join("/tmp", remote_name)
            self.log(
                f"Copying local file ({local_path}) to remote ({remote_path})",
                detail=VVERBOSE,
            )
            scp_cmd = scp_to_cmd(ssh_user, target_host, local_path, remote_path)
            self._run_os_cmd(scp_cmd)
        return remote_path

    def _remote_copy_transport_files(self, local_paths: list[str], target_host: str) -> list[str]:
        remote_paths = []
        for local_path in local_paths:
            if local_path:
                remote_paths.append(self._remote_copy_transport_file(local_path, target_host))
        return remote_paths

    def _remote_copy_transport_file_csv(self, local_path_csv: str, target_host: str) -> str:
        if not local_path_csv:
            return local_path_csv
        remote_files = self._remote_copy_transport_files(local_path_csv.split(","), self._offload_transport_cmd_host)
        return ",".join(remote_files)

    def _spark_listener_included_in_config(self) -> str | None:
        for k, v in self._spark_config_properties.items():
            if k.lower() == "spark.extralisteners" and isinstance(v, str) and GOE_LISTENER_NAME in v:
                self.log(f"{GOE_LISTENER_NAME} configured: {k}: {v}", detail=VVERBOSE)
                return k
        return None

    def _credential_provider_path_jvm_override(self) -> str | None:
        return credential_provider_path_jvm_override(self._offload_transport_credential_provider_path)

    def _get_mod_column(self) -> str:
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
                f"Offloading with offload predicate:\n{self._rdbms_offload_predicate!s}",
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
        assert self._rdbms_table is not None
        sql_comment = build_transport_sql_comment(sql_comment)
        self.debug(
            f"_get_spark_jdbc_query_text({TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN}, {split_type}, {sql_comment})"
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
        return """(SELECT %(row_source_hint)s%(sql_comment)s %(rdbms_projection)s
FROM (%(row_source_subquery)s) %(table_alias)s) v2""" % {
            "row_source_subquery": row_source_subquery,
            "rdbms_projection": rdbms_sql_projection,
            "row_source_hint": self._rdbms_api.get_transport_row_source_query_hint_block(),
            "sql_comment": f" /* {sql_comment} */" if sql_comment else "",
            "table_alias": self._rdbms_table.enclose_identifier(self._rdbms_table_name),
        }

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

    def _build_offload_query_lists(
        self,
        convert_expressions_on_rdbms_side: bool | None = None,
        for_spark: bool = False,
        for_qi: bool = False,
    ) -> tuple[list[Any], list[Any]]:
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
        self,
        colexpressions: list[Any],
        colnames: list[Any],
        no_newlines: bool = False,
        extra_cols: list[Any] | None = None,
    ) -> str:
        if extra_cols:
            colexpressions = colexpressions + extra_cols
            colnames = colnames + extra_cols
        if no_newlines:
            return ",".join(['%s "%s"' % (expr, cname) for expr, cname in zip(colexpressions, colnames)])
        max_expr_len = max(len(_) for _ in colexpressions)
        project_pattern = "%-" + str(max_expr_len or 32) + 's AS "%s"'
        return "\n,      ".join([project_pattern % (expr, cname) for expr, cname in zip(colexpressions, colnames)])

    def _offload_transport_type_remappings(self, return_as_list: bool = True, remap_sep: str = " ") -> list[str] | str:
        assert self._offload_transport_method in (
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
            if self._offload_transport_method in OFFLOAD_TRANSPORT_SPARK_METHODS:
                remap_strings = "'%s'" % ",".join("%s %s" % (col_name, remap_type) for col_name, remap_type in remap)
                remap_prefix = "customSchema"
            else:
                raise NotImplementedError(
                    f"_offload_transport_type_remappings: unknown remap type {self._offload_transport_method}"
                )

            self.log(
                f"Mapped staging columns to Java primitives: {remap_strings}",
                detail=VVERBOSE,
            )

            if return_as_list:
                return [remap_prefix, remap_strings]
            return remap_prefix + remap_sep + remap_strings
        return [] if return_as_list else ""

    def _log_staged_file_size(self, path: Any, uri_attribs: Any) -> int | None:
        self.log(f"Staged path: {path}", detail=VVERBOSE)
        size_str = "Unknown" if uri_attribs.get("length") is None else bytes_to_human_size(uri_attribs["length"])
        self.log(f"Staged size: {size_str}", detail=VVERBOSE)
        return uri_attribs.get("length")

    def _check_and_log_transported_files(self, row_count: Any) -> int | None:
        if not row_count:
            self.debug(f"Not logging contents of URI for row count: {row_count}")
            return None

        self.debug(f"Logging contents of URI: {self._staging_table_location}")
        if self._dry_run:
            return None

        try:
            total_size = 0
            for file_path in self._dfs_client.list_dir_and_wait_for_contents(self._staging_table_location):
                uri_attribs = self._dfs_client.stat(file_path)
                self.debug(f"{file_path} attributes: {uri_attribs}")
                file_bytes = None
                if uri_attribs["type"] == DFS_TYPE_FILE:
                    file_bytes = self._log_staged_file_size(file_path, uri_attribs)
                else:
                    for sub_path in self._dfs_client.list_dir(file_path):
                        uri_attribs = self._dfs_client.stat(sub_path)
                        self.debug(f"{sub_path} attributes: {uri_attribs}")
                        if uri_attribs["type"] == DFS_TYPE_FILE:
                            file_bytes = self._log_staged_file_size(sub_path, uri_attribs)
                if file_bytes:
                    total_size += file_bytes
            return total_size
        except Exception as exc:
            self.log(traceback.format_exc(), detail=VVERBOSE)
            self.log(str(exc), detail=VVERBOSE)
            return None


class OffloadTransportSpark(OffloadTransport, metaclass=ABCMeta):
    """Base class for Spark-based offload transport implementations."""

    def __init__(
        self,
        offload_source_table: Any,
        offload_target_table: Any,
        offload_operation: Any,
        offload_options: Any,
        messages: Any,
        dfs_client: Any,
    ) -> None:
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        self._OffloadTransportSqlStatsThread: PollingThread | None = None
        self._convert_nans_to_nulls = convert_nans_to_nulls(offload_target_table, offload_operation)
        self._spark_files_csv = offload_options.offload_transport_spark_files
        self._spark_jars_csv = offload_options.offload_transport_spark_jars

    def _column_type_read_remappings(self) -> list[str] | str:
        return self._offload_transport_type_remappings(return_as_list=False)

    def _standalone_spark(self) -> bool:
        return bool(self._offload_options.backend_distribution not in HADOOP_BASED_BACKEND_DISTRIBUTIONS)

    def _option_from_properties(self, option_name: Any, property_name: Any) -> list[Any]:
        if property_name in self._spark_config_properties:
            return [option_name, self._spark_config_properties[property_name]]
        return []

    def _jdbc_option_clauses(self) -> str:
        if self._offload_options.db_type == DBTYPE_ORACLE:
            return ".option('oracle.jdbc.timezoneAsRegion', 'false')"
        return ""

    def _get_id_range(
        self, split_row_source_by: Any, id_range_column: Any, partition_chunk: Any
    ) -> tuple[Any, Any, Any]:
        assert self._rdbms_table is not None
        return TransportSplitPlanner.resolve_id_range(
            self._rdbms_api,
            self._rdbms_table,
            self._rdbms_offload_predicate,
            split_row_source_by,
            id_range_column,
            partition_chunk,
            self._messages,
        )

    def _get_id_column_for_range_splitting(self) -> ColumnSpec:
        assert self._rdbms_table is not None
        return self._rdbms_api.get_id_column_for_range_splitting(self._rdbms_table)

    def _get_pyspark_body(
        self,
        partition_chunk: Any = None,
        create_spark_context: bool = True,
        canary_query: Any = None,
    ) -> str:
        batch_col_min: Any = 0
        batch_col_max: Any = self._offload_transport_parallelism
        id_col_min = None
        id_col_max = None
        if canary_query:
            custom_schema_clause = ""
            rdbms_source_query = str(canary_query)
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

            custom_schema_clause = str(self._column_type_read_remappings() or "")
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
        base64_cols = tuple(col.name for col in self._base64_staged_columns())
        all_cols = tuple(col.name for col in (self._rdbms_columns or []))
        target_uri = "" if canary_query or not self._target_table else self._target_table.get_staging_table_location()

        spec = PySparkJobSpec(
            app_name=transport_app_name,
            jdbc_url=self._rdbms_api.jdbc_url(),
            jdbc_driver_name=self._rdbms_api.jdbc_driver_name(),
            source_query=rdbms_source_query,
            write_format=str(self._staging_format or ""),
            target_uri=str(target_uri or ""),
            load_db=str(load_db_name or ""),
            table_name=str(load_table_name or ""),
            parallelism=self._offload_transport_parallelism,
            fetch_size=self._offload_transport_fetch_size,
            batch_col=TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
            batch_col_min=batch_col_min,
            batch_col_max=batch_col_max,
            rdbms_app_user=getattr(self._offload_options, "rdbms_app_user", None),
            password_alias=self._offload_transport_password_alias,
            credential_provider_path=self._offload_transport_credential_provider_path,
            auth_using_oracle_wallet=bool(self._offload_transport_auth_using_oracle_wallet),
            session_init_statement=session_init_statements,
            custom_schema_clause=custom_schema_clause,
            jdbc_option_clauses=self._jdbc_option_clauses(),
            base64_columns=base64_cols,
            all_columns=all_cols,
            standalone_spark=self._standalone_spark(),
            create_spark_context=create_spark_context,
            include_utf8_header=(self._offload_transport_method != OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY),
            canary_only=bool(canary_query),
        )
        return PySparkCodegen.generate(spec)

    def _get_rows_imported_from_spark_log(self, spark_log_text: str | None) -> int | None:
        self.debug("_get_rows_imported_from_spark_log()")
        if not spark_log_text:
            return None
        assert isinstance(spark_log_text, str), f"{type(spark_log_text)} is not str"
        matches = re.findall(SPARK_LOG_ROW_COUNT_PATTERN, spark_log_text, re.IGNORECASE | re.MULTILINE)
        if matches:
            self.log(
                f"Found {len(matches)} recordsWritten matches in Spark log: {matches!s}",
                detail=VVERBOSE,
            )
            records_written = sum([int(_) for _ in matches if _])
            self.log(
                f"Spark recordsWritten total: {records_written!s}",
                detail=VVERBOSE,
            )
            return records_written
        return None

    def _load_table_compression_pyspark_settings(self) -> None:
        if self._compress_load_table:
            codec = "snappy"
            true_or_false = "true"
        else:
            codec = "uncompressed"
            true_or_false = "false"
        prm_format = "avro" if self._staging_format == FILE_STORAGE_FORMAT_AVRO else "parquet"
        if self._standalone_spark():
            self._spark_config_properties.update({f"spark.sql.{prm_format}.compression.codec": codec})
        else:
            self._spark_config_properties.update(
                {
                    f"spark.hadoop.{prm_format}.output.codec": codec,
                    "spark.hadoop.hive.exec.compress.output": true_or_false,
                }
            )

    def _load_table_compression_spark_sql_settings(self) -> None:
        if self._compress_load_table:
            codec = "snappy"
            true_or_false = "true"
        else:
            codec = "uncompressed"
            true_or_false = "false"
        prm_format = "avro" if self._staging_format == FILE_STORAGE_FORMAT_AVRO else "parquet"
        self._spark_config_properties.update(
            {
                f"{prm_format}.output.codec": codec,
                "hive.exec.compress.output": true_or_false,
            }
        )

    def _local_goe_listener_jar(self) -> str:
        offload_home = os.environ.get("OFFLOAD_HOME")
        assert offload_home, "OFFLOAD_HOME is not set, environment is not correct"
        jar_path = os.path.join(offload_home, "lib", GOE_LISTENER_JAR)
        assert os.path.exists(jar_path), f"{jar_path} cannot be found, environment is not correct"
        return jar_path

    def _start_validation_polling_thread(self) -> None:
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

    def _stop_validation_polling_thread(self) -> None:
        if self._OffloadTransportSqlStatsThread and self._OffloadTransportSqlStatsThread.is_alive():
            self._OffloadTransportSqlStatsThread.stop()

    def _drain_validation_polling_thread_queue(self) -> list[Any] | None:
        if self._OffloadTransportSqlStatsThread:
            if self._OffloadTransportSqlStatsThread.is_alive():
                self._stop_validation_polling_thread()
            if self._OffloadTransportSqlStatsThread.exception:
                self.log(
                    f"Exception in {self._OffloadTransportSqlStatsThread.name} polling method:\n"
                    f"{self._OffloadTransportSqlStatsThread.exception}",
                    VVERBOSE,
                )
                return None
            if self._OffloadTransportSqlStatsThread.get_queue_length() == 0:
                self.log(
                    f"Empty results queue from {self._OffloadTransportSqlStatsThread.name} polling method",
                    VVERBOSE,
                )
                return None
            self.log(
                POLLING_VALIDATION_TEXT % self._OffloadTransportSqlStatsThread.name,
                VVERBOSE,
            )
            self.debug(
                f"Parsing {self._OffloadTransportSqlStatsThread.get_queue_length()} snapshots "
                f"taken at {self._OffloadTransportSqlStatsThread.interval} second intervals"
            )
            return self._OffloadTransportSqlStatsThread.drain_queue()
        return None


__all__ = [
    "CONFIG_NOLOG_KEYS",
    "OffloadTransport",
    "OffloadTransportException",
    "OffloadTransportSpark",
    "PollingThread",
    "PySparkCodegen",
    "PySparkJobSpec",
    "RdbmsTransportStatsPoller",
    "SparkCommandRunner",
    "TransportSplitPlanner",
    "convert_nans_to_nulls",
    "derive_rest_api_verify_value_from_url",
    "get_offload_transport_value",
]
