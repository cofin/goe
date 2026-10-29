# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Offload Status Report models, renderers, and concurrent DuckDB-backed service."""

from goe.report.models import (
    AAPD_OBJECTS as AAPD_OBJECTS,
)
from goe.report.models import (
    CSV as CSV,
)
from goe.report.models import (
    DEFAULT_CSV_DELIMITER as DEFAULT_CSV_DELIMITER,
)
from goe.report.models import (
    DEFAULT_CSV_ENCLOSURE as DEFAULT_CSV_ENCLOSURE,
)
from goe.report.models import (
    DEFAULT_DEMO_MODE as DEFAULT_DEMO_MODE,
)
from goe.report.models import (
    DEFAULT_OUTPUT_FORMAT as DEFAULT_OUTPUT_FORMAT,
)
from goe.report.models import (
    DEFAULT_OUTPUT_LEVEL as DEFAULT_OUTPUT_LEVEL,
)
from goe.report.models import (
    DEFAULT_REPORT_DIRECTORY as DEFAULT_REPORT_DIRECTORY,
)
from goe.report.models import (
    DEFAULT_REPORT_NAME as DEFAULT_REPORT_NAME,
)
from goe.report.models import (
    DEPENDENT_OBJECTS as DEPENDENT_OBJECTS,
)
from goe.report.models import (
    DETAIL_LEVEL as DETAIL_LEVEL,
)
from goe.report.models import (
    FAILURE as FAILURE,
)
from goe.report.models import (
    HTML as HTML,
)
from goe.report.models import (
    HYBRID_EXTERNAL_TABLE as HYBRID_EXTERNAL_TABLE,
)
from goe.report.models import (
    HYBRID_OWNER as HYBRID_OWNER,
)
from goe.report.models import (
    HYBRID_VIEW as HYBRID_VIEW,
)
from goe.report.models import (
    HYBRID_VIEW_TYPE as HYBRID_VIEW_TYPE,
)
from goe.report.models import (
    INCREMENTAL_HIGH_VALUE as INCREMENTAL_HIGH_VALUE,
)
from goe.report.models import (
    INCREMENTAL_KEY as INCREMENTAL_KEY,
)
from goe.report.models import (
    INCREMENTAL_PREDICATE_TYPE as INCREMENTAL_PREDICATE_TYPE,
)
from goe.report.models import (
    INCREMENTAL_PREDICATE_VALUE as INCREMENTAL_PREDICATE_VALUE,
)
from goe.report.models import (
    INCREMENTAL_RANGE as INCREMENTAL_RANGE,
)
from goe.report.models import (
    INCREMENTAL_UPDATE_METHOD as INCREMENTAL_UPDATE_METHOD,
)
from goe.report.models import (
    INCREMENTAL_UPDATE_OBJECTS_OFFLOAD as INCREMENTAL_UPDATE_OBJECTS_OFFLOAD,
)
from goe.report.models import (
    INCREMENTAL_UPDATE_OBJECTS_RDBMS as INCREMENTAL_UPDATE_OBJECTS_RDBMS,
)
from goe.report.models import (
    JOIN_OBJECTS_OFFLOAD as JOIN_OBJECTS_OFFLOAD,
)
from goe.report.models import (
    JOIN_OBJECTS_RDBMS as JOIN_OBJECTS_RDBMS,
)
from goe.report.models import (
    JSON as JSON,
)
from goe.report.models import (
    MULTIVALUE_KEYS as MULTIVALUE_KEYS,
)
from goe.report.models import (
    OBJECT_NAME as OBJECT_NAME,
)
from goe.report.models import (
    OBJECT_OWNER as OBJECT_OWNER,
)
from goe.report.models import (
    OBJECT_TYPE_DB as OBJECT_TYPE_DB,
)
from goe.report.models import (
    OBJECT_TYPE_GOE as OBJECT_TYPE_GOE,
)
from goe.report.models import (
    OFFLOAD_BUCKET_COLUMN as OFFLOAD_BUCKET_COLUMN,
)
from goe.report.models import (
    OFFLOAD_BUCKET_COUNT as OFFLOAD_BUCKET_COUNT,
)
from goe.report.models import (
    OFFLOAD_BUCKET_METHOD as OFFLOAD_BUCKET_METHOD,
)
from goe.report.models import (
    OFFLOAD_OWNER as OFFLOAD_OWNER,
)
from goe.report.models import (
    OFFLOAD_PART_KEY as OFFLOAD_PART_KEY,
)
from goe.report.models import (
    OFFLOAD_PARTITION_FUNCTIONS as OFFLOAD_PARTITION_FUNCTIONS,
)
from goe.report.models import (
    OFFLOAD_SORT_COLUMNS as OFFLOAD_SORT_COLUMNS,
)
from goe.report.models import (
    OFFLOAD_TABLE as OFFLOAD_TABLE,
)
from goe.report.models import (
    OFFLOAD_TABLE_EXISTS as OFFLOAD_TABLE_EXISTS,
)
from goe.report.models import (
    OFFLOAD_TYPE as OFFLOAD_TYPE,
)
from goe.report.models import (
    OFFLOAD_VERSION as OFFLOAD_VERSION,
)
from goe.report.models import (
    OFFLOADED_BYTES as OFFLOADED_BYTES,
)
from goe.report.models import (
    OFFLOADED_PARTS as OFFLOADED_PARTS,
)
from goe.report.models import (
    OFFLOADED_ROWS as OFFLOADED_ROWS,
)
from goe.report.models import (
    OFFLOADED_TABLES as OFFLOADED_TABLES,
)
from goe.report.models import (
    RAW as RAW,
)
from goe.report.models import (
    RECLAIMABLE_BYTES as RECLAIMABLE_BYTES,
)
from goe.report.models import (
    RECLAIMABLE_PARTS as RECLAIMABLE_PARTS,
)
from goe.report.models import (
    RECLAIMABLE_ROWS as RECLAIMABLE_ROWS,
)
from goe.report.models import (
    RETAINED_BYTES as RETAINED_BYTES,
)
from goe.report.models import (
    RETAINED_PARTS as RETAINED_PARTS,
)
from goe.report.models import (
    RETAINED_ROWS as RETAINED_ROWS,
)
from goe.report.models import (
    SOURCE_IOT_TYPE as SOURCE_IOT_TYPE,
)
from goe.report.models import (
    SOURCE_OWNER as SOURCE_OWNER,
)
from goe.report.models import (
    SOURCE_TABLE as SOURCE_TABLE,
)
from goe.report.models import (
    SUCCESS as SUCCESS,
)
from goe.report.models import (
    SUMMARY_KEYS as SUMMARY_KEYS,
)
from goe.report.models import (
    SUMMARY_LEVEL as SUMMARY_LEVEL,
)
from goe.report.models import (
    TEXT as TEXT,
)
from goe.report.models import (
    OffloadStatusReportException as OffloadStatusReportException,
)
from goe.report.models import (
    PartitionStatusRow as PartitionStatusRow,
)
from goe.report.models import (
    StatusReportEnvelope as StatusReportEnvelope,
)
from goe.report.models import (
    TableStatusReport as TableStatusReport,
)
from goe.report.models import (
    divider as divider,
)
from goe.report.models import (
    incremental_partition_match as incremental_partition_match,
)
from goe.report.models import (
    sub_divider as sub_divider,
)
from goe.report.renderers import ReportRenderersMixin as ReportRenderersMixin
from goe.report.service import (
    DEMO_FIXTURE_PATH as DEMO_FIXTURE_PATH,
)
from goe.report.service import (
    OffloadStatusReport as OffloadStatusReport,
)
from goe.report.service import (
    StatusReportService as StatusReportService,
)
from goe.report.service import (
    normalise_offload_status_report_options as normalise_offload_status_report_options,
)
from goe.report.service import (
    offload_status_report_run as offload_status_report_run,
)
