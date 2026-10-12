# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Report rendering mixin for the Offload Status Report."""

import json
import os
import traceback
from datetime import datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader

from goe.goe import (
    version,
)
from goe.offload.offload_messages import (
    SUPPRESS_STDOUT,
)
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
    HTML,
    HYBRID_EXTERNAL_TABLE,
    HYBRID_OWNER,
    HYBRID_VIEW,
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
    MULTIVALUE_KEYS,
    OBJECT_NAME,
    OBJECT_OWNER,
    OBJECT_TYPE_DB,
    OBJECT_TYPE_GOE,
    OFFLOAD_BUCKET_COLUMN,
    OFFLOAD_BUCKET_COUNT,
    OFFLOAD_BUCKET_METHOD,
    OFFLOAD_OWNER,
    OFFLOAD_PART_KEY,
    OFFLOAD_PARTITION_FUNCTIONS,
    OFFLOAD_SORT_COLUMNS,
    OFFLOAD_TABLE,
    OFFLOAD_TABLE_EXISTS,
    OFFLOAD_TYPE,
    OFFLOAD_VERSION,
    OFFLOADED_BYTES,
    OFFLOADED_PARTS,
    OFFLOADED_ROWS,
    OFFLOADED_TABLES,
    RECLAIMABLE_BYTES,
    RECLAIMABLE_PARTS,
    RECLAIMABLE_ROWS,
    RETAINED_BYTES,
    RETAINED_PARTS,
    RETAINED_ROWS,
    SOURCE_OWNER,
    SOURCE_TABLE,
    SUCCESS,
    SUMMARY_KEYS,
    OffloadStatusReportException,
    divider,
)
from goe.util.misc_functions import backtick_sandwich, format_json_list


class ReportRenderersMixin:
    """Mixin providing CSV, TEXT, HTML, JSON, and RAW report renderers for OffloadStatusReport."""

    _report_name: Any
    _report_directory: Any
    _ora_db_name: Any
    _start_ts: Any
    _start_time: Any
    _output_format: Any
    _output_level: Any
    _messages: Any
    _csv_enclosure: Any
    _csv_delimiter: Any
    _schema: Any
    _table: Any
    _demo_mode: Any
    is_summary: Any
    is_detail: Any
    metadata: Any
    _format_table_name: Any

    def _gen_report_file_name(self, extension=None):
        if self._report_name == DEFAULT_REPORT_NAME:
            self._report_file = os.path.join(
                self._report_directory,
                f"{self._report_name}_{self._ora_db_name}_{self._start_ts}.{extension or self._output_format}",
            )
        else:
            _, ext = os.path.splitext(self._report_name)
            self._report_file = os.path.join(
                self._report_directory,
                "{repname}{ext}".format(
                    repname=self._report_name,
                    ext="" if ext else ".%s" % extension or self._output_format,
                ),
            )
        self._messages.debug("Report file path: %s" % self._report_file, detail=SUPPRESS_STDOUT)
        return self._report_file

    def _strip_summary(self, data):
        """Strips the summary keys off a dict to leave the remaining detail dict iterable."""
        return {k: v for k, v in list(data.items()) if k not in SUMMARY_KEYS}

    def _strip_detail(self, data):
        """Strips the detail keys off a dict to leave the remaining summary dict iterable."""
        return {k: v for k, v in list(data.items()) if k in SUMMARY_KEYS}

    def _gen_csv_report(self, data):
        """Generates a report in CSV format. Its content can be controlled by detail level (summary for
        schema-level or detail for table-level). The delimiter and enclosure character can also be
        controlled by options.

        Delimiter and enclosure functions... Prepare the header... Format the data...
        """
        report_data = []
        schema_data = self._strip_summary(data)

        def nvl(x, r=""):
            return x or r

        def quote(x):
            if x:
                value = backtick_sandwich(x, self._csv_enclosure) if isinstance(x, str) else x
            else:
                value = ""
            return value

        def delim(x, override_delimiter=None):
            d = override_delimiter if override_delimiter is not None else self._csv_delimiter
            return "%s" % d.join(str(_) if not isinstance(_, str) else _ for _ in x)

        if self.is_summary:
            self._messages.debug("Preparing summary level CSV report")

            line = [quote("SCHEMA")] + [quote("TABLE")] + [quote(_.strip("_")) for _ in SUMMARY_KEYS]
            report_data.append(delim(line))
            self._messages.debug("Report header generated", detail=SUPPRESS_STDOUT)

            for schema in sorted(schema_data):
                table_data = self._strip_summary(schema_data[schema])
                for table in sorted(table_data):
                    line = [quote(schema), quote(table)]
                    for k in SUMMARY_KEYS:
                        line.append(quote(table_data[table][k]))
                    report_data.append(delim(line))
            self._messages.debug("Report data added", detail=SUPPRESS_STDOUT)

        else:
            self._messages.debug("Preparing detail level CSV report")

            header = []
            header_written = False
            for schema in sorted(schema_data):
                table_data = self._strip_summary(schema_data[schema])
                for table in sorted(table_data):
                    line = []
                    for k, v in sorted(table_data[table].items()):
                        if not header_written:
                            header.append(quote(k.strip("_")))

                        if k in MULTIVALUE_KEYS:
                            multifield = []
                            for mv in v:
                                multifield.append(
                                    self._format_table_name(
                                        mv[OBJECT_OWNER],
                                        mv[OBJECT_NAME],
                                        k != INCREMENTAL_UPDATE_OBJECTS_OFFLOAD,
                                    )
                                )
                            line.append(quote(delim(multifield, DEFAULT_CSV_DELIMITER)))
                            self._messages.debug(
                                "Data for multivalue key %s added" % k,
                                detail=SUPPRESS_STDOUT,
                            )
                        else:
                            line.append(
                                quote(v)
                                if k != INCREMENTAL_PREDICATE_VALUE
                                else quote(format_json_list(v, DEFAULT_CSV_DELIMITER))
                            )

                    if not header_written:
                        report_data.append(delim(header))
                        header_written = True
                        self._messages.debug("Report header generated", detail=SUPPRESS_STDOUT)
                    report_data.append(delim(line))

        self._messages.debug("Saving report to CSV file")
        status = self._save_report(report_data, CSV)
        return status

    def _gen_text_report(self, data):
        """Generates a report in text format. This is a less-rich format than HTML. Its content
        can be controlled by detail level (summary for schema-level or detail for table-level).

        Prepare the schema-level data up-front to determine the appropriate reporting width... Add section 3 data to the report... Prepare the table-level data up-front to determine the appropriate reporting width... Add section 4 data to the report...
        """
        report_data = []

        def line(length, char="-"):
            return "%s" % (char * length)

        def underline(string, indent=0):
            return "%s\n%s%s\n" % (string, lpad("", indent), line(len(string)))

        def heading(string):
            return "\n\n%s\n%s\n" % (string, line(len(string), "="))

        def gb(n):
            return round(float(n) / (1024**3), 2)

        def rows(n):
            if n is None:
                value = "-"
            else:
                value = n
            return value

        def lpad(string, spaces=4):
            return "%s%s" % ((" " * spaces), string)

        self._messages.debug("Preparing %s level text report" % self._output_level)

        report_data.append("\nOffload Status Report for %s database at %s.\n" % (self._ora_db_name, self._start_time))

        report_data.append(heading("1. Options"))
        self._messages.debug("Adding Section 1 to text report", detail=SUPPRESS_STDOUT)
        width = max(40, len(self._schema or ""), len(self._table or ""))
        report_data.append("%-30s %-*s %s" % ("Option Name", width, "Option Value", "Default"))
        report_data.append("%s %s %s" % (line(30), line(width), line(10)))
        report_data.append("%-30s %-*s %s" % ("--schema", width, self._schema or "-", self._schema is None))
        report_data.append("%-30s %-*s %s" % ("--table", width, self._table or "-", self._table is None))
        report_data.append(
            "%-30s %-*s %s"
            % (
                "--output-format",
                width,
                self._output_format,
                self._output_format == DEFAULT_OUTPUT_FORMAT,
            )
        )
        report_data.append(
            "%-30s %-*s %s"
            % (
                "--output-level",
                width,
                self._output_level,
                self._output_level == DEFAULT_OUTPUT_LEVEL,
            )
        )
        report_data.append(
            "%-30s %-*s %s"
            % (
                "--report-name",
                width,
                self._report_name,
                self._report_name == DEFAULT_REPORT_NAME,
            )
        )
        report_data.append(
            "%-30s %-*s %s"
            % (
                "--report-directory",
                width,
                self._report_directory,
                self._report_directory == DEFAULT_REPORT_DIRECTORY,
            )
        )
        report_data.append(
            "%-30s %-*s %s"
            % (
                "--csv-delimiter",
                width,
                self._csv_delimiter,
                self._csv_delimiter == DEFAULT_CSV_DELIMITER,
            )
        )
        report_data.append(
            "%-30s %-*s %s"
            % (
                "--csv-enclosure",
                width,
                self._csv_enclosure,
                self._csv_enclosure == DEFAULT_CSV_ENCLOSURE,
            )
        )
        report_data.append(
            "%-30s %-*s %s"
            % (
                "--demo-mode",
                width,
                self._demo_mode,
                self._demo_mode == DEFAULT_DEMO_MODE,
            )
        )
        self._messages.debug("Section 1 added to text report", detail=SUPPRESS_STDOUT)

        report_data.append(heading("2. Database Environment"))
        self._messages.debug("Adding Section 2 to text report", detail=SUPPRESS_STDOUT)
        report_data.append("%-30s %s" % ("Name", "Value"))
        report_data.append("%s %s" % (line(30), line(40)))
        report_data.append("%-30s %s" % ("RDBMS name", self.metadata["db_name"]))
        report_data.append("%-30s %s" % ("RDBMS login user", self.metadata["db_login_user"]))
        report_data.append("%-30s %s" % ("RDBMS connection", self.metadata["db_connection"]))
        report_data.append("%-30s %s" % ("Offload database type", self.metadata["backend_db_type"]))
        report_data.append(
            "%-30s %s"
            % (
                "Offload %s" % self.metadata["backend_host_label"].lower(),
                self.metadata["backend_host_value"],
            )
        )
        self._messages.debug("Section 2 added to text report", detail=SUPPRESS_STDOUT)

        report_data.append(heading("3. Schema Summary"))
        self._messages.debug("Adding Section 3 to text report", detail=SUPPRESS_STDOUT)

        s3_raw_data = []
        schema_width = 30
        schema_data = self._strip_summary(data)
        for k, v in sorted(schema_data.items()):
            schema_width = max(schema_width, len(k))
            s3_raw_data.append(
                (
                    k,
                    v[OFFLOADED_TABLES],
                    v[OFFLOADED_PARTS],
                    gb(v[OFFLOADED_BYTES]),
                    rows(v[OFFLOADED_ROWS]),
                    v[RETAINED_PARTS],
                    gb(v[RETAINED_BYTES]),
                    rows(v[RETAINED_ROWS]),
                    v[RECLAIMABLE_PARTS],
                    gb(v[RECLAIMABLE_BYTES]),
                    rows(v[RECLAIMABLE_ROWS]),
                )
            )

        report_data.append(
            "%-*s %15s %15s %15s %15s %15s %15s %15s %15s %15s %15s"
            % (
                schema_width,
                "",
                "Offloaded",
                "Offloaded",
                "Offloaded",
                "Offloaded",
                "Retained",
                "Retained",
                "Retained",
                "Reclaimable",
                "Reclaimable",
                "Reclaimable",
            )
        )
        report_data.append(
            "%-*s %15s %15s %15s %15s %15s %15s %15s %15s %15s %15s"
            % (
                schema_width,
                "Schema Name",
                "Tables",
                "Segments",
                "Size (GB)",
                "Rows (Stats)",
                "Segments",
                "Size (GB)",
                "Rows (Stats)",
                "Segments",
                "Size (GB)",
                "Rows (Stats)",
            )
        )
        report_data.append(
            "%s %s %s %s %s %s %s %s %s %s %s"
            % (
                line(schema_width),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
            )
        )
        for rv in s3_raw_data:
            report_data.append("%-*s %15s %15s %15.2f %15s %15s %15.2f %15s %15s %15.2f %15s" % (schema_width, *rv))
        report_data.append(
            "%s %s %s %s %s %s %s %s %s %s %s"
            % (
                line(schema_width),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
            )
        )
        report_data.append(
            "%-*s %15s %15s %15.2f %15s %15s %15.2f %15s %15s %15.2f %15s"
            % (
                schema_width,
                "Totals",
                data[OFFLOADED_TABLES],
                data[OFFLOADED_PARTS],
                gb(data[OFFLOADED_BYTES]),
                rows(data[OFFLOADED_ROWS]),
                data[RETAINED_PARTS],
                gb(data[RETAINED_BYTES]),
                rows(data[RETAINED_ROWS]),
                data[RECLAIMABLE_PARTS],
                gb(data[RECLAIMABLE_BYTES]),
                rows(data[RECLAIMABLE_ROWS]),
            )
        )
        self._messages.debug("Section 3 added to text report", detail=SUPPRESS_STDOUT)

        report_data.append(heading("4. Table Summary"))
        self._messages.debug("Adding Section 4 to text report", detail=SUPPRESS_STDOUT)

        s4_raw_data = []
        table_width = 30
        for k, v in sorted(schema_data.items()):
            table_data = self._strip_summary(schema_data[k])
            for tk, tv in sorted(table_data.items()):
                table_width = max(table_width, len(tk))
                s4_raw_data.append(
                    (
                        k,
                        tk,
                        tv[OFFLOADED_TABLES],
                        tv[OFFLOADED_PARTS],
                        gb(tv[OFFLOADED_BYTES]),
                        rows(tv[OFFLOADED_ROWS]),
                        tv[RETAINED_PARTS],
                        gb(tv[RETAINED_BYTES]),
                        rows(tv[RETAINED_ROWS]),
                        tv[RECLAIMABLE_PARTS],
                        gb(tv[RECLAIMABLE_BYTES]),
                        rows(tv[RECLAIMABLE_ROWS]),
                    )
                )

        report_data.append(
            "%-*s %-*s %15s %15s %15s %15s %15s %15s %15s %15s %15s %15s"
            % (
                schema_width,
                "",
                table_width,
                "",
                "Offloaded",
                "Offloaded",
                "Offloaded",
                "Offloaded",
                "Retained",
                "Retained",
                "Retained",
                "Reclaimable",
                "Reclaimable",
                "Reclaimable",
            )
        )
        report_data.append(
            "%-*s %-*s %15s %15s %15s %15s %15s %15s %15s %15s %15s %15s"
            % (
                schema_width,
                "Schema Name",
                table_width,
                "Table Name",
                "Tables",
                "Segments",
                "Size (GB)",
                "Rows (Stats)",
                "Segments",
                "Size (GB)",
                "Rows (Stats)",
                "Segments",
                "Size (GB)",
                "Rows (Stats)",
            )
        )
        report_data.append(
            "%s %s %s %s %s %s %s %s %s %s %s %s"
            % (
                line(schema_width),
                line(table_width),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
            )
        )
        for s4_rv in s4_raw_data:
            schema_slice = s4_rv[0]
            table_slice = s4_rv[1:]
            report_data.append(
                "%-*s %-*s %15s %15s %15.2f %15s %15s %15.2f %15s %15s %15.2f %15s"
                % (schema_width, schema_slice, table_width, *table_slice)
            )
        report_data.append(
            "%s %s %s %s %s %s %s %s %s %s %s %s"
            % (
                line(schema_width),
                line(table_width),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
                line(15),
            )
        )
        report_data.append(
            "%-*s %-*s %15s %15s %15.2f %15s %15s %15.2f %15s %15s %15.2f %15s"
            % (
                schema_width,
                "Totals",
                table_width,
                "",
                data[OFFLOADED_TABLES],
                data[OFFLOADED_PARTS],
                gb(data[OFFLOADED_BYTES]),
                rows(data[OFFLOADED_ROWS]),
                data[RETAINED_PARTS],
                gb(data[RETAINED_BYTES]),
                rows(data[RETAINED_ROWS]),
                data[RECLAIMABLE_PARTS],
                gb(data[RECLAIMABLE_BYTES]),
                rows(data[RECLAIMABLE_ROWS]),
            )
        )
        self._messages.debug("Section 4 added to text report", detail=SUPPRESS_STDOUT)

        if self.is_detail:
            report_data.append(heading("5. Table Detail"))
            self._messages.debug("Adding Section 5 to text report", detail=SUPPRESS_STDOUT)

            if not schema_data:
                report_data.append("No offloaded tables to report on")

            for k, v in sorted(schema_data.items()):
                table_data = self._strip_summary(schema_data[k])
                for tk, tv in sorted(table_data.items()):
                    report_data.append(underline(self._format_table_name(k, tk)))

                    self._messages.debug(
                        "Adding Offload Summary Statistics to Section 5",
                        detail=SUPPRESS_STDOUT,
                    )
                    indent = 4
                    report_data.append(lpad(underline("Offload Summary Statistics", indent)))
                    indent = 8
                    report_data.append(
                        lpad(
                            "%-30s %20s %20s %20s" % ("Type", "Size (GB)", "Segments", "Rows (From Stats)"),
                            indent,
                        )
                    )
                    report_data.append(
                        lpad(
                            "%s %s %s %s" % (line(30), line(20), line(20), line(20)),
                            indent,
                        )
                    )
                    report_data.append(
                        lpad(
                            "%-30s %20.2f %20s %20s"
                            % (
                                "Offloaded",
                                gb(tv[OFFLOADED_BYTES]),
                                tv[OFFLOADED_PARTS],
                                tv[OFFLOADED_ROWS],
                            ),
                            indent,
                        )
                    )
                    report_data.append(
                        lpad(
                            "%-30s %20.2f %20s %20s"
                            % (
                                "Retained (RDBMS)",
                                gb(tv[RETAINED_BYTES]),
                                tv[RETAINED_PARTS],
                                tv[RETAINED_ROWS],
                            ),
                            indent,
                        )
                    )
                    report_data.append(
                        lpad(
                            "%-30s %20.2f %20s %20s"
                            % (
                                "Reclaimable (RDBMS)",
                                gb(tv[RECLAIMABLE_BYTES]),
                                tv[RECLAIMABLE_PARTS],
                                tv[RECLAIMABLE_ROWS],
                            ),
                            indent,
                        )
                    )

                    def append_table_detail(name, value, indent):
                        if value:
                            report_data.append(lpad("%-30s %s" % (name, value), indent))

                    self._messages.debug(
                        "Adding Offloaded Table Details to Section 5",
                        detail=SUPPRESS_STDOUT,
                    )
                    indent = 4
                    report_data.append("")
                    report_data.append(lpad(underline("Offloaded Table Details", indent), indent))
                    indent = 8
                    append_table_detail("Name", "Value", indent)
                    append_table_detail(line(30), line(85), indent)
                    append_table_detail(
                        "Source table",
                        self._format_table_name(tv[SOURCE_OWNER], tv[SOURCE_TABLE]),
                        indent,
                    )
                    append_table_detail(
                        "Hybrid view",
                        self._format_table_name(tv[HYBRID_OWNER], tv[HYBRID_VIEW]),
                        indent,
                    )
                    append_table_detail(
                        "Hybrid external table",
                        self._format_table_name(tv[HYBRID_OWNER], tv[HYBRID_EXTERNAL_TABLE]),
                        indent,
                    )
                    if tv[OFFLOAD_TABLE_EXISTS]:
                        append_table_detail(
                            "Offloaded table",
                            self._format_table_name(tv[OFFLOAD_OWNER], tv[OFFLOAD_TABLE], False),
                            indent,
                        )
                    else:
                        append_table_detail(
                            "Offloaded table",
                            "Offloaded table not found (%s)"
                            % self._format_table_name(tv[OFFLOAD_OWNER], tv[OFFLOAD_TABLE]),
                            indent,
                        )

                    self._messages.debug("Adding Offload Parameters to Section 5", detail=SUPPRESS_STDOUT)
                    indent = 4
                    report_data.append("")
                    report_data.append(lpad(underline("Offload Parameters", indent), indent))
                    indent = 8
                    append_table_detail("Name", "Value", indent)
                    append_table_detail(line(30), line(85), indent)
                    append_table_detail("Offload type", tv[OFFLOAD_TYPE], indent)
                    append_table_detail("Offload predicate type", tv[INCREMENTAL_PREDICATE_TYPE], indent)
                    append_table_detail("Offload high water mark", tv[INCREMENTAL_HIGH_VALUE], indent)
                    append_table_detail(
                        "Offload predicates",
                        format_json_list(tv[INCREMENTAL_PREDICATE_VALUE], indent=30 + indent + 1),
                        indent,
                    )
                    append_table_detail("Partition columns (RDBMS)", tv[INCREMENTAL_KEY], indent)
                    append_table_detail("Partition columns (offloaded)", tv[OFFLOAD_PART_KEY], indent)
                    append_table_detail("Partition functions", tv[OFFLOAD_PARTITION_FUNCTIONS], indent)
                    append_table_detail("Partition offload level", tv[INCREMENTAL_RANGE], indent)
                    if tv[INCREMENTAL_UPDATE_METHOD]:
                        append_table_detail("Incremental Update enabled", "Yes", indent)
                    else:
                        append_table_detail(
                            "Incremental Update enabled",
                            "No" if tv[OFFLOAD_TABLE_EXISTS] else "Unknown",
                            indent,
                        )
                    append_table_detail(
                        "Incremental Update method",
                        tv[INCREMENTAL_UPDATE_METHOD],
                        indent,
                    )
                    append_table_detail("Offload version", tv[OFFLOAD_VERSION], indent)
                    append_table_detail("Offload bucket count", tv[OFFLOAD_BUCKET_COUNT], indent)
                    append_table_detail("Offload bucket column", tv[OFFLOAD_BUCKET_COLUMN], indent)
                    append_table_detail("Offload bucket method", tv[OFFLOAD_BUCKET_METHOD], indent)
                    append_table_detail("Offload sort columns", tv[OFFLOAD_SORT_COLUMNS], indent)

                    def multivalue_subsection(data, data_type, title):
                        if data:
                            self._messages.debug("Adding %s to Section 5" % title, detail=SUPPRESS_STDOUT)
                            indent = 4
                            report_data.append("")
                            report_data.append(lpad(underline(title, indent)))
                            indent = 8
                            report_data.append(
                                lpad(
                                    "%-30s %-24s %s"
                                    % (
                                        "%s Object Type" % data_type,
                                        "Object Type",
                                        "Object Name",
                                    ),
                                    indent,
                                )
                            )
                            report_data.append(lpad("%s %s %s" % (line(30), line(24), line(60)), indent))
                            for o in sorted(data, key=lambda k: k[OBJECT_NAME]):
                                report_data.append(
                                    lpad(
                                        "%-30s %-24s %s"
                                        % (
                                            o[OBJECT_TYPE_GOE].replace("_", " ").capitalize(),
                                            o[OBJECT_TYPE_DB],
                                            self._format_table_name(o[OBJECT_OWNER], o[OBJECT_NAME]),
                                        ),
                                        indent,
                                    )
                                )

                    multivalue_subsection(
                        tv[AAPD_OBJECTS],
                        "AAPD",
                        "Advanced Aggregation Pushdown (AAPD) Objects",
                    )
                    multivalue_subsection(
                        tv[INCREMENTAL_UPDATE_OBJECTS_RDBMS],
                        "Incremental Update",
                        "Incremental Update Objects (RDBMS)",
                    )
                    multivalue_subsection(
                        tv[INCREMENTAL_UPDATE_OBJECTS_OFFLOAD],
                        "Incremental Update",
                        "Incremental Update Objects (Offloaded)",
                    )
                    multivalue_subsection(
                        tv[JOIN_OBJECTS_RDBMS],
                        "Join Pushdown",
                        "Advanced Join Pushdown Objects (RDBMS)",
                    )
                    multivalue_subsection(
                        tv[JOIN_OBJECTS_OFFLOAD],
                        "Join Pushdown",
                        "Advanced Join Pushdown Objects (Offloaded)",
                    )
                    multivalue_subsection(tv[DEPENDENT_OBJECTS], "Dependent", "Dependent Objects (RDBMS)")
                    report_data.append("")
            self._messages.debug("Section 5 added to text report", detail=SUPPRESS_STDOUT)
        else:
            report_data.append("")

        self._messages.debug("Saving report to TXT file")
        status = self._save_report(report_data, "txt", footer=True)
        return status

    def _gen_html_report(self, data):
        """Generates a fully-rich report in HTML format."""
        this_dir = os.path.dirname(os.path.abspath(__file__))
        j2_env = Environment(loader=FileSystemLoader(this_dir + "/../templates/"), trim_blocks=True)
        report_data = [
            j2_env.get_template("offload_status_report/goe_offload_status_report.html").render(
                data=data, metadata=self.metadata
            )
        ]
        status = self._save_report(report_data, HTML)
        return status

    def _gen_json_report(self, data):
        """Generates a report in JSON format (simple conversion of Python dict to JSON)."""
        status = self._save_report(json.dumps(data), JSON)
        return status

    def _gen_raw_report(self, data):
        """Generates a report data in its raw format (Python dict)."""
        status = self._save_report(data, "dat")
        return status

    def _save_report(self, report_data, report_format=None, footer=False):
        goe_report = "\nOffload Status Report v%s%s" % (
            version(),
            " (Demo Mode)" if self._demo_mode else "",
        )
        goe_copyright = "\nCopyright 2015-%s GOE Inc. All rights reserved." % datetime.now().strftime("%Y")
        try:
            self._messages.debug("Saving data to file", detail=SUPPRESS_STDOUT)
            self._gen_report_file_name(extension=report_format)
            if not isinstance(report_data, list):
                report_data = [report_data]
            with open(self._report_file, "w") as rf:
                if not report_format == HTML:
                    rf.write("\n%s" % divider)
                    rf.write(goe_report)
                    rf.write(goe_copyright)
                    rf.write("\n%s\n\n" % divider)
                [rf.write("%s\n" % line) for line in report_data]
                if not report_format == HTML and footer:
                    rf.write(goe_report)
                    rf.write("%s\n\n" % goe_copyright)
            self._messages.log("Report saved to %s" % self._report_file)
        except OSError:
            raise OffloadStatusReportException(
                "Unable to write report %s\n%s" % (self._report_file, traceback.format_exc())
            )
        return SUCCESS
