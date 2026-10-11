# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Backwards-compatible facade for the Offload Status Report, now implemented in goe.report."""

from goe.report.collector import OffloadStatusReport as OffloadStatusReport
from goe.report.collector import offload_status_report_run as offload_status_report_run
from goe.report.models import DEFAULT_CSV_DELIMITER as DEFAULT_CSV_DELIMITER
from goe.report.models import DEFAULT_CSV_ENCLOSURE as DEFAULT_CSV_ENCLOSURE
from goe.report.models import DEFAULT_DEMO_MODE as DEFAULT_DEMO_MODE
from goe.report.models import DEFAULT_OUTPUT_FORMAT as DEFAULT_OUTPUT_FORMAT
from goe.report.models import DEFAULT_OUTPUT_LEVEL as DEFAULT_OUTPUT_LEVEL
from goe.report.models import DEFAULT_REPORT_DIRECTORY as DEFAULT_REPORT_DIRECTORY
from goe.report.models import DEFAULT_REPORT_NAME as DEFAULT_REPORT_NAME
