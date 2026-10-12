# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadTransportOracleApi: Library for logic/interaction with source Oracle system during offload transport."""

from contextlib import contextmanager
from itertools import groupby
from typing import TYPE_CHECKING, Any

import oracledb as cxo

from goe.observability.db import build_oracle_client_info_command
from goe.offload.column_metadata import match_table_column
from goe.offload.frontend_api import FRONTEND_TRACE_ID
from goe.offload.offload_constants import OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_source_table import OFFLOAD_PARTITION_TYPE_RANGE
from goe.offload.offload_transport_functions import (
    get_rdbms_connection_for_oracle,
    split_ranges_for_id_range,
)
from goe.offload.offload_transport_rdbms_api import (
    OFFLOAD_TRANSPORT_SQL_STATISTICS_TITLE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_NATIVE_RANGE,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
    TRANSPORT_ROW_SOURCE_QUERY_SPLIT_TYPE_TEXT,
    OffloadTransportRdbmsApiException,
    OffloadTransportRdbmsApiInterface,
)
from goe.offload.oracle.oracle_column import (
    ORACLE_TYPE_BINARY_DOUBLE,
    ORACLE_TYPE_BINARY_FLOAT,
    ORACLE_TYPE_DATE,
    ORACLE_TYPE_FLOAT,
    ORACLE_TYPE_INTERVAL_DS,
    ORACLE_TYPE_INTERVAL_YM,
    ORACLE_TYPE_NUMBER,
    ORACLE_TYPE_TIMESTAMP,
    ORACLE_TYPE_TIMESTAMP_LOCAL_TZ,
    ORACLE_TYPE_TIMESTAMP_TZ,
    ORACLE_TYPE_XMLTYPE,
)
from goe.offload.oracle.oracle_dialect import get_oracle_dialect_engine
from goe.offload.oracle.oracle_offload_source_table import (
    oracle_version_is_smart_scan_unsafe,
)
from goe.util.misc_functions import id_generator

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_data import OffloadSourcePartitions
    from goe.offload.offload_source_table import OffloadSourceTableInterface


MAX_UNION_ALL_SPLITS = 1024

LOG_SQL_STATS_QUERY_TEXT = """SELECT sql_id,
   child_number,
   rows_processed,
   ROUND(cpu_time/1e6)           AS cpu_seconds,
   ROUND(user_io_wait_time/1e6)  AS io_wait_seconds,
   executions
FROM   gv$sql
WHERE  parsing_schema_name = sys_context('USERENV','SESSION_USER')
AND    module = :module
AND    action = :action
AND    sql_fulltext LIKE '%'||:action||'%'
ORDER BY sql_id, child_number"""


class OffloadTransportOracleApi(OffloadTransportRdbmsApiInterface):
    """Oracle specific methods"""

    def __init__(
        self,
        rdbms_owner: str,
        rdbms_table_name: str,
        offload_options: "OrchestrationConfig",
        messages: "OffloadMessages",
        dry_run: bool = False,
    ):
        super().__init__(
            rdbms_owner,
            rdbms_table_name,
            offload_options,
            messages,
            dry_run=dry_run,
        )
        self.debug("OffloadTransportOracleApi setup: (%s, %s)" % (rdbms_owner, rdbms_table_name))
        self._offload_transport_auth_using_oracle_wallet = offload_options.offload_transport_auth_using_oracle_wallet
        self._transport_row_source_query_split_methods = [
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT,
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD,
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE,
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_NATIVE_RANGE,
        ]

    def convert_query_import_expressions_on_rdbms_side(self):
        return False

    def generate_transport_action(self):
        """Action in Oracle is trimmed at 32 bytes, we do the same here"""
        id_str = id_generator()
        return ("%s_%s" % (id_str, self._rdbms_table_name.lower()))[:32]

    def get_id_column_for_range_splitting(self, rdbms_table):
        if len(rdbms_table.get_primary_key_columns()) != 1:
            return None
        pk_col = match_table_column(rdbms_table.get_primary_key_columns()[0], rdbms_table.columns)
        if pk_col and pk_col.data_type in (
            ORACLE_TYPE_NUMBER,
            ORACLE_TYPE_DATE,
            ORACLE_TYPE_TIMESTAMP,
        ):
            return pk_col
        return None

    def get_id_range(self, rdbms_col_name: str, predicate_offload_clause: str, partition_chunk: Any = None) -> tuple:
        """Return the MIN and MAX values for an id column using OracleSqlEngine."""
        iot_part_name = self._extract_iot_single_partition_name(partition_chunk)
        min_max_qry = get_oracle_dialect_engine().id_range_query(
            owner=self._rdbms_owner,
            table_name=self._rdbms_table_name,
            id_col_name=rdbms_col_name,
            iot_partition_name=iot_part_name,
            where_clause=predicate_offload_clause or "",
        )
        self.log("Oracle SQL:\n%s" % min_max_qry, detail=VVERBOSE)
        min_max_row = None
        cx = get_rdbms_connection_for_oracle(
            self._offload_options.rdbms_app_user,
            self._offload_options.rdbms_app_pass,
            self._offload_transport_dsn,
            self._offload_options.use_oracle_wallet,
        )
        ora_cursor = None
        try:
            ora_cursor = cx.cursor()
            min_max_row = ora_cursor.execute(min_max_qry).fetchone()
            if min_max_row:
                self.log(
                    "MIN/MAX: %s (%s)/%s (%s)"
                    % (
                        min_max_row[0],
                        type(min_max_row[0]),
                        min_max_row[1],
                        type(min_max_row[1]),
                    ),
                    detail=VVERBOSE,
                )
        finally:
            if ora_cursor is not None:
                try:
                    ora_cursor.close()
                except Exception:
                    pass
            try:
                cx.close()
            except Exception:
                pass
        assert min_max_row is not None
        return min_max_row[0], min_max_row[1]

    def get_rdbms_query_cast(
        self,
        column_expression,
        rdbms_column,
        staging_column,
        max_ts_scale,
        convert_expressions_on_rdbms_side=False,
        for_spark=False,
        nan_values_as_null=False,
        for_qi=False,
    ):
        """Returns an expression suitable for reading a specific column from the RDBMS table.
        Takes column_expression as an input rather than a column name because a transformation may already have
        taken place.
        for_spark: Spark fails to process TS WITH LOCAL TIME ZONE and INTERVALs so we convert to character in the DB.
        for_qi: Allows different behaviour for Query Import.
        """
        ff_scale = self._get_ts_ff_scale(max_ts_scale)
        cast_expression = column_expression
        if rdbms_column.data_type == ORACLE_TYPE_TIMESTAMP_LOCAL_TZ:
            cast_expression = f"CONCAT(CAST({column_expression} AS VARCHAR2(64)),' UTC')"
        elif rdbms_column.data_type == ORACLE_TYPE_TIMESTAMP_TZ:
            cast_expression = "TO_CHAR(%s,'YYYY-MM-DD HH24:MI:SS.FF%s TZH:TZM')" % (
                column_expression,
                ff_scale,
            )
        elif rdbms_column.data_type == ORACLE_TYPE_DATE and convert_expressions_on_rdbms_side:
            cast_expression = f"TO_CHAR({column_expression},'YYYY-MM-DD HH24:MI:SS')"
        elif rdbms_column.data_type == ORACLE_TYPE_TIMESTAMP and convert_expressions_on_rdbms_side:
            cast_expression = f"TO_CHAR({column_expression},'YYYY-MM-DD HH24:MI:SS.FF{ff_scale}')"
        elif (
            staging_column.is_string_based()
            and rdbms_column.data_type in (ORACLE_TYPE_NUMBER, ORACLE_TYPE_FLOAT)
            and convert_expressions_on_rdbms_side
        ):
            cast_expression = f"TO_CHAR({column_expression},'TM')"
        elif rdbms_column.data_type in (
            ORACLE_TYPE_INTERVAL_DS,
            ORACLE_TYPE_INTERVAL_YM,
        ) and (for_spark or for_qi):
            cast_expression = f"TO_CHAR({column_expression})"
        elif (
            rdbms_column.data_type == ORACLE_TYPE_NUMBER
            and rdbms_column.data_precision
            and rdbms_column.data_scale
            and rdbms_column.data_scale > rdbms_column.data_precision
            and for_spark
        ):
            cast_expression = f"CAST({column_expression} AS NUMBER)"
        elif rdbms_column.data_type in (ORACLE_TYPE_BINARY_FLOAT, ORACLE_TYPE_BINARY_DOUBLE) and nan_values_as_null:
            cast_expression = f"CASE WHEN {column_expression} IN ('NaN','Infinity','-Infinity') THEN NULL ELSE {column_expression} END"
        elif rdbms_column.data_type == ORACLE_TYPE_XMLTYPE:
            cast_expression = f'("{self._rdbms_table_name}".{column_expression}).getClobVal()'
        return cast_expression

    def get_offload_transport_sql_stats_function(self, rdbms_module, rdbms_action, conn_action=None):
        """Return a function that executes the LOG_SQL_STATS_QUERY_TEXT query for a given
        module and action
        """
        conn = self._get_app_connection()
        conn.module = rdbms_module
        if conn_action:
            conn.action = conn_action
        cursor = conn.cursor()

        def stats_function():
            return cursor.execute(
                LOG_SQL_STATS_QUERY_TEXT,
                {"module": rdbms_module, "action": rdbms_action},
            ).fetchall()

        return stats_function

    def get_rdbms_session_setup_commands(
        self,
        module: Any,
        action: Any,
        custom_session_parameters: Any,
        include_fixed_sqoop: bool = True,
        for_plsql: bool = False,
        include_semi_colons: bool = False,
        escape_semi_colons: bool = False,
        max_ts_scale: Any = None,
    ) -> list:
        """Returns a list of strings to be executed in the data transport source RDBMS session"""
        assert type(custom_session_parameters) is dict
        fixed_sqoop_parameters = self._get_fixed_sqoop_parameters(max_ts_scale)

        commands = []
        if include_fixed_sqoop:
            if for_plsql:
                commands.append("DBMS_APPLICATION_INFO.SET_MODULE('%s','%s');" % (module, action))
            else:
                commands.append("BEGIN DBMS_APPLICATION_INFO.SET_MODULE('%s','%s'); END;" % (module, action))
            client_info_command = build_oracle_client_info_command(for_plsql=for_plsql)
            if client_info_command:
                commands.append(client_info_command)
            commands.extend(
                self._oracle_alter_session_statements(
                    fixed_sqoop_parameters,
                    for_plsql=for_plsql,
                    include_semi_colons=include_semi_colons,
                    escape_semi_colons=escape_semi_colons,
                )
            )
        commands.extend(
            self._oracle_alter_session_statements(
                self._get_fixed_goe_parameters(),
                for_plsql=for_plsql,
                include_semi_colons=include_semi_colons,
                escape_semi_colons=escape_semi_colons,
            )
        )
        commands.extend(
            self._oracle_alter_session_statements(
                custom_session_parameters,
                for_plsql=for_plsql,
                include_semi_colons=include_semi_colons,
                escape_semi_colons=escape_semi_colons,
            )
        )
        return commands

    def get_rdbms_session_setup_hint(self, custom_session_parameters, max_ts_scale):
        """Returns a hint containing OPT_PARAM() calls for each optimizer parameter we control.
        We always include NO_PARALLEL because we handle parallelism in Sqoop/Spark, Oracle queries should be serial.
        """

        def enquote(x):
            if '"' not in x and "'" not in x:
                return f"'{x}'"
            return x

        def valid_hint_param(x):
            if not x:
                return False
            x = x.upper().strip('"').strip("'")
            return bool(x and not x.startswith("NLS_") and x not in self._get_fixed_sqoop_parameters(None))

        def to_opt_param(kv_dict):
            if not kv_dict:
                return ""
            return " ".join(f"OPT_PARAM({enquote(k)}, {enquote(v)})" for k, v in kv_dict.items() if valid_hint_param(k))

        assert type(custom_session_parameters) is dict
        opt_param_hints = (
            to_opt_param(self._get_fixed_sqoop_parameters(max_ts_scale))
            + " "
            + to_opt_param(self._get_fixed_goe_parameters())
            + " "
            + to_opt_param(custom_session_parameters)
        ).strip()
        return f"/*+ NO_PARALLEL {opt_param_hints} */"

    def get_transport_split_type(
        self,
        partition_chunk: "OffloadSourcePartitions",
        rdbms_table: "OffloadSourceTableInterface",
        parallelism: int,
        rdbms_partition_type: str,
        offload_by_subpartition: bool,
        predicate_offload_clause: str,
        native_range_split_available: bool = False,
    ) -> tuple:
        """Return split type and any tuned transport parallelism.
        If there are more partitions/subpartitions than the requested parallelism then split by
        partition/subpartition, otherwise we split the few partitions by Oracle extent (ROWID ranges),
        id ranges or MOD ranges.
        """
        self.debug("get_transport_split_type()")
        is_iot = rdbms_table.is_iot()
        id_split_col = self.get_id_column_for_range_splitting(rdbms_table)
        partition_by = None
        if partition_chunk and partition_chunk.count() > 0:
            partition_count = partition_chunk.count()
            subpartition_count = len(partition_chunk.subpartition_names())
        else:
            partition_count = 0
            subpartition_count = 0
        self.debug(f"parallelism: {parallelism}")
        tuned_parallelism = parallelism
        self.debug(f"partition_count: {partition_count}")
        self.debug(f"subpartition_count: {subpartition_count}")
        if partition_count > 0 and partition_count >= parallelism and partition_count <= MAX_UNION_ALL_SPLITS:
            if offload_by_subpartition:
                self.log("Splitting subpartitioned table by subpartition", detail=VVERBOSE)
                partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION
            else:
                self.log("Splitting partitioned table by partition", detail=VVERBOSE)
                partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION
        elif partition_count > 0 and subpartition_count >= parallelism and subpartition_count <= MAX_UNION_ALL_SPLITS:
            self.log(
                "Splitting subpartitioned table by subpartition as there are fewer partitions than requested parallelism: %s < %s"
                % (str(partition_count), str(parallelism)),
                detail=VVERBOSE,
            )
            partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION
        elif is_iot:
            if (
                partition_count > 1
                and partition_count <= MAX_UNION_ALL_SPLITS
                and rdbms_partition_type in ("RANGE", "LIST", "HASH")
            ):
                if partition_count < parallelism:
                    self.log(
                        "Splitting IOT by partition even though fewer partitions than requested parallelism: %s < %s"
                        % (str(partition_count), str(parallelism)),
                        detail=VVERBOSE,
                    )
                    tuned_parallelism = partition_count
                partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION
            elif id_split_col:
                if partition_count == 1:
                    self.log("Splitting IOT for single partition", detail=VVERBOSE)
                else:
                    self.log("Splitting non-partitioned IOT", detail=VVERBOSE)
                if id_split_col and native_range_split_available:
                    partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_NATIVE_RANGE
                elif id_split_col and id_split_col.is_number_based():
                    partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE
                else:
                    partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD
            else:
                if partition_count == 1:
                    self.log("Splitting IOT by MOD() for single partition", detail=VVERBOSE)
                else:
                    self.log("Splitting non-partitioned IOT by MOD()", detail=VVERBOSE)
                partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD
        else:
            self.log("Splitting table into ROWID ranges", detail=VVERBOSE)
            partition_by = TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT
        self.log(TRANSPORT_ROW_SOURCE_QUERY_SPLIT_TYPE_TEXT + partition_by, detail=VVERBOSE)
        assert partition_by in self._transport_row_source_query_split_methods
        return partition_by, tuned_parallelism

    def get_snapshot_clause(self, transport_scn: int, consistent_read: bool) -> str:
        """Return the Oracle Flashback AS OF SCN clause when consistent_read is enabled."""
        if consistent_read and transport_scn is not None:
            self.log(
                f"Using RDBMS snapshot {transport_scn} for consistent data retrieval",
                detail=VVERBOSE,
            )
            return f" {get_oracle_dialect_engine().snapshot_scn_clause(transport_scn)}"
        return ""

    def get_transport_row_source_query(
        self,
        partition_by_prm: str,
        rdbms_table: "OffloadSourceTableInterface",
        consistent_read: bool,
        transport_scn: int,
        parallelism: Any,
        offload_by_subpartition: Any,
        mod_column: Any,
        predicate_offload_clause: str,
        partition_chunk: "OffloadSourcePartitions | None" = None,
        pad: int | None = None,
        id_col_min: Any = None,
        id_col_max: Any = None,
    ) -> str:
        """Define a frontend query that retrieves data divided by the selected split method."""
        assert partition_by_prm in self._transport_row_source_query_split_methods

        is_iot = rdbms_table.is_iot()
        id_split_col = self.get_id_column_for_range_splitting(rdbms_table)

        if partition_by_prm == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT and is_iot:
            raise NotImplementedError("RDBMS extent splitting is not supported for IOTs")

        owner_table = '"%s"."%s"' % (self._rdbms_owner, self._rdbms_table_name)
        partition_by = partition_by_prm
        if consistent_read and transport_scn is not None:
            self.log(
                f"Using RDBMS snapshot {transport_scn} for consistent data retrieval",
                detail=VVERBOSE,
            )
            effective_scn: int | None = int(transport_scn)
        else:
            effective_scn = None
        union_all = self._row_source_query_union_all_clause(pad)
        engine = get_oracle_dialect_engine()
        iot_part_name = self._extract_iot_single_partition_name(partition_chunk)
        row_source = ""

        if partition_by in (
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_PARTITION,
            TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION,
        ):
            assert partition_chunk is not None
            is_subpart = partition_by == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_SUBPARTITION
            if not is_subpart:
                partition_names = partition_chunk.partition_names()
            elif offload_by_subpartition:
                partition_names = partition_chunk.partition_names()
            else:
                partition_names = partition_chunk.subpartition_names()
            row_source = union_all.join(
                [
                    engine.partition_split_branch_query(
                        owner=self._rdbms_owner,
                        table_name=self._rdbms_table_name,
                        partition_name=p,
                        is_subpartition=is_subpart,
                        transport_scn=effective_scn,
                        batch=(i % parallelism),
                        batch_col=TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
                    )
                    for i, p in enumerate(partition_names)
                ]
            )
        elif partition_by == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_EXTENT:
            partition_param, subpartition_param = "NULL", "NULL"
            if partition_chunk and partition_chunk.count() > 0:
                partition_param = "offload_vc2_ntt(%s)" % ",".join(
                    ["'%s'" % _ for _ in partition_chunk.partition_names()]
                )
                if offload_by_subpartition:
                    subpartition_param = partition_param
                    partition_param = "NULL"
            row_source = union_all.join(
                [
                    engine.extent_split_branch_query(
                        owner=self._rdbms_owner,
                        table_name=self._rdbms_table_name,
                        transport_scn=effective_scn,
                        partition_param=partition_param,
                        subpartition_param=subpartition_param,
                        degree=parallelism,
                        batch=i,
                        batch_col=TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
                        where_clause=predicate_offload_clause or "",
                    )
                    for i in range(parallelism)
                ]
            )
        elif partition_by == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_MOD:
            if not mod_column:
                raise OffloadTransportRdbmsApiException(
                    "Table %s cannot be split by mod without suitable column" % owner_table
                )
            row_source = engine.mod_split_query(
                owner=self._rdbms_owner,
                table_name=self._rdbms_table_name,
                mod_column=mod_column,
                degree=parallelism,
                batch_col=TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
                iot_partition_name=iot_part_name,
                transport_scn=effective_scn,
                where_clause=predicate_offload_clause or "",
            )
        elif partition_by == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_NATIVE_RANGE:
            assert id_split_col is not None
            row_source = engine.native_range_split_query(
                owner=self._rdbms_owner,
                table_name=self._rdbms_table_name,
                id_col_sql=rdbms_table.enclose_identifier(id_split_col.name),
                batch_col=TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
                iot_partition_name=iot_part_name,
                transport_scn=effective_scn,
                where_clause=predicate_offload_clause or "",
            )
        elif partition_by == TRANSPORT_ROW_SOURCE_QUERY_SPLIT_BY_ID_RANGE:
            assert id_split_col is not None
            id_ranges = split_ranges_for_id_range(id_col_min, id_col_max, parallelism)
            row_source = union_all.join(
                [
                    engine.id_range_split_branch_query(
                        owner=self._rdbms_owner,
                        table_name=self._rdbms_table_name,
                        id_col_name=id_split_col.name,
                        low_val=lowhigh[0],
                        high_val=lowhigh[1],
                        batch=(i % parallelism),
                        batch_col=TRANSPORT_ROW_SOURCE_QUERY_SPLIT_COLUMN,
                        iot_partition_name=iot_part_name,
                        transport_scn=effective_scn,
                        where_clause=predicate_offload_clause or "",
                    )
                    for i, lowhigh in enumerate(id_ranges)
                ]
            )
        return row_source

    def get_transport_row_source_query_hint_block(self) -> str:
        return "/*+ NO_PARALLEL */"

    def jdbc_driver_name(self) -> str:
        return "oracle.jdbc.driver.OracleDriver"

    def jdbc_url(self) -> str:
        auto_user = "/" if self._offload_transport_auth_using_oracle_wallet else ""
        return "jdbc:oracle:thin:%s@%s" % (auto_user, self._offload_transport_dsn)

    def log_sql_stats(
        self,
        module,
        action,
        payload,
        validation_polling_interval=OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED,
    ):
        """Retrieve Oracle SQL stats for a given module/action and log it.
        Also returns ROWS_PROCESSED in case the calling code needs it.
        Important that we use GV$SQL for this because Offload Transport tasks may have executed on different
        database instances to this orchestration code.

        Two methods are available for stats collection:

        1)  Polling thread. In this case the thread will have already collected snapshots of GV$SQL queries
            taken at an interval defined by an offload parameter. The snapshot results are held in a queue
            in the thread class instance. The queue should be drained by the caller of this method and the
            results passed in to this method as the payload parameter.

        2)  Query (default). If the payload parameter is None we need to run the query against GV$SQL now.
        """

        def log_sql_info(sql_info):
            if sql_info:
                tot_rows_processed = sum([_[2] for _ in sql_info])
                tot_cpu_seconds = sum([_[3] for _ in sql_info])
                tot_io_wait_seconds = sum([_[4] for _ in sql_info])
                tot_executions = sum([_[5] for _ in sql_info])
                row_format = "{0: <13} {1: >12} {2: >12} {3: >12} {4: >12} {5: >12}"
                self.log(OFFLOAD_TRANSPORT_SQL_STATISTICS_TITLE, detail=VVERBOSE)
                self.log(
                    row_format.format("SQL Id", "Child#", "Executions", "Rows", "CPU(s)", "IO Wait(s)"),
                    detail=VVERBOSE,
                )
                for (
                    sql_id,
                    child_number,
                    rows_processed,
                    cpu_seconds,
                    io_wait_seconds,
                    executions,
                ) in sql_info:
                    self.log(
                        row_format.format(
                            sql_id,
                            child_number,
                            executions,
                            rows_processed,
                            cpu_seconds,
                            io_wait_seconds,
                        ),
                        detail=VVERBOSE,
                    )
                self.log(
                    row_format.format(
                        "Total",
                        "",
                        tot_executions,
                        tot_rows_processed,
                        tot_cpu_seconds,
                        tot_io_wait_seconds,
                    ),
                    detail=VVERBOSE,
                )
                return tot_rows_processed

        self.debug("log_sql_stats()")
        if validation_polling_interval == OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED:
            self.log("Offload transport SQL stats collection is disabled", detail=VVERBOSE)
            return None

        tot_rows_processed = None
        try:
            if payload:
                sql_info = []
                row_snapshots = [item for sublist in payload for item in sublist]
                for sql_id_child_num, row_data in groupby(sorted(row_snapshots), lambda x: "%s:%s" % (x[0], x[1])):
                    rows = list(row_data)
                    sql_id, child_number = sql_id_child_num.split(":")
                    sql_info.append(
                        (
                            sql_id,
                            child_number,
                            max([_[2] for _ in rows]),
                            max([_[3] for _ in rows]),
                            max([_[4] for _ in rows]),
                            max([_[5] for _ in rows]),
                        )
                    )
            else:
                q_params = {"module": module, "action": action}
                self.log(
                    "Searching for transport SQL matching: %s" % str(q_params),
                    detail=VVERBOSE,
                )
                fn = self.get_offload_transport_sql_stats_function(module, action)
                sql_info = fn()
            tot_rows_processed = log_sql_info(sql_info)
        finally:
            self._close_app_connection()
        return tot_rows_processed

    def log_ash_usage(self, start_datetime, module, action):
        """Retrieve Oracle Active Session History for a given module/action
        and log it.
        THIS IS CURRENTLY NOT USED because we don't want to increase our
        dependency on add-on Oracle packs
        """
        self.debug("log_ash_usage()")
        ora_conn = self._get_adm_connection()
        ash_q = """SELECT sql_id, NVL(event,'CPU'), COUNT(*) seconds
FROM  gv$active_session_history
WHERE user_id = (SELECT user_id FROM dba_users WHERE username = :rdbms_app_user)
AND   sample_time >= :start_datetime
AND   module = :module
AND   action = :action
GROUP BY sql_id, NVL(event,'CPU')
ORDER BY seconds DESC"""
        q_params = {
            "rdbms_app_user": str((self._offload_options.rdbms_app_user or "").upper()),
            "start_datetime": start_datetime,
            "module": module,
            "action": action,
        }
        try:
            ora_cursor = ora_conn.cursor()
            ash = ora_cursor.execute(ash_q, q_params).fetchall()
            if ash:
                event_width = max([len(_[1]) for _ in ash])
                row_format = "{0: <15} {1: <" + str(event_width) + "} {2: >8}"
                self.log("Active Session History", detail=VVERBOSE)
                self.log(row_format.format("SQL Id", "Event", "Seconds"), detail=VVERBOSE)
                for sql_id, event, seconds in ash:
                    self.log(row_format.format(sql_id, event, seconds), detail=VVERBOSE)
        finally:
            ora_cursor.close()
            self._close_adm_connection()

    def get_rdbms_canary_query(self):
        return "SELECT dummy FROM dual"

    @contextmanager
    def query_import_extraction(
        self,
        staging_columns,
        source_query,
        source_binds,
        fetch_size,
        compress,
        rdbms_session_setup_commands,
    ):
        def cx_type_handler(cursor, name, default_type, size, precision, scale):
            if default_type == cxo.DB_TYPE_NUMBER:
                staging_column = match_table_column(name, staging_columns)
                if not staging_column or not staging_column.safe_mapping or staging_column.is_string_based():
                    return cursor.var(str, 255, cursor.arraysize)
            elif default_type in (cxo.DB_TYPE_VARCHAR, cxo.DB_TYPE_CHAR):
                return cursor.var(str, size, cursor.arraysize)
            elif default_type in (cxo.DB_TYPE_DATE, cxo.DB_TYPE_TIMESTAMP):
                return cursor.var(str, 255, cursor.arraysize)

        def setup_rdbms_session(ora_cursor):
            for session_statement in rdbms_session_setup_commands:
                self.log("Oracle sql: %s" % session_statement, detail=VERBOSE)
                if not self._dry_run:
                    ora_cursor.execute(session_statement)

        cx = get_rdbms_connection_for_oracle(
            self._offload_options.rdbms_app_user,
            self._offload_options.rdbms_app_pass,
            self._offload_transport_dsn,
            self._offload_options.use_oracle_wallet,
        )
        ora_cursor = cx.cursor()
        cx.outputtypehandler = cx_type_handler

        ora_cursor.arraysize = fetch_size

        self.log(
            "Importing load data with arraysize=%s, compression=%s" % (ora_cursor.arraysize, compress),
            detail=VERBOSE,
        )

        try:
            setup_rdbms_session(ora_cursor)
            self.log("Oracle sql: %s" % source_query, detail=VERBOSE)
            if source_binds:
                self.log("Bind values: %s" % str(source_binds), detail=VERBOSE)
            if not self._dry_run:
                if source_binds:
                    ora_cursor.execute(source_query, source_binds)
                else:
                    ora_cursor.execute(source_query)
            yield ora_cursor
        finally:
            ora_cursor.close()
            cx.close()

    def sqoop_by_query_boundary_query(self, offload_transport_parallelism):
        """Return a query providing a value range for Sqoop --boundary-query option."""
        return f'"SELECT 0, {offload_transport_parallelism - 1} FROM dual"'

    def sqoop_rdbms_specific_jvm_overrides(self, rdbms_session_setup_commands: Any) -> list:
        oraoop_d_options = [
            "-Doracle.sessionTimeZone=UTC",
            "-Doraoop.timestamp.string=true",
            "-Doraoop.jdbc.url.verbatim=true",
        ]
        if rdbms_session_setup_commands:
            oraoop_d_options += [
                "-Doraoop.oracle.session.initialization.statements=%s"
                % self._ssh_cli_safe_value("".join(rdbms_session_setup_commands))
            ]
        return oraoop_d_options

    def sqoop_rdbms_specific_options(self) -> list:
        sqoop_opts = []
        if not self._offload_options.sqoop_disable_direct:
            sqoop_opts.append("--direct")
        return sqoop_opts

    def sqoop_rdbms_specific_jvm_table_options(
        self, partition_chunk: Any, partition_type: Any = None, is_iot: bool = False, consistent_read: bool = False
    ) -> list:
        oraoop_options = []
        if is_iot and partition_type == OFFLOAD_PARTITION_TYPE_RANGE:
            oraoop_options += ["-Doraoop.chunk.method=partition"]
            oraoop_options += ["-Doraoop.import.consistent.read=false"]
        else:
            oraoop_options += [
                "-Doraoop.import.consistent.read={true_or_false}".format(
                    true_or_false="true" if consistent_read else "false"
                )
            ]

        if partition_chunk and partition_chunk.count() > 0:
            oraoop_options += [
                "-Doraoop.import.partitions=" + self._ssh_cli_safe_value(",".join(partition_chunk.partition_names()))
            ]
        return oraoop_options

    def sqoop_rdbms_specific_table_options(self, rdbms_owner: Any, table_name: Any) -> list:
        return [
            "--table",
            self._ssh_cli_safe_value((rdbms_owner + "." + table_name).upper()),
        ]

    def _get_adm_connection(self):
        if not self._rdbms_adm_conn:
            self._rdbms_adm_conn = get_rdbms_connection_for_oracle(
                self._offload_options.ora_adm_user,
                self._offload_options.ora_adm_pass,
                self._rdbms_adm_dsn,
                self._offload_options.use_oracle_wallet,
            )
        return self._rdbms_adm_conn

    def _close_adm_connection(self):
        if self._rdbms_adm_conn:
            self._rdbms_adm_conn.close()
        self._rdbms_adm_conn = None

    def _get_app_connection(self):
        if not self._rdbms_app_conn:
            self._rdbms_app_conn = get_rdbms_connection_for_oracle(
                self._offload_options.rdbms_app_user,
                self._offload_options.rdbms_app_pass,
                self._offload_transport_dsn,
                self._offload_options.use_oracle_wallet,
            )
        return self._rdbms_app_conn

    def _close_app_connection(self):
        if self._rdbms_app_conn:
            self._rdbms_app_conn.close()
        self._rdbms_app_conn = None

    def _get_fixed_goe_parameters(self):
        """GOE-1375"""
        if self._fixed_goe_parameters is None:
            ora_conn = self._get_adm_connection()
            if oracle_version_is_smart_scan_unsafe(ora_conn.version):
                self._fixed_goe_parameters = {"CELL_OFFLOAD_PROCESSING": "FALSE"}
            else:
                self._fixed_goe_parameters = {}
            self._close_adm_connection()
        return self._fixed_goe_parameters

    def _get_fixed_sqoop_parameters(self, max_ts_scale):
        """These are defined to match parameters set by Sqoop/Oraoop

        Dependency on this TIME_ZONE=UTC with logic for avro_conv_fns appending UTC
        """
        ff_scale = self._get_ts_ff_scale(max_ts_scale)
        return {
            "TRACEFILE_IDENTIFIER": "'%s'" % FRONTEND_TRACE_ID,
            "TIME_ZONE": "'UTC'",
            "NLS_TIMESTAMP_TZ_FORMAT": "'YYYY-MM-DD HH24:MI:SS.FF%s TZH:TZM'" % ff_scale,
            "NLS_TIMESTAMP_FORMAT": "'YYYY-MM-DD HH24:MI:SS.FF%s'" % ff_scale,
            "NLS_DATE_FORMAT": "'YYYY-MM-DD HH24:MI:SS'",
            '"_SERIAL_DIRECT_READ"': "TRUE",
        }

    def _get_ts_ff_scale(self, ts_scale):
        """Return a string scale which can be tagged onto 'HH24:MI:SS.FF'"""
        if ts_scale:
            assert isinstance(ts_scale, int)
            assert 0 <= ts_scale <= 9
        return "" if ts_scale is None else str(ts_scale)

    def _oracle_alter_session_statements(
        self,
        session_parameter_dict,
        for_plsql=False,
        include_semi_colons=False,
        escape_semi_colons=False,
    ):
        """Format ALTER SESSION statements for inclusion in a data transport operation
        return statements as a list, empty list if nothing to do
        """
        if not session_parameter_dict:
            return []
        alter_template = "ALTER SESSION SET %s=%s"
        semi_colon = "\\;" if escape_semi_colons else ";"
        if include_semi_colons:
            alter_template += semi_colon

        if for_plsql:
            plsql_wrap_template = "EXECUTE IMMEDIATE q'!%s!'"
            use_template = (plsql_wrap_template % alter_template) + semi_colon
        else:
            use_template = alter_template

        alter_session_statements = [use_template % (k, v) for k, v in sorted(session_parameter_dict.items())]
        return alter_session_statements

    def _cx_getvalue(self, incoming):
        return incoming.getvalue() if incoming and hasattr(incoming, "getvalue") else incoming

    @staticmethod
    def _extract_iot_single_partition_name(partition_chunk: Any) -> str | None:
        """Return the single partition name when partition_chunk contains exactly 1 partition."""
        if partition_chunk and partition_chunk.count() == 1:
            return str(partition_chunk.partition_names().pop())
        return None

    def _get_iot_single_partition_clause(self, partition_chunk):
        """Return PARTITION("partition_name") clause for a single-partition IOT chunk."""
        iot_part_name = self._extract_iot_single_partition_name(partition_chunk)
        if iot_part_name:
            return f" {get_oracle_dialect_engine().iot_partition_clause(iot_part_name)}"
        return ""
