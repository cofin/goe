# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Batched StatusReportService with concurrent collection, DuckDB rollup, and compressed demo fixture."""

import gzip
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from goe.config.orchestration_config import OrchestrationConfig
from goe.exceptions import OffloadOptionError
from goe.goe import (
    get_log_fh,
    get_log_fh_name,
    init,
    init_log,
    log,
    log_command_line,
    log_timestamp,
    version,
)
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
from goe.offload.registry import (
    create_backend_api,
    create_frontend_api,
    create_repository_client,
)
from goe.orchestration import command_steps, orchestration_constants
from goe.report.models import (
    CSV,
    DEFAULT_CSV_DELIMITER,
    DEFAULT_CSV_ENCLOSURE,
    DEFAULT_DEMO_MODE,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_OUTPUT_LEVEL,
    DEFAULT_REPORT_DIRECTORY,
    DEFAULT_REPORT_NAME,
    DETAIL_LEVEL,
    FAILURE,
    HTML,
    JSON,
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
    SOURCE_OWNER,
    SOURCE_TABLE,
    SUMMARY_LEVEL,
    TEXT,
    OffloadStatusReportException,
    PartitionStatusRow,
    StatusReportEnvelope,
    TableStatusReport,
)
from goe.report.renderers import ReportRenderersMixin
from goe.serializers import decode_json
from goe.util.concurrency import run_bounded
from goe.util.goe_log import log_exception
from goe.util.string_utils import plural

if TYPE_CHECKING:
    from goe.config.options import StatusReportOptions

__all__ = (
    "DEMO_FIXTURE_PATH",
    "OffloadStatusReport",
    "StatusReportService",
    "normalise_offload_status_report_options",
    "offload_status_report_run",
)

DEMO_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "demo_report.json.gz"

type MetadataFetcherFn = Callable[[str | None, str | None], list[dict[str, Any]]]


class StatusReportService:
    """Collect and aggregate offload status report metrics concurrently with DuckDB rollup."""

    def __init__(
        self,
        *,
        source_fetcher: MetadataFetcherFn | None = None,
        target_fetcher: MetadataFetcherFn | None = None,
    ) -> None:
        self._source_fetcher = source_fetcher
        self._target_fetcher = target_fetcher

    def collect_report(
        self,
        *,
        schema: str | None = None,
        table: str | None = None,
        database_name: str = "DEMO_DB",
        demo_mode: bool = False,
    ) -> StatusReportEnvelope:
        """Collect source and target partition metrics concurrently and aggregate via DuckDB."""
        if demo_mode and self._source_fetcher is None and self._target_fetcher is None:
            return self.load_demo_envelope(schema=schema, table=table, database_name=database_name)

        def _fetch_src() -> list[dict[str, Any]]:
            return self._source_fetcher(schema, table) if self._source_fetcher else []

        def _fetch_tgt() -> list[dict[str, Any]]:
            return self._target_fetcher(schema, table) if self._target_fetcher else []

        fetched = run_bounded([_fetch_src, _fetch_tgt], max_workers=2)
        src_rows, tgt_rows = fetched[0], fetched[1]
        return self._aggregate_in_duckdb(
            source_rows=src_rows,
            target_rows=tgt_rows,
            database_name=database_name,
        )

    @staticmethod
    def load_demo_table_data(
        schema: str | None = None,
        table: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load synthetic demo table records from the compressed demo_report.json.gz fixture."""
        if not DEMO_FIXTURE_PATH.exists():
            return []
        with gzip.open(DEMO_FIXTURE_PATH, "rb") as fh:
            payload = decode_json(fh.read())
        rows: list[dict[str, Any]] = list(payload) if isinstance(payload, list) else []
        if schema:
            schema_upper = schema.upper()
            rows = [r for r in rows if str(r.get(SOURCE_OWNER, "")).upper() == schema_upper]
        if table:
            table_upper = table.upper()
            rows = [r for r in rows if str(r.get(SOURCE_TABLE, "")).upper() == table_upper]
        return rows

    @classmethod
    def load_demo_envelope(
        cls,
        *,
        schema: str | None = None,
        table: str | None = None,
        database_name: str = "DEMO_DB",
    ) -> StatusReportEnvelope:
        """Load the compressed demo fixture into a structured StatusReportEnvelope."""
        raw_tables = cls.load_demo_table_data(schema=schema, table=table)
        tables: list[TableStatusReport] = []
        total_src_bytes = 0
        total_off_bytes = 0
        total_rec_bytes = 0
        for row in raw_tables:
            retained_bytes = int(row.get(RETAINED_BYTES, 0) or 0)
            reclaimable_bytes = int(row.get(RECLAIMABLE_BYTES, 0) or 0)
            offloaded_bytes = int(row.get(OFFLOADED_BYTES, 0) or 0)
            retained_rows = int(row.get(RETAINED_ROWS, 0) or 0)
            reclaimable_rows = int(row.get(RECLAIMABLE_ROWS, 0) or 0)
            offloaded_rows = int(row.get(OFFLOADED_ROWS, 0) or 0)
            src_bytes = retained_bytes + reclaimable_bytes
            src_rows = retained_rows + reclaimable_rows
            total_src_bytes += src_bytes
            total_off_bytes += offloaded_bytes
            total_rec_bytes += reclaimable_bytes
            tables.append(
                TableStatusReport(
                    schema_name=str(row.get(SOURCE_OWNER, "")),
                    table_name=str(row.get(SOURCE_TABLE, "")),
                    target_schema=str(row.get("OFFLOAD_OWNER", "")),
                    target_table=str(row.get("OFFLOAD_TABLE", "")),
                    offload_type=str(row.get("OFFLOAD_TYPE", "FULL")),
                    incremental_key=row.get("INCREMENTAL_KEY"),
                    incremental_high_value=row.get("INCREMENTAL_HIGH_VALUE"),
                    incremental_predicate_type=row.get("INCREMENTAL_PREDICATE_TYPE"),
                    source_rows=src_rows,
                    source_bytes=src_bytes,
                    offloaded_rows=offloaded_rows,
                    offloaded_bytes=offloaded_bytes,
                    reclaimable_rows=reclaimable_rows,
                    reclaimable_bytes=reclaimable_bytes,
                )
            )
        return StatusReportEnvelope(
            generated_at=datetime.now(tz=UTC).isoformat(),
            database_name=database_name,
            total_tables=len(tables),
            total_source_bytes=total_src_bytes,
            total_offloaded_bytes=total_off_bytes,
            total_reclaimable_bytes=total_rec_bytes,
            tables=tuple(tables),
        )

    @staticmethod
    def run_from_options(options: "StatusReportOptions") -> None:
        """Execute the Offload Status Report CLI flow from StatusReportOptions."""
        offload_status_report_run(options)

    @staticmethod
    def _aggregate_in_duckdb(
        *,
        source_rows: Sequence[Mapping[str, Any]],
        target_rows: Sequence[Mapping[str, Any]],
        database_name: str,
    ) -> StatusReportEnvelope:
        """Compute per-table and rollup status metrics in an in-memory DuckDB instance."""
        target_by_part: dict[tuple[str, str, str], Mapping[str, Any]] = {}
        for trow in target_rows:
            tkey = (
                str(trow.get("schema_name", "")).upper(),
                str(trow.get("table_name", "")).upper(),
                str(trow.get("partition_name", "")).upper(),
            )
            target_by_part[tkey] = trow

        grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for srow in source_rows:
            gkey = (
                str(srow.get("schema_name", "")).upper(),
                str(srow.get("table_name", "")).upper(),
            )
            grouped.setdefault(gkey, []).append(srow)

        part_tuples: list[tuple[str, str, int, int, int, int, int, int]] = []
        tables: list[TableStatusReport] = []

        for (schema_name, table_name), rows in sorted(grouped.items()):
            first = rows[0]
            target_schema = str(first.get("target_schema", schema_name.lower()))
            target_table = str(first.get("target_table", table_name.lower()))
            offload_type = str(first.get("offload_type", "FULL"))
            inc_key = first.get("incremental_key")
            inc_hv = first.get("incremental_high_value")
            inc_pred_type = first.get("incremental_predicate_type")

            part_structs: list[PartitionStatusRow] = []
            for r in rows:
                pname = str(r.get("partition_name", "ALL"))
                tmatch = target_by_part.get((schema_name, table_name, pname.upper()), {})
                offloaded = bool(r.get("offloaded", False))
                s_rows = int(r.get("source_rows", 0) or 0)
                s_bytes = int(r.get("source_bytes", 0) or 0)
                t_rows = int(tmatch.get("target_rows", r.get("target_rows", 0)) or 0)
                t_bytes = int(tmatch.get("target_bytes", r.get("target_bytes", 0)) or 0)
                rec_rows = s_rows if offloaded else 0
                rec_bytes = s_bytes if offloaded else 0
                part_structs.append(
                    PartitionStatusRow(
                        partition_name=pname,
                        high_value=r.get("high_value"),
                        offloaded=offloaded,
                        source_rows=s_rows,
                        source_bytes=s_bytes,
                        target_rows=t_rows,
                        target_bytes=t_bytes,
                    )
                )
                part_tuples.append((schema_name, table_name, s_rows, s_bytes, t_rows, t_bytes, rec_rows, rec_bytes))

            tables.append(
                TableStatusReport(
                    schema_name=schema_name,
                    table_name=table_name,
                    target_schema=target_schema,
                    target_table=target_table,
                    offload_type=offload_type,
                    incremental_key=inc_key,
                    incremental_high_value=inc_hv,
                    incremental_predicate_type=inc_pred_type,
                    partitions=tuple(part_structs),
                )
            )

        if not part_tuples:
            return StatusReportEnvelope(
                generated_at=datetime.now(tz=UTC).isoformat(),
                database_name=database_name,
                total_tables=0,
                total_source_bytes=0,
                total_offloaded_bytes=0,
                total_reclaimable_bytes=0,
                tables=(),
            )

        conn = duckdb.connect(":memory:")
        try:
            conn.execute(
                "CREATE TABLE part_metrics ("
                "schema_name VARCHAR, table_name VARCHAR, "
                "s_rows BIGINT, s_bytes BIGINT, t_rows BIGINT, t_bytes BIGINT, "
                "rec_rows BIGINT, rec_bytes BIGINT)"
            )
            conn.executemany("INSERT INTO part_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?)", part_tuples)
            rollup_rows = conn.execute(
                "SELECT schema_name, table_name, "
                "CAST(SUM(s_rows) AS BIGINT), CAST(SUM(s_bytes) AS BIGINT), "
                "CAST(SUM(t_rows) AS BIGINT), CAST(SUM(t_bytes) AS BIGINT), "
                "CAST(SUM(rec_rows) AS BIGINT), CAST(SUM(rec_bytes) AS BIGINT) "
                "FROM part_metrics "
                "GROUP BY ROLLUP (schema_name, table_name)"
            ).fetchall()
        finally:
            conn.close()

        table_totals: dict[tuple[str, str], tuple[int, int, int, int, int, int]] = {}
        grand_totals = (0, 0, 0, 0, 0, 0)
        for s_name, t_name, sr, sb, tr, tb, rr, rb in rollup_rows:
            if s_name is None and t_name is None:
                grand_totals = (int(sr or 0), int(sb or 0), int(tr or 0), int(tb or 0), int(rr or 0), int(rb or 0))
            elif s_name is not None and t_name is not None:
                table_totals[(str(s_name), str(t_name))] = (
                    int(sr or 0),
                    int(sb or 0),
                    int(tr or 0),
                    int(tb or 0),
                    int(rr or 0),
                    int(rb or 0),
                )

        populated_tables: list[TableStatusReport] = []
        for tbl in tables:
            sr, sb, tr, tb, rr, rb = table_totals.get((tbl.schema_name, tbl.table_name), (0, 0, 0, 0, 0, 0))
            populated_tables.append(
                TableStatusReport(
                    schema_name=tbl.schema_name,
                    table_name=tbl.table_name,
                    target_schema=tbl.target_schema,
                    target_table=tbl.target_table,
                    offload_type=tbl.offload_type,
                    incremental_key=tbl.incremental_key,
                    incremental_high_value=tbl.incremental_high_value,
                    incremental_predicate_type=tbl.incremental_predicate_type,
                    source_rows=sr,
                    source_bytes=sb,
                    offloaded_rows=tr,
                    offloaded_bytes=tb,
                    reclaimable_rows=rr,
                    reclaimable_bytes=rb,
                    partitions=tbl.partitions,
                )
            )

        return StatusReportEnvelope(
            generated_at=datetime.now(tz=UTC).isoformat(),
            database_name=database_name,
            total_tables=len(populated_tables),
            total_source_bytes=grand_totals[1],
            total_offloaded_bytes=grand_totals[3],
            total_reclaimable_bytes=grand_totals[5],
            tables=tuple(populated_tables),
        )


class OffloadStatusReport(ReportRenderersMixin):
    """Generate Offload Status Report data and formatted output artifacts."""

    _execute: bool = True

    def __init__(self, orchestration_config: Any, messages: Any, ora_adm_conn: Any = None) -> None:
        self._messages = messages
        self._orchestration_config = orchestration_config
        self._backend_api = create_backend_api(
            self._orchestration_config.target,
            self._orchestration_config,
            self._messages,
            dry_run=(not self._execute),
        )
        self._backend_info = self._backend_api.backend_report_info()
        self._backend_db_type = self._orchestration_config.target
        self._ora_adm_user = self._orchestration_config.ora_adm_user
        self._ora_adm_pass = self._orchestration_config.ora_adm_pass
        self._oracle_dsn = self._orchestration_config.oracle_dsn
        self._use_oracle_wallet = self._orchestration_config.use_oracle_wallet
        self._ora_db_name = getattr(self._orchestration_config, "db_name_prefix", None) or "ORCL"
        self._repo_client = create_repository_client(
            self._orchestration_config,
            self._messages,
            dry_run=(not self._execute),
        )
        self._execute = True
        self._start_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._start_time = datetime.now().strftime("%d %B %Y %H:%M:%S")

    @property
    def metadata(self) -> dict[str, Any]:
        """Return metadata about the report."""
        return self._initialise_metadata_dict()

    @property
    def report_file(self) -> str | None:
        """Return name of the report being saved if applicable."""
        return self._report_file if hasattr(self, "_report_file") else None

    @property
    def as_json(self) -> bool:
        """Return whether the data is to be returned as JSON."""
        return self._output_format == JSON

    @property
    def as_raw(self) -> bool:
        """Return whether the data is to be returned as Python raw data."""
        return self._output_format == RAW

    @property
    def is_summary(self) -> bool:
        """Return whether the output format is at summary level."""
        return self._output_level == SUMMARY_LEVEL

    @property
    def is_detail(self) -> bool:
        """Return whether the output format is at detail level."""
        return self._output_level == DETAIL_LEVEL

    def get_offload_status_report_data(
        self,
        schema: str | None = None,
        table: str | None = None,
        output_level: str = DEFAULT_OUTPUT_LEVEL,
        demo_mode: bool = DEFAULT_DEMO_MODE,
    ) -> dict[str, Any]:
        """Fetch and pre-process all data required for the Offload Status Report."""
        self._schema = schema.upper() if schema is not None else None
        self._table = table.upper() if table is not None else None
        self._output_level = output_level.lower() if output_level is not None else DEFAULT_OUTPUT_LEVEL
        self._demo_mode = demo_mode

        assert self._output_level in (
            SUMMARY_LEVEL,
            DETAIL_LEVEL,
        ), f"output_level parameter must be either {SUMMARY_LEVEL} or {DETAIL_LEVEL}"

        table_data = self._messages.offload_step(
            command_steps.STEP_OSR_DEMO_DATA if self._demo_mode else command_steps.STEP_OSR_FETCH_DATA,
            lambda: self._get_demo_table_data(),
            self._execute,
        )
        return self._messages.offload_step(
            command_steps.STEP_OSR_PROCESS_DATA,
            lambda: self._process_report_data(table_data),
            self._execute,
        )

    def gen_offload_status_report(
        self,
        report_data: dict[str, Any],
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        report_name: str = DEFAULT_REPORT_NAME,
        report_directory: str = DEFAULT_REPORT_DIRECTORY,
        csv_delimiter: str = DEFAULT_CSV_DELIMITER,
        csv_enclosure: str = DEFAULT_CSV_ENCLOSURE,
    ) -> int:
        """Render and save the Offload Status Report in the requested output format."""
        self._output_format = output_format.lower() if output_format is not None else DEFAULT_OUTPUT_FORMAT
        self._report_name = report_name or DEFAULT_REPORT_NAME
        self._report_directory = report_directory or DEFAULT_REPORT_DIRECTORY
        self._csv_delimiter = csv_delimiter or DEFAULT_CSV_DELIMITER
        self._csv_enclosure = csv_enclosure or DEFAULT_CSV_ENCLOSURE

        assert self._output_format in (CSV, TEXT, HTML, JSON, RAW)
        assert " " not in self._report_name
        assert " " not in self._report_directory
        assert len(self._csv_delimiter) == 1
        assert len(self._csv_enclosure) == 1

        if self._output_format == CSV:
            rep_fn = lambda: self._gen_csv_report(report_data)
        elif self._output_format == TEXT:
            rep_fn = lambda: self._gen_text_report(report_data)
        elif self._output_format == HTML:
            rep_fn = lambda: self._gen_html_report(report_data)
        elif self._output_format == JSON:
            rep_fn = lambda: self._gen_json_report(report_data)
        else:
            rep_fn = lambda: self._gen_raw_report(report_data)
        return int(self._messages.offload_step(command_steps.STEP_OSR_GENERATE_REPORT, rep_fn, execute=self._execute))

    def _get_demo_table_data(self) -> list[dict[str, Any]]:
        """Load demo table data from the compressed JSON fixture."""
        return StatusReportService.load_demo_table_data(schema=self._schema, table=self._table)

    def _format_table_name(self, schema_name: str, table_name: str, uppercase: bool = True) -> str:
        """Return qualified table name in uppercase if required."""
        qualified = f"{schema_name}.{table_name}"
        return qualified.upper() if uppercase else qualified

    def _initialise_metadata_dict(self) -> dict[str, Any]:
        """Return dictionary of metadata pertaining to this report."""
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

    def _initialise_summary_dict(self) -> dict[str, Any]:
        """Return zero-initialized summary dictionary."""
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

    def _process_report_data(self, table_data: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """Format a list of pre-processed table data into the final reporting data model."""

        def update_summary(summary_data: dict[str, Any], detail_data: Mapping[str, Any]) -> dict[str, Any]:
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

        for n, item in enumerate(table_data, 1):
            row = dict(item)
            schema, table = row[SOURCE_OWNER], row[SOURCE_TABLE]
            qualified_table_name = self._format_table_name(schema, table)
            self._messages.log(
                "Processing %s of %s: %s" % (n, table_count, qualified_table_name),
                detail=VVERBOSE,
            )

            if schema not in report_data:
                report_data[schema] = self._initialise_summary_dict()
                self._messages.debug("Initializing new schema %s:" % schema, detail=SUPPRESS_STDOUT)

            if self._output_level == SUMMARY_LEVEL:
                row = self._strip_detail(row)
            report_data[schema][table] = row
            update_summary(report_data[schema], row)
            update_summary(report_data, row)

        return report_data


def normalise_offload_status_report_options(options: "StatusReportOptions | Any") -> None:
    """Validate and normalize StatusReportOptions."""
    if getattr(options, "vverbose", False):
        options.verbose = True
    elif getattr(options, "quiet", False):
        options.vverbose = False
        options.verbose = False

    if not os.path.exists(options.report_directory):
        raise OffloadOptionError(
            f"Invalid value specified for --report-directory parameter. Directory {options.report_directory} does not exist."
        )
    if len(options.csv_delimiter) > 1:
        raise OffloadOptionError(
            f"Invalid value specified for --csv-delimiter parameter ({options.csv_delimiter}). Delimiter must be a single character."
        )
    if len(options.csv_enclosure) > 1:
        raise OffloadOptionError(
            f"Invalid value specified for --csv-enclosure parameter ({options.csv_enclosure}). Enclosure must be a single character or NULL."
        )


def offload_status_report_run(options: "StatusReportOptions") -> None:
    """Execute the Offload Status Report CLI flow."""
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
