# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""OffloadStatusReport collector, option normaliser, and CLI runner."""

import json
import os
import sys
from copy import copy
from datetime import datetime
from types import SimpleNamespace

from goe.config.options import StatusReportOptions
from goe.config.orchestration_config import OrchestrationConfig
from goe.exceptions import OffloadOptionError
from goe.goe import (
    get_log_fh,
    get_log_fh_name,
    get_rdbms_db_name,
    init,
    init_log,
    log,
    log_command_line,
    log_timestamp,
    version,
)
from goe.offload import offload_constants
from goe.offload.backend_api import (
    REPORT_ATTR_BACKEND_DISPLAY_NAME,
    REPORT_ATTR_BACKEND_HOST_INFO,
    REPORT_ATTR_BACKEND_HOST_INFO_TYPE,
)
from goe.offload.offload_messages import (
    SUPPRESS_STDOUT,
    VERBOSE,
    VVERBOSE,
    OffloadMessages,
)
from goe.offload.offload_metadata_functions import (
    decode_metadata_incremental_high_values,
)
from goe.offload.oracle.ora_query import OracleQuery, OracleQueryException, get_oracle_connection
from goe.offload.registry import (
    create_backend_api,
    create_backend_table,
    create_frontend_api,
    create_repository_client,
    create_source_table,
)
from goe.orchestration import command_steps, orchestration_constants
from goe.persistence.orchestration_metadata import OrchestrationMetadata
from goe.report.demo_data import DemoDataMixin
from goe.report.models import (
    AAPD_OBJECTS,
    CSV,
    DEFAULT_CSV_DELIMITER,
    DEFAULT_CSV_ENCLOSURE,
    DEFAULT_DEMO_MODE,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_OUTPUT_LEVEL,
    DEFAULT_REPORT_DIRECTORY,
    DEFAULT_REPORT_NAME,
    DEPENDENT_OBJECTS,
    DETAIL_LEVEL,
    FAILURE,
    HTML,
    INCREMENTAL_HIGH_VALUE,
    INCREMENTAL_KEY,
    INCREMENTAL_PREDICATE_TYPE,
    INCREMENTAL_PREDICATE_VALUE,
    INCREMENTAL_RANGE,
    INCREMENTAL_UPDATE_METHOD,
    INCREMENTAL_UPDATE_OBJECTS_OFFLOAD,
    INCREMENTAL_UPDATE_OBJECTS_RDBMS,
    JOIN_OBJECTS_OFFLOAD,
    JOIN_OBJECTS_RDBMS,
    JSON,
    OBJECT_NAME,
    OBJECT_OWNER,
    OBJECT_TYPE_DB,
    OBJECT_TYPE_GOE,
    OFFLOAD_OWNER,
    OFFLOAD_PART_KEY,
    OFFLOAD_TABLE,
    OFFLOAD_TABLE_EXISTS,
    OFFLOAD_TYPE,
    OFFLOADED_BYTES,
    OFFLOADED_PARTS,
    OFFLOADED_ROWS,
    OFFLOADED_TABLES,
    RAW,
    RECLAIMABLE_BYTES,
    RECLAIMABLE_PARTS,
    RECLAIMABLE_ROWS,
    RETAINED_BYTES,
    RETAINED_PARTS,
    RETAINED_ROWS,
    SOURCE_IOT_TYPE,
    SOURCE_OWNER,
    SOURCE_TABLE,
    SUMMARY_LEVEL,
    TEXT,
    OffloadStatusReportException,
    incremental_partition_match,
)
from goe.report.renderers import ReportRenderersMixin
from goe.util.goe_log import log_exception
from goe.util.string_utils import plural


class OffloadStatusReport(ReportRenderersMixin, DemoDataMixin):
    """Class for generating the Offload Status Report data and optional report."""

    _execute: bool = True

    def __init__(self, orchestration_config, messages, ora_adm_conn=None):
        """OffloadStatusReport constructor. Essentially a range of the database connection parameters.

        Log all parameters (except the password) RDBMS initialisation... General initialisations...
        """
        self._messages = messages
        self._orchestration_config = orchestration_config

        self._messages.debug("Parameters:")
        self._messages.debug(
            "%-50s : %s" % ("ora_adm_user", self._orchestration_config.ora_adm_user),
            detail=SUPPRESS_STDOUT,
        )
        self._messages.debug(
            "%-50s : %s" % ("oracle_dsn", self._orchestration_config.oracle_dsn),
            detail=SUPPRESS_STDOUT,
        )
        self._messages.debug(
            "%-50s : %s" % ("ora_adm_conn", "initialized" if ora_adm_conn else "not initialized"),
            detail=SUPPRESS_STDOUT,
        )

        self._backend_api = create_backend_api(
            self._orchestration_config.target,
            self._orchestration_config,
            self._messages,
            dry_run=(not self._execute),
        )
        self._backend_info = self._backend_api.backend_report_info()
        self._backend_db_type = self._orchestration_config.target

        self._messages.debug(
            "%-50s : %s" % ("_backend_db_type", self._backend_db_type),
            detail=SUPPRESS_STDOUT,
        )
        for k, v in self._backend_info.items():
            self._messages.debug("%-50s : %s" % ("_backend_info.%s" % k, v), detail=SUPPRESS_STDOUT)

        if ora_adm_conn:
            self._ora_conn = ora_adm_conn
            self._messages.debug("Using existing Oracle connection")
        else:
            self._ora_conn = get_oracle_connection(
                self._orchestration_config.ora_adm_user,
                self._orchestration_config.ora_adm_pass,
                self._orchestration_config.oracle_dsn,
                self._orchestration_config.use_oracle_wallet,
            )
            self._messages.debug("Oracle connection made")
        self._ora_service = OracleQuery.fromconnection(self._ora_conn)
        self._ora_adm_user = self._orchestration_config.ora_adm_user
        self._ora_adm_pass = self._orchestration_config.ora_adm_pass
        self._ora_db_name = get_rdbms_db_name(self._orchestration_config, ora_conn=self._ora_conn)
        self._oracle_dsn = self._orchestration_config.oracle_dsn
        self._db_type = offload_constants.DBTYPE_ORACLE
        self._use_oracle_wallet = self._orchestration_config.use_oracle_wallet

        self._set_module("Offload Status Report")

        self._messages.debug(
            "%-50s : %s" % ("_ora_conn", "initialized" if self._ora_conn else "not initialized"),
            detail=SUPPRESS_STDOUT,
        )
        self._messages.debug(
            "%-50s : %s"
            % (
                "_ora_service",
                "initialized" if self._ora_service else "not initialized",
            ),
            detail=SUPPRESS_STDOUT,
        )
        self._messages.debug("%-50s : %s" % ("ora_db_name", self._ora_db_name), detail=SUPPRESS_STDOUT)

        self._repo_client = create_repository_client(
            self._orchestration_config, self._messages, dry_run=(not self._execute)
        )

        self._execute = True
        self._start_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._start_time = datetime.now().strftime("%d %B %Y %H:%M:%S")

        self._messages.debug("%-50s : %s" % ("_execute", self._execute), detail=SUPPRESS_STDOUT)
        self._messages.debug("%-50s : %s" % ("_start_ts", self._start_ts), detail=SUPPRESS_STDOUT)
        self._messages.debug("%-50s : %s" % ("_start_time", self._start_time), detail=SUPPRESS_STDOUT)

        self._messages.debug("OffloadStatusReport object initialized")

    def __del__(self):
        """Destructor."""
        if hasattr(self, "_ora_conn"):
            self._ora_conn.close()

    @property
    def metadata(self):
        """Return metadata about the report."""
        return self._initialise_metadata_dict()

    @property
    def report_file(self):
        """Return name of the report being saved if applicable."""
        return self._report_file if hasattr(self, "_report_file") else None

    @property
    def as_json(self):
        """Return whether the data is to be returned as JSON."""
        return self._output_format == JSON

    @property
    def as_raw(self):
        """Return whether the data is to be returned as Python raw data."""
        return self._output_format == RAW

    @property
    def is_summary(self):
        """Return whether the output format is at summary level."""
        return self._output_level == SUMMARY_LEVEL

    @property
    def is_detail(self):
        """Return whether the output format is at detail level."""
        return self._output_level == DETAIL_LEVEL

    def get_offload_status_report_data(
        self,
        schema=None,
        table=None,
        output_level=DEFAULT_OUTPUT_LEVEL,
        demo_mode=DEFAULT_DEMO_MODE,
    ):
        """Fetch and pre-process all of the data required for either the Offload Status Report or API consumer."""
        if schema is not None:
            assert self._valid_sql_name(schema), "invalid value for schema parameter"
            self._schema = schema.upper()
        else:
            self._schema = schema

        if table is not None:
            assert self._valid_sql_name(table), "invalid value for table parameter"
            self._table = table.upper()
        else:
            self._table = table

        self._output_level = output_level.lower() if output_level is not None else DEFAULT_OUTPUT_LEVEL
        self._demo_mode = demo_mode

        self._messages.debug("%-30s : %s" % ("_schema", self._schema), detail=SUPPRESS_STDOUT)
        self._messages.debug("%-30s : %s" % ("_table", self._table), detail=SUPPRESS_STDOUT)
        self._messages.debug("%-30s : %s" % ("_output_level", self._output_level), detail=SUPPRESS_STDOUT)
        self._messages.debug("%-30s : %s" % ("_demo_mode", self._demo_mode), detail=SUPPRESS_STDOUT)

        assert self._output_level in (
            SUMMARY_LEVEL,
            DETAIL_LEVEL,
        ), "output_level parameter must be either %s or %s" % (
            SUMMARY_LEVEL,
            DETAIL_LEVEL,
        )

        if not self._demo_mode:
            offloaded_tables = self._messages.offload_step(
                command_steps.STEP_OSR_FIND_TABLES,
                lambda: self._get_offloaded_tables(),
                self._execute,
            )
            table_data = self._messages.offload_step(
                command_steps.STEP_OSR_FETCH_DATA,
                lambda: self._get_table_data(offloaded_tables),
                self._execute,
            )
        else:
            table_data = self._messages.offload_step(
                command_steps.STEP_OSR_DEMO_DATA,
                lambda: self._get_demo_table_data(),
                self._execute,
            )

        report_data = self._messages.offload_step(
            command_steps.STEP_OSR_PROCESS_DATA,
            lambda: self._process_report_data(table_data),
            self._execute,
        )

        return report_data

    def gen_offload_status_report(
        self,
        report_data,
        output_format=DEFAULT_OUTPUT_FORMAT,
        report_name=DEFAULT_REPORT_NAME,
        report_directory=DEFAULT_REPORT_DIRECTORY,
        csv_delimiter=DEFAULT_CSV_DELIMITER,
        csv_enclosure=DEFAULT_CSV_ENCLOSURE,
    ):
        """Fetch and pre-process all of the data required for either the Offload Status Report or API consumer."""
        self._output_format = output_format.lower() if output_format is not None else DEFAULT_OUTPUT_FORMAT
        self._report_name = report_name or DEFAULT_REPORT_NAME
        self._report_directory = report_directory or DEFAULT_REPORT_DIRECTORY
        self._csv_delimiter = csv_delimiter or DEFAULT_CSV_DELIMITER
        self._csv_enclosure = csv_enclosure or DEFAULT_CSV_ENCLOSURE

        self._messages.debug(
            "%-30s : %s" % ("_output_format", self._output_format),
            detail=SUPPRESS_STDOUT,
        )
        self._messages.debug("%-30s : %s" % ("_report_name", self._report_name), detail=SUPPRESS_STDOUT)
        self._messages.debug(
            "%-30s : %s" % ("_report_directory", self._report_directory),
            detail=SUPPRESS_STDOUT,
        )
        self._messages.debug(
            "%-30s : %s" % ("_csv_delimiter", self._csv_delimiter),
            detail=SUPPRESS_STDOUT,
        )
        self._messages.debug(
            "%-30s : %s" % ("_csv_enclosure", self._csv_enclosure),
            detail=SUPPRESS_STDOUT,
        )

        assert self._output_format in (
            CSV,
            TEXT,
            HTML,
            JSON,
            RAW,
        ), "output_format parameter must be one of [%s, %s, %s, %s, %s]" % (
            CSV,
            TEXT,
            HTML,
            JSON,
            RAW,
        )
        assert " " not in self._report_name, "report_name parameter cannot contain spaces"
        assert " " not in self._report_directory, "report_directory parameter cannot contain spaces"
        assert len(self._csv_delimiter) == 1, "csv_delimiter parameter must be a single character"
        assert len(self._csv_enclosure) == 1, "csv_enclosure parameter must be a single character"

        if self._output_format == CSV:
            rep_fn = lambda: self._gen_csv_report(report_data)
        elif self._output_format == TEXT:
            rep_fn = lambda: self._gen_text_report(report_data)
        elif self._output_format == HTML:
            rep_fn = lambda: self._gen_html_report(report_data)
        elif self._output_format == JSON:
            rep_fn = lambda: self._gen_json_report(report_data)
        elif self._output_format == RAW:
            rep_fn = lambda: self._gen_raw_report(report_data)
        status = self._messages.offload_step(command_steps.STEP_OSR_GENERATE_REPORT, rep_fn, execute=self._execute)
        return status

    def _set_module(self, module):
        """Set V$SESSION.MODULE."""
        self._ora_conn.module = f"{module:.64}"
        self._messages.debug("Set module to %s" % module, SUPPRESS_STDOUT)

    def _set_action(self, action):
        """Set V$SESSION.ACTION."""
        self._ora_conn.action = f"{action:.64}"
        self._messages.debug("Set action to %s" % action, SUPPRESS_STDOUT)

    def _set_client_info(self, client_info):
        """Set V$SESSION.CLIENT_INFO."""
        self._ora_conn.clientinfo = client_info
        self._messages.debug("Set clientinfo to %s" % client_info, SUPPRESS_STDOUT)

    def _format_table_name(self, schema_name, table_name, uppercase=True):
        """Return qualified table name in uppercase if required."""
        qualified_table_name = "%s.%s" % (schema_name, table_name)
        return qualified_table_name.upper() if uppercase else qualified_table_name

    def _valid_sql_name(self, sql_name):
        """Validate that the schema or table name is a valid SQL name (return boolean)."""
        try:
            self._ora_service.execute(
                "SELECT DBMS_ASSERT.SIMPLE_SQL_NAME(:name) FROM dual",
                binds={"name": sql_name},
            )
            return True
        except OracleQueryException:
            return False

    def _initialise_metadata_dict(self):
        """Return dictionary of metadata pertaining to this report"""
        return {
            "version": version(),
            "schema": self._schema,
            "table": self._table,
            "output_format": self._output_format,
            "output_level": self._output_level,
            "report_name": self._report_name,
            "report_directory": self._report_directory,
            "csv_delimiter": self._csv_delimiter,
            "csv_enclosure": self._csv_enclosure,
            "demo_mode": self._demo_mode,
            "db_name": self._ora_db_name,
            "db_login_user": self._ora_adm_user,
            "db_connection": self._oracle_dsn,
            "run_date": self._start_time,
            "backend_db_type": self._backend_info[REPORT_ATTR_BACKEND_DISPLAY_NAME],
            "backend_host_label": self._backend_info[REPORT_ATTR_BACKEND_HOST_INFO_TYPE],
            "backend_host_value": self._backend_info[REPORT_ATTR_BACKEND_HOST_INFO],
        }

    def _initialise_summary_dict(self):
        return {
            OFFLOADED_TABLES: 0,
            OFFLOADED_PARTS: 0,
            OFFLOADED_BYTES: 0,
            OFFLOADED_ROWS: 0,
            RETAINED_BYTES: 0,
            RETAINED_PARTS: 0,
            RETAINED_ROWS: 0,
            RECLAIMABLE_BYTES: 0,
            RECLAIMABLE_PARTS: 0,
            RECLAIMABLE_ROWS: 0,
        }

    def _get_offloaded_tables(self):
        """Return the set of offloaded tables to cycle through for the report.

        Data format:
            {
              SOURCE_OWNER:                string
              SOURCE_TABLE:                string
              OFFLOAD_TYPE:                string
              OFFLOAD_OWNER:               string
              OFFLOAD_TABLE:               string
              HYBRID_OWNER:                string
              HYBRID_VIEW:                 string
              HYBRID_VIEW_TYPE:            string
              HYBRID_EXTERNAL_TABLE:       string
              INCREMENTAL_KEY:             string
              INCREMENTAL_HIGH_VALUE:      string
              INCREMENTAL_RANGE:           string
              INCREMENTAL_PREDICATE_TYPE:  string
              INCREMENTAL_PREDICATE_VALUE: string
              OFFLOAD_BUCKET_COLUMN:       string
              OFFLOAD_BUCKET_METHOD:       string
              OFFLOAD_BUCKET_COUNT:        string
              OFFLOAD_VERSION:             string
              OFFLOAD_SORT_COLUMNS:        string
              OFFLOAD_PARTITION_FUNCTIONS: string
              SOURCE_IOT_TYPE:             string
            }
        """

        self._messages.log("Get offloaded tables for report", detail=VERBOSE)

        sql = f"""SELECT o.offloaded_owner AS source_owner
,      o.offloaded_table AS source_table
,      o.offload_type
,      o.hadoop_owner    AS offload_owner
,      o.hadoop_table    AS offload_table
,      o.hybrid_owner
,      o.hybrid_view
,      o.hybrid_view_type
,      o.hybrid_external_table
,      o.incremental_key
,      o.incremental_high_value
,      o.incremental_range
,      o.incremental_predicate_type
,      o.incremental_predicate_value
,      o.offload_bucket_column
,      o.offload_bucket_method
,      o.offload_bucket_count
,      o.offload_version
,      o.offload_sort_columns
,      o.offload_partition_functions
,      t.iot_type AS source_iot_type
FROM  {self._ora_adm_user}.offload_objects o
       LEFT OUTER JOIN
       dba_all_tables                  t
       ON (    t.owner      = o.offloaded_owner
           AND t.table_name = o.offloaded_table )
WHERE (o.offloaded_owner  = :offloaded_owner OR :offloaded_owner IS NULL)
AND   (o.offloaded_table  = :offloaded_table OR :offloaded_table IS NULL)
AND    o.hybrid_view_type = 'GOE_OFFLOAD_HYBRID_VIEW'
AND    o.offloaded_table  = o.hybrid_view
ORDER  BY
       o.offloaded_owner
,      o.offloaded_table"""

        binds = {"offloaded_owner": self._schema, "offloaded_table": self._table}

        self._messages.debug("SQL: %s" % sql, detail=SUPPRESS_STDOUT)
        self._messages.debug("Binds: %s" % binds, detail=SUPPRESS_STDOUT)

        results = self._ora_service.execute(sql, binds=binds, cursor_fn=lambda c: c.fetchall(), as_dict=True)

        self._messages.debug("Fetched %s offloaded %s" % (len(results), plural("table", len(results))))
        self._messages.debug("Offloaded table data: %s" % results, detail=SUPPRESS_STDOUT)

        return results

    def _decode_metadata_incremental_high_values(
        self,
        incremental_predicate_type,
        incremental_key,
        incremental_high_value,
        rdbms_base_table,
    ):
        _, hvs, _ = decode_metadata_incremental_high_values(
            incremental_predicate_type,
            incremental_key,
            incremental_high_value,
            rdbms_base_table,
        )
        return hvs

    def _get_rdbms_space_data(self, offloaded_table, offload_data, ost):
        """Return the RDBMS data for an offloaded table. Data includes space and partitions
        retained in the RDBMS along with some metadata about the table(s).

        Data format:
            {
              SOURCE_OWNER:      string
              SOURCE_TABLE:      string
              RETAINED_BYTES:    int
              RETAINED_PARTS:    int
              RECLAIMABLE_BYTES: int
              RECLAIMABLE_PARTS: int
            }

        Initialise return data... Determine reclaimable space or retained space. Reclaimable if: 1) it's a 90-10 (RANGE[_AND_PREDICATE], LIST_AS_RANGE[_AND_PREDICATE] only) and the partition has been offloaded 2) it's a 100-10 and the partition has been offloaded and the table is not enabled for certain Incremental Update methods that would mean the partition might possibly be modified 3) it's a 100-0 and the table is not enabled for certain Incremental Update methods that would mean the partition might possibly be modified For item 1), 90-10 tables offloaded by PREDICATE cannot be reclaimed as we have no current means of calculating how much space could be reclaimed by deleting data that matches offloaded predicates. And even then space is only reclaimed for the table itself (unless re-organising it with a MOVE). For item 2), just because a table is enabled with Incremental Update methods such as CHANGELOG does not necessarily mean that an offloaded partition will be updated. It's probably more likely that the data above the HWM would be updated. However, we can't assume this and therefore we have to assume that an offloaded partition for a table with a non-reclaimable Incremental Update method cannot be reclaimed.
        """

        self._messages.detail(
            "Get RDBMS space data for offloaded table: %s"
            % self._format_table_name(offloaded_table[SOURCE_OWNER], offloaded_table[SOURCE_TABLE])
        )

        rdbms_data = self._initialise_summary_dict()
        rdbms_data[SOURCE_OWNER] = offloaded_table[SOURCE_OWNER]
        rdbms_data[SOURCE_TABLE] = offloaded_table[SOURCE_TABLE]

        sql = """WITH table_data AS (
        SELECT t.owner
        ,      t.table_name
        ,      t.parent_table_name
        ,      NVL(t.num_rows, 0)   AS table_rows
        ,      tp.partition_name
        ,      tp.partition_position
        ,      tp.high_value        AS partition_high_value
        ,      NVL(tp.num_rows, 0)  AS partition_rows
        ,      tsp.subpartition_name
        ,      tsp.subpartition_position
        ,      tsp.high_value       AS subpartition_high_value
        ,      NVL(tsp.num_rows, 0) AS subpartition_rows
        FROM  (
               SELECT t.owner
               ,      t.table_name
               ,      t.table_name AS parent_table_name
               ,      t.num_rows
               FROM   dba_all_tables t
               WHERE  t.owner      = :source_owner
               AND    t.table_name = :source_table
               UNION ALL
               SELECT t.owner
               ,      t.table_name
               ,      t.iot_name AS parent_table_name
               ,      t.num_rows
               FROM   dba_all_tables t
               WHERE  t.owner    = :source_owner
               AND    t.iot_name = :source_table
               AND    'IOT'      = :source_iot_type
              )                           t
               LEFT OUTER JOIN
               dba_tab_partitions         tp
               ON (    tp.table_owner     = t.owner
                   AND tp.table_name      = t.table_name )
               LEFT OUTER JOIN
               dba_tab_subpartitions      tsp
               ON (    tsp.table_owner    = tp.table_owner
                   AND tsp.table_name     = tp.table_name
                   AND tsp.partition_name = tp.partition_name )
        )
,    index_data AS (
        SELECT i.owner
        ,      i.index_name
        ,      i.index_type
        ,      i.table_owner
        ,      i.table_name
        ,      ip.partition_name
        ,      CASE
                  WHEN pi.locality = 'LOCAL'
                  THEN ip.partition_position
               END AS partition_position
        ,      isp.subpartition_name
        ,      CASE
                  WHEN pi.locality = 'LOCAL'
                  THEN isp.subpartition_position
               END AS subpartition_position
        FROM   dba_indexes                i
               LEFT OUTER JOIN
               dba_part_indexes           pi
               ON (    pi.owner           = i.owner
                   AND pi.index_name      = i.index_name )
               LEFT OUTER JOIN
               dba_ind_partitions         ip
               ON (    ip.index_owner     = i.owner
                   AND ip.index_name      = i.index_name )
               LEFT OUTER JOIN
               dba_ind_subpartitions      isp
               ON (    isp.index_owner    = ip.index_owner
                   AND isp.index_name     = ip.index_name
                   AND isp.partition_name = ip.partition_name )
        WHERE i.table_owner = :source_owner
        AND   i.table_name  = :source_table
        )
,    lob_data AS (
        SELECT l.owner
        ,      l.segment_name AS lob_name
        ,      l.table_name
        ,      lp.partition_name
        ,      lp.partition_position
        ,      lp.lob_partition_name
        ,      lsp.lob_subpartition_name
        ,      lsp.subpartition_position
        FROM   dba_lobs                       l
               LEFT OUTER JOIN
               dba_lob_partitions             lp
               ON (    lp.table_owner         = l.owner
                   AND lp.table_name          = l.table_name
                   AND lp.lob_name            = l.segment_name )
               LEFT OUTER JOIN
               dba_lob_subpartitions          lsp
               ON (    lsp.table_owner        = lp.table_owner
                   AND lsp.table_name         = lp.table_name
                   AND lsp.lob_partition_name = lp.lob_partition_name )
        WHERE  l.owner      = :source_owner
        AND    l.table_name = :source_table
        )
,    segment_mapping AS (
        SELECT 'TABLES'                   AS segment_group
        ,      NVL(s.bytes,0)             AS segment_bytes
        ,      t.owner                    AS table_owner
        ,      t.parent_table_name        AS table_name
        ,      t.partition_position       AS table_partition_position
        ,      t.subpartition_position    AS table_subpartition_position
        ,      t.partition_high_value     AS table_partition_high_value
        ,      t.subpartition_high_value  AS table_subpartition_high_value
        ,      t.table_rows               AS table_rows
        ,      t.partition_rows           AS table_partition_rows
        ,      t.subpartition_rows        AS table_subpartition_rows
        FROM   table_data                 t
               LEFT OUTER JOIN
               dba_segments               s
               ON (    t.owner            = s.owner
                   AND t.table_name       = s.segment_name
                   AND COALESCE(t.subpartition_name, t.partition_name, t.table_name) = COALESCE(s.partition_name, s.segment_name)
                   AND s.segment_type IN ('TABLE', 'TABLE PARTITION', 'TABLE SUBPARTITION') )
        --
        UNION ALL
        --
        SELECT CASE
                  WHEN i.index_type = 'IOT - TOP'
                  THEN 'TABLES'
                  ELSE 'INDEXES'
               END                        AS segment_group
        ,      NVL(s.bytes,0)             AS segment_bytes
        ,      i.table_owner              AS table_owner
        ,      i.table_name               AS table_name
        ,      i.partition_position       AS table_partition_position
        ,      i.subpartition_position    AS table_subpartition_position
        ,      NULL                       AS table_partition_high_value
        ,      NULL                       AS table_subpartition_high_value
        ,      NULL                       AS table_rows
        ,      NULL                       AS table_partition_rows
        ,      NULL                       AS table_subpartition_rows
        FROM   index_data                 i
               LEFT OUTER JOIN
               dba_segments               s
               ON (    i.owner            = s.owner
                   AND i.index_name       = s.segment_name
                   AND COALESCE(i.subpartition_name, i.partition_name, i.index_name) = COALESCE(s.partition_name, s.segment_name)
                   AND s.segment_type IN ('INDEX', 'LOBINDEX', 'INDEX PARTITION', 'INDEX SUBPARTITION') )
        WHERE  i.index_type != 'CLUSTER'
        --
        UNION ALL
        --
        SELECT 'LOBS'                     AS segment_group
        ,      NVL(s.bytes,0)             AS segment_bytes
        ,      l.owner                    AS table_owner
        ,      l.table_name               AS table_name
        ,      l.partition_position       AS table_partition_position
        ,      l.subpartition_position    AS table_subpartition_position
        ,      NULL                       AS table_partition_high_value
        ,      NULL                       AS table_subpartition_high_value
        ,      NULL                       AS table_rows
        ,      NULL                       AS table_partition_rows
        ,      NULL                       AS table_subpartition_rows
        FROM   lob_data                   l
               LEFT OUTER JOIN
               dba_segments               s
               ON (    l.owner            = s.owner
                   AND l.lob_name         = s.segment_name
                   AND COALESCE(l.lob_subpartition_name, l.lob_partition_name, l.lob_name) = COALESCE(s.partition_name, s.segment_name)
                   AND s.segment_type IN ('LOBSEGMENT', 'LOB PARTITION', 'LOB SUBPARTITION') )
        )
,    segment_sizes AS (
        SELECT s.segment_group
        ,      MAX(NVL2(s.table_partition_position, s.table_partition_rows, s.table_rows)) OVER (
                  PARTITION BY s.table_owner, s.table_name, s.table_partition_position) AS table_partition_rows
        ,      MAX(s.table_subpartition_rows) OVER (
                  PARTITION BY s.table_owner, s.table_name, s.table_partition_position, s.table_subpartition_position) AS table_subpartition_rows
        ,      s.table_partition_position
        ,      s.table_subpartition_position
        ,      s.table_partition_high_value
        ,      s.table_subpartition_high_value
        ,      SUM(s.segment_bytes) OVER (
                  PARTITION BY s.table_owner, s.table_name, s.table_partition_position) AS table_partition_bytes
        ,      SUM(s.segment_bytes) OVER (
                  PARTITION BY s.table_owner, s.table_name, s.table_partition_position, s.table_subpartition_position) AS table_subpartition_bytes
        ,      COUNT(DISTINCT s.table_partition_position) OVER (
                  PARTITION BY s.table_owner, s.table_name) AS table_partition_segments
        ,      COUNT(s.table_subpartition_position) OVER (
                  PARTITION BY s.table_owner, s.table_name) AS table_subpartition_segments
        ,      SUM(NVL2(s.table_partition_position, 0, s.segment_bytes)) OVER (
                  PARTITION BY s.table_owner, s.table_name) AS table_global_index_bytes
        ,      ROW_NUMBER() OVER (
                  PARTITION BY s.segment_group, s.table_owner, s.table_name, s.table_partition_position
                  ORDER BY CASE
                              WHEN s.table_subpartition_high_value IS NOT NULL
                              THEN 1
                              WHEN s.table_partition_high_value IS NOT NULL
                              THEN 2
                              ELSE 3
                           END, s.table_subpartition_position) AS table_partition_rn
        FROM   segment_mapping s
        )
SELECT CASE :incremental_range
          WHEN 'SUBPARTITION'
          THEN s.table_subpartition_high_value
          ELSE s.table_partition_high_value
       END AS high_value
,      CASE :incremental_range
          WHEN 'SUBPARTITION'
          THEN s.table_subpartition_rows
          ELSE s.table_partition_rows
       END AS num_rows
,      CASE :incremental_range
          WHEN 'SUBPARTITION'
          THEN s.table_subpartition_bytes + CASE
                                               WHEN s.table_subpartition_position IS NOT NULL
                                               THEN (s.table_global_index_bytes/s.table_subpartition_segments)
                                               ELSE 0
                                            END
          ELSE s.table_partition_bytes + CASE
                                            WHEN s.table_partition_position IS NOT NULL
                                            THEN (s.table_global_index_bytes/s.table_partition_segments)
                                            ELSE 0
                                         END
       END AS bytes
FROM   segment_sizes s
WHERE  s.segment_group = 'TABLES'
AND    CASE :incremental_range
          WHEN 'SUBPARTITION'
          THEN 1
          ELSE s.table_partition_rn
       END = 1
ORDER  BY
       s.table_partition_position
,      s.table_subpartition_position"""

        binds = {
            "source_owner": offloaded_table[SOURCE_OWNER],
            "source_table": offloaded_table[SOURCE_TABLE],
            "source_iot_type": offloaded_table[SOURCE_IOT_TYPE],
            "incremental_range": offloaded_table[INCREMENTAL_RANGE],
        }

        self._messages.debug("SQL: %s" % sql, detail=SUPPRESS_STDOUT)
        self._messages.debug("Binds: %s" % binds, detail=SUPPRESS_STDOUT)

        rows = self._ora_service.execute(sql, binds=binds, cursor_fn=lambda c: c.fetchall(), as_dict=True)

        self._messages.debug("Fetched %s %s" % (len(rows), plural("row", len(rows))))

        if len(rows) > 0:
            offload_metadata = self._repo_metadata_from_osr_metadata(offloaded_table)
            offload_type = offloaded_table[OFFLOAD_TYPE]
            incremental_predicate_type = offloaded_table[INCREMENTAL_PREDICATE_TYPE]
            if offloaded_table[INCREMENTAL_KEY] and offloaded_table[INCREMENTAL_HIGH_VALUE]:
                table_high_value = self._decode_metadata_incremental_high_values(
                    offload_metadata.incremental_predicate_type,
                    offload_metadata.incremental_key,
                    offload_metadata.incremental_high_value,
                    ost,
                )
                ipa_offload = True
            else:
                table_high_value = None
                ipa_offload = False

            for row in rows:
                if ipa_offload:
                    row_high_value = self._decode_metadata_incremental_high_values(
                        offload_metadata.incremental_predicate_type,
                        offload_metadata.incremental_key,
                        row["HIGH_VALUE"],
                        ost,
                    )
                    partition_offloaded = incremental_partition_match(
                        row_high_value, table_high_value, incremental_predicate_type
                    )
                else:
                    partition_offloaded = None

                if (
                    (offload_type == "INCREMENTAL" and partition_offloaded)
                    or (offload_type == "FULL" and ipa_offload and partition_offloaded)
                    or (offload_type == "FULL" and (not ipa_offload))
                ):
                    rdbms_data[RECLAIMABLE_PARTS] += 1
                    rdbms_data[RECLAIMABLE_BYTES] += row["BYTES"]
                    rdbms_data[RECLAIMABLE_ROWS] += row["NUM_ROWS"]
                else:
                    rdbms_data[RETAINED_PARTS] += 1
                    rdbms_data[RETAINED_BYTES] += row["BYTES"]
                    rdbms_data[RETAINED_ROWS] += row["NUM_ROWS"]

        self._messages.debug("RDBMS space data: %s" % rdbms_data, detail=SUPPRESS_STDOUT)

        return rdbms_data

    def _get_rdbms_objects_data(self, offloaded_table, ost):
        """Return all of the RDBMS objects for an offloaded table. Data includes AAPD objects,
        Incremental Update objects, Join Pushdown objects, dependent views.

        Data format:
            {
              SOURCE_OWNER:                     string
              SOURCE_TABLE:                     string
              AAPD_OBJECTS:                     [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
              JOIN_OBJECTS_RDBMS:               [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
              INCREMENTAL_UPDATE_OBJECTS_RDBMS: [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
              DEPENDENT_OBJECTS:                [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
            }

        Initialise return data...
        """

        rdbms_data = {}
        rdbms_data[SOURCE_OWNER] = offloaded_table[SOURCE_OWNER]
        rdbms_data[SOURCE_TABLE] = offloaded_table[SOURCE_TABLE]
        rdbms_data[AAPD_OBJECTS] = []
        rdbms_data[JOIN_OBJECTS_RDBMS] = []
        rdbms_data[INCREMENTAL_UPDATE_OBJECTS_RDBMS] = []
        rdbms_data[DEPENDENT_OBJECTS] = []

        if self._output_level == DETAIL_LEVEL:
            self._messages.detail(
                "Get RDBMS objects data for offloaded table: %s"
                % self._format_table_name(offloaded_table[SOURCE_OWNER], offloaded_table[SOURCE_TABLE])
            )

            self._messages.debug("RDBMS objects data: %s" % rdbms_data, detail=SUPPRESS_STDOUT)

        else:
            self._messages.detail("RDBMS objects data collection skipped in summary mode")

        return rdbms_data

    def _repo_metadata_from_osr_metadata(self, offloaded_table):
        """Because this tool reads metadata en-masse from offload_objects we convert
        the OSR metadata back to true metadata here.
        """
        new_metadata_dict = copy(offloaded_table)
        new_metadata_dict["OFFLOADED_OWNER"] = offloaded_table[SOURCE_OWNER]
        new_metadata_dict["OFFLOADED_TABLE"] = offloaded_table[SOURCE_TABLE]
        new_metadata_dict["HADOOP_OWNER"] = offloaded_table[OFFLOAD_OWNER]
        new_metadata_dict["HADOOP_TABLE"] = offloaded_table[OFFLOAD_TABLE]
        return OrchestrationMetadata(new_metadata_dict, client=self._repo_client)

    def _get_offload_data(self, offloaded_table, rdbms_join_objects):
        """Return the offload data for an offloaded table. Data includes space and partitions
        offloaded to the backend. Also adds any materialized offload objects to the dataset.

        Data format:
            {
              SOURCE_OWNER:                       string
              SOURCE_TABLE:                       string
              OFFLOADED_BYTES:                    int
              OFFLOADED_PARTS:                    int
              OFFLOADED_ROWS:                     int
              OFFLOADED_TABLES:                   int
              OFFLOAD_PART_KEY:                   string
              OFFLOAD_TABLE_EXISTS:               boolean
              INCREMENTAL_UPDATE_METHOD:          string
              INCREMENTAL_UPDATE_OBJECTS_OFFLOAD: [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
              JOIN_OBJECTS_OFFLOAD:               [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
            }

        Initialise return data... Build a backend table instance to get access to Incremental Update information... We re-use the existing backend_api to avoid unnecessary connections. This will replace the Oracle-side metadata for backend owner/table with the backend format... Since adding BigQuery support, not all offloaded tables will be partitioned... Add in any materialized join objects...
        """
        self._messages.detail(
            "Get offload data for offloaded table: %s"
            % self._format_table_name(offloaded_table[SOURCE_OWNER], offloaded_table[SOURCE_TABLE])
        )

        offload_data = {}
        offload_data[SOURCE_OWNER] = offloaded_table[SOURCE_OWNER]
        offload_data[SOURCE_TABLE] = offloaded_table[SOURCE_TABLE]
        offload_data[OFFLOADED_BYTES] = 0
        offload_data[OFFLOADED_PARTS] = 0
        offload_data[OFFLOADED_ROWS] = 0
        offload_data[OFFLOADED_TABLES] = 0
        offload_data[OFFLOAD_TABLE_EXISTS] = None
        offload_data[OFFLOAD_PART_KEY] = None
        offload_data[INCREMENTAL_UPDATE_METHOD] = None
        offload_data[INCREMENTAL_UPDATE_OBJECTS_OFFLOAD] = []
        offload_data[JOIN_OBJECTS_OFFLOAD] = []

        db, table = offloaded_table[OFFLOAD_OWNER], offloaded_table[OFFLOAD_TABLE]
        table_metadata = self._repo_metadata_from_osr_metadata(offloaded_table)
        offload_table = create_backend_table(
            db,
            table,
            self._backend_db_type,
            self._orchestration_config,
            self._messages,
            hybrid_metadata=table_metadata,
            dry_run=bool(not self._execute),
            existing_backend_api=self._backend_api,
        )
        self._messages.debug("Fetched details for offload table/view", detail=SUPPRESS_STDOUT)

        if offload_table.exists():
            offload_data[OFFLOAD_OWNER] = offload_table.db_name
            offload_data[OFFLOAD_TABLE] = offload_table.table_name
            offload_data[OFFLOAD_TABLE_EXISTS] = True
            offload_data[OFFLOADED_TABLES] = 1
            self._messages.debug(
                "Offload table/view: %s"
                % self._format_table_name(offload_data[OFFLOAD_OWNER], offload_data[OFFLOAD_TABLE])
            )
            offload_parts = offload_table.get_table_partitions()

            table_size, table_row_count = offload_table.get_table_size_and_row_count()
            offload_data[OFFLOADED_BYTES] += table_size or 0
            offload_data[OFFLOADED_ROWS] += table_row_count or 0

            if offload_parts:
                self._messages.debug("Offload table has %s partitions" % len(offload_parts))
                self._messages.debug("Offload partitions: %s" % offload_parts, detail=SUPPRESS_STDOUT)
                offload_data[OFFLOADED_PARTS] += len(offload_parts)
                backend_part_col_names = [_.name for _ in offload_table.get_partition_columns()]
                offload_data[OFFLOAD_PART_KEY] = ", ".join(backend_part_col_names)
                self._messages.debug(
                    "Offload partition key: %s" % backend_part_col_names,
                    detail=SUPPRESS_STDOUT,
                )
            else:
                offload_data[OFFLOADED_PARTS] = 1
                self._messages.debug("Offload table is not partitioned")

            if self._output_level == DETAIL_LEVEL:
                for join_object in rdbms_join_objects:
                    if join_object[OBJECT_TYPE_GOE] == "JOIN_VIEW":
                        db, table = (
                            offload_data[OFFLOAD_OWNER],
                            join_object[OBJECT_NAME],
                        )
                        backend_api = offload_table.get_backend_api()
                        if backend_api.exists(db, table):
                            object_type = "VIEW" if backend_api.is_view(db, table) else "TABLE"
                            offload_data[JOIN_OBJECTS_OFFLOAD].append(
                                {
                                    OBJECT_OWNER: db,
                                    OBJECT_NAME: table,
                                    OBJECT_TYPE_DB: object_type,
                                    OBJECT_TYPE_GOE: "JOIN_%s" % object_type,
                                }
                            )
                        else:
                            self._messages.debug(
                                "Unable to find corresponding offload join object for %s"
                                % self._format_table_name(join_object[OBJECT_OWNER], join_object[OBJECT_NAME]),
                                detail=SUPPRESS_STDOUT,
                            )
            else:
                self._messages.debug("Skipped Join Objects data collection in summary mode")

        else:
            offload_data[OFFLOAD_TABLE_EXISTS] = False
            offload_data[OFFLOADED_TABLES] = 0
            self._messages.debug(
                "Offload table/view %s does not exist"
                % self._format_table_name(offloaded_table[OFFLOAD_OWNER], offloaded_table[OFFLOAD_TABLE])
            )

        self._messages.debug("Offload data: %s" % offload_data, detail=SUPPRESS_STDOUT)

        return offload_data

    def _get_table_data(self, offloaded_tables):
        """Get the RDBMS and backend table data for a set of target tables, ready for processing.
        Returns a list of dicts.
        Data format:
                [  {
                        SOURCE_OWNER:                       string
                        SOURCE_TABLE:                       string
                        OFFLOADED_PARTS:                    int
                        OFFLOADED_TABLES:                   int
                        OFFLOADED_BYTES:                    int
                        OFFLOADED_ROWS:                     int
                        RETAINED_BYTES:                     int
                        RETAINED_PARTS:                     int
                        RETAINED_ROWS:                      int
                        RECLAIMABLE_BYTES:                  int
                        RECLAIMABLE_PARTS:                  int
                        RECLAIMABLE_ROWS:                   int
                        OFFLOAD_TYPE:                       string
                        OFFLOAD_OWNER:                      string
                        OFFLOAD_TABLE:                      string
                        OFFLOAD_PART_KEY:                   string
                        OFFLOAD_TABLE_EXISTS:               boolean
                        HYBRID_OWNER:                       string
                        HYBRID_VIEW:                        string
                        HYBRID_VIEW_TYPE:                   string
                        HYBRID_EXTERNAL_TABLE:              string
                        INCREMENTAL_KEY:                    string
                        INCREMENTAL_HIGH_VALUE:             string
                        INCREMENTAL_RANGE:                  string
                        INCREMENTAL_PREDICATE_TYPE:         string
                        INCREMENTAL_PREDICATE_VALUE:        string
                        INCREMENTAL_UPDATE_METHOD:          string
                        OFFLOAD_BUCKET_COLUMN:              string
                        OFFLOAD_BUCKET_METHOD:              string
                        OFFLOAD_BUCKET_COUNT:               string
                        OFFLOAD_VERSION:                    string
                        OFFLOAD_SORT_COLUMNS:               string
                        OFFLOAD_PARTITION_FUNCTIONS:        string
                        AAPD_OBJECTS:                       [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
                        JOIN_OBJECTS_RDBMS:                 [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
                        JOIN_OBJECTS_OFFLOAD:               [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
                        INCREMENTAL_UPDATE_OBJECTS_RDBMS:   [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
                        INCREMENTAL_UPDATE_OBJECTS_OFFLOAD: [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
                        DEPENDENT_OBJECTS:                  [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]
                    },
                    {
                        ...etc...
                    } ]

        Populate the RDBMS and backend dataset, table-by-table... Prepare table data from offloaded table metadata, rdbms_data, offload_data and JSON-converted predicates...
        """

        def get_offload_source_table(offloaded_table):
            conn_options = SimpleNamespace(
                db_type=self._db_type,
                ora_adm_user=self._ora_adm_user,
                ora_adm_pass=self._ora_adm_pass,
                rdbms_dsn=self._oracle_dsn,
                use_oracle_wallet=self._use_oracle_wallet,
            )
            return create_source_table(
                offloaded_table[SOURCE_OWNER],
                offloaded_table[SOURCE_TABLE],
                conn_options,
                self._messages,
                conn=self._ora_conn,
            )

        table_data = []
        offloaded_count = len(offloaded_tables)
        self._messages.log(
            "Fetching report data for %s offloaded %s" % (offloaded_count, plural("table", offloaded_count)),
            detail=VERBOSE,
        )

        for n, offloaded_table in enumerate(offloaded_tables, 1):
            qualified_table_name = self._format_table_name(offloaded_table[SOURCE_OWNER], offloaded_table[SOURCE_TABLE])
            progress_message = "Fetching %s of %s" % (n, offloaded_count)
            self._set_action(qualified_table_name)
            self._set_client_info(progress_message)
            self._messages.log("%s: %s" % (progress_message, qualified_table_name), detail=VVERBOSE)

            ost = get_offload_source_table(offloaded_table)

            rdbms_objects_data = self._get_rdbms_objects_data(offloaded_table, ost)
            self._messages.debug("Fetched RDBMS objects data")

            offload_data = self._get_offload_data(offloaded_table, rdbms_objects_data[JOIN_OBJECTS_RDBMS])
            self._messages.debug("Fetched offload data")

            rdbms_space_data = self._get_rdbms_space_data(offloaded_table, offload_data, ost)
            self._messages.debug("Fetched RDBMS space data")

            offloaded_table.update(rdbms_space_data)
            offloaded_table.update(rdbms_objects_data)
            offloaded_table.update(offload_data)
            offloaded_table.pop(SOURCE_IOT_TYPE, None)
            if offloaded_table[INCREMENTAL_PREDICATE_VALUE]:
                offloaded_table[INCREMENTAL_PREDICATE_VALUE] = json.loads(offloaded_table[INCREMENTAL_PREDICATE_VALUE])
            table_data.append(offloaded_table)

            self._messages.debug("RDBMS and offload data merged for %s" % qualified_table_name)
            self._messages.debug("Merged data: %s" % offloaded_table, detail=SUPPRESS_STDOUT)

        self._messages.debug("Table data: %s" % table_data, detail=SUPPRESS_STDOUT)
        return table_data

    def _process_report_data(self, table_data):
        """Formats a list of pre-processed table data into the final reporting data model.

        Data format:
        {
            OFFLOADED_TABLES:  int    -- report summary
            OFFLOADED_PARTS:   int
            OFFLOADED_BYTES:   int
            OFFLOADED_ROWS:    int
            RETAINED_BYTES:    int
            RETAINED_PARTS:    int
            RETAINED_ROWS:     int
            RECLAIMABLE_BYTES: int
            RECLAIMABLE_PARTS: int
            RECLAIMABLE_ROWS:  int
            'SCHEMA_1':         {
                                    OFFLOADED_TABLES:  int    -- schema summary
                                    OFFLOADED_PARTS:   int
                                    OFFLOADED_BYTES:   int
                                    OFFLOADED_ROWS:    int
                                    RETAINED_BYTES:    int
                                    RETAINED_PARTS:    int
                                    RETAINED_ROWS:     int
                                    RECLAIMABLE_BYTES: int
                                    RECLAIMABLE_PARTS: int
                                    RECLAIMABLE_ROWS:  int
                                    'TABLE_1':          {
                                                            OFFLOADED_TABLES:                   int      -- table summary
                                                            OFFLOADED_PARTS:                    int
                                                            OFFLOADED_BYTES:                    int
                                                            OFFLOADED_ROWS:                     int
                                                            RETAINED_BYTES:                     int
                                                            RETAINED_PARTS:                     int
                                                            RETAINED_ROWS:                      int
                                                            RECLAIMABLE_BYTES:                  int
                                                            RECLAIMABLE_PARTS:                  int
                                                            RECLAIMABLE_ROWS:                   int
                                                            SOURCE_OWNER:                       string   -- detail level only
                                                            SOURCE_TABLE:                       string   -- detail level only
                                                            OFFLOAD_TYPE:                       string   -- detail level only
                                                            OFFLOAD_OWNER:                      string   -- detail level only
                                                            OFFLOAD_TABLE:                      string   -- detail level only
                                                            OFFLOAD_PART_KEY:                   string   -- detail level only
                                                            OFFLOAD_TABLE_EXISTS:               boolean  -- detail level only
                                                            HYBRID_OWNER:                       string   -- detail level only
                                                            HYBRID_VIEW:                        string   -- detail level only
                                                            HYBRID_VIEW_TYPE:                   string   -- detail level only
                                                            HYBRID_EXTERNAL_TABLE:              string   -- detail level only
                                                            INCREMENTAL_KEY:                    string   -- detail level only
                                                            INCREMENTAL_HIGH_VALUE:             string   -- detail level only
                                                            INCREMENTAL_RANGE:                  string   -- detail level only
                                                            INCREMENTAL_PREDICATE_TYPE:         string   -- detail level only
                                                            INCREMENTAL_PREDICATE_VALUE:        string   -- detail level only
                                                            INCREMENTAL_UPDATE_METHOD:          string   -- detail level only
                                                            OFFLOAD_BUCKET_COLUMN:              string   -- detail level only
                                                            OFFLOAD_BUCKET_METHOD:              string   -- detail level only
                                                            OFFLOAD_BUCKET_COUNT:               string   -- detail level only
                                                            OFFLOAD_VERSION:                    string   -- detail level only
                                                            OFFLOAD_SORT_COLUMNS:               string   -- detail level only
                                                            OFFLOAD_PARTITION_FUNCTIONS:        string   -- detail level only
                                                            AAPD_OBJECTS:                       [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]  -- detail level only
                                                            JOIN_OBJECTS_RDBMS:                 [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]  -- detail level only
                                                            JOIN_OBJECTS_OFFLOAD:               [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]  -- detail level only
                                                            INCREMENTAL_UPDATE_OBJECTS_RDBMS:   [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]  -- detail level only
                                                            INCREMENTAL_UPDATE_OBJECTS_OFFLOAD: [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]  -- detail level only
                                                            DEPENDENT_OBJECTS:                  [ { OBJECT_OWNER: string, OBJECT_NAME: string, OBJECT_TYPE_DB: string, OBJECT_TYPE_GOE: string } ]  -- detail level only
                                                        }
                                    'TABLE_2':          {
                                                            ...as TABLE_1...
                                                        }
                                }
            'SCHEMA_2':         {
                                    ...as SCHEMA_2...
                                }
        }

        Summarise the data and process it into final data model... remove detail attributes from dict if in summary mode add table to schema dict (each table includes its own summary total) add summary total to schema dict (each schema has its own summary total) add summary total to report dict (the entire report, i.e. all schemas/tables, has its own summary total)
        """

        def update_summary(summary_data, detail_data):
            summary_data[OFFLOADED_TABLES] += detail_data[OFFLOADED_TABLES]
            summary_data[OFFLOADED_BYTES] += detail_data[OFFLOADED_BYTES]
            summary_data[OFFLOADED_PARTS] += detail_data[OFFLOADED_PARTS]
            summary_data[OFFLOADED_ROWS] += detail_data[OFFLOADED_ROWS]
            summary_data[RETAINED_BYTES] += detail_data[RETAINED_BYTES]
            summary_data[RETAINED_PARTS] += detail_data[RETAINED_PARTS]
            summary_data[RETAINED_ROWS] += detail_data[RETAINED_ROWS]
            summary_data[RECLAIMABLE_BYTES] += detail_data[RECLAIMABLE_BYTES]
            summary_data[RECLAIMABLE_PARTS] += detail_data[RECLAIMABLE_PARTS]
            summary_data[RECLAIMABLE_ROWS] += detail_data[RECLAIMABLE_ROWS]
            return summary_data

        report_data = self._initialise_summary_dict()
        table_count = len(table_data)
        self._messages.log(
            "Processing report data for %s offloaded %s" % (table_count, plural("table", table_count)),
            detail=VERBOSE,
        )

        for n, table_data in enumerate(table_data, 1):
            schema, table = table_data[SOURCE_OWNER], table_data[SOURCE_TABLE]
            qualified_table_name = self._format_table_name(schema, table)
            self._messages.log(
                "Processing %s of %s: %s" % (n, table_count, qualified_table_name),
                detail=VVERBOSE,
            )

            if schema not in report_data:
                report_data[schema] = self._initialise_summary_dict()
                self._messages.debug("Initializing new schema %s:" % schema, detail=SUPPRESS_STDOUT)

            if self._output_level == SUMMARY_LEVEL:
                table_data = self._strip_detail(table_data)
            report_data[schema][table] = table_data
            self._messages.debug("Added %s to %s:" % (table, schema), detail=SUPPRESS_STDOUT)
            update_summary(report_data[schema], table_data)
            self._messages.debug(
                "Added %s summary to %s summary:" % (table, schema),
                detail=SUPPRESS_STDOUT,
            )
            update_summary(report_data, table_data)
            self._messages.debug("Added %s summary to report summary:" % table, detail=SUPPRESS_STDOUT)

            self._messages.debug("Final processed report data: %s" % report_data, detail=SUPPRESS_STDOUT)

        return report_data


def normalise_offload_status_report_options(options):
    if options.vverbose:
        options.verbose = True
    elif options.quiet:
        options.vverbose = options.verbose = False

    if not os.path.exists(options.report_directory):
        raise OffloadOptionError(
            "Invalid value specified for --report-directory parameter. Directory %s does not exist."
            % options.report_directory
        )

    if len(options.csv_delimiter) > 1:
        raise OffloadOptionError(
            "Invalid value specified for --csv-delimiter parameter (%s). Delimiter must be a single character."
            % options.csv_delimiter
        )

    if len(options.csv_enclosure) > 1:
        raise OffloadOptionError(
            "Invalid value specified for --csv-enclosure parameter (%s). Enclosure must be a single character or NULL."
            % options.csv_enclosure
        )


def offload_status_report_run(options: StatusReportOptions) -> None:
    try:
        init(options)
        init_log("offload_status_report")

        log("")
        log("Offload Status Report v%s" % version(), ansi_code="underline")
        log("Log file: %s" % get_log_fh_name())
        log("", VERBOSE)
        log_command_line()

        normalise_offload_status_report_options(options)
        messages = OffloadMessages.from_options(
            options,
            log_fh=get_log_fh(),
            command_type=orchestration_constants.COMMAND_OSR,
        )
        orchestration_config = OrchestrationConfig.from_dict({"verbose": options.verbose, "vverbose": options.vverbose})
        frontend_api = create_frontend_api(
            orchestration_config.db_type,
            orchestration_config,
            messages,
            dry_run=True,
            do_not_connect=True,
        )
        if not frontend_api.goe_offload_status_report_supported():
            raise OffloadStatusReportException(
                "Offload Status Report is not supported for frontend system: %s" % frontend_api.frontend_db_name()
            )

        osr = OffloadStatusReport(orchestration_config, messages)
        report_data = osr.get_offload_status_report_data(
            options.schema, options.table, options.output_level, options.demo_mode
        )
        status = osr.gen_offload_status_report(
            report_data,
            options.output_format,
            options.report_name,
            options.report_directory,
            options.csv_delimiter,
            options.csv_enclosure,
        )

        sys.exit(status)

    except OffloadOptionError as exc:
        log("Option error: %s" % exc.detail, ansi_code="red")
        log("")
        sys.exit(FAILURE)
    except Exception as exc:
        log("Exception caught at top-level", ansi_code="red")
        log_timestamp()
        log_exception(exc, log_fh=get_log_fh(), options=options)
        sys.exit(1)
