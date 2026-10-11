# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Backwards-compatible facade for offload source-data classes, now in goe.offload.source_data."""

from goe.offload.source_data.base import (
    INCREMENTAL_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT as INCREMENTAL_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import (
    IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT as IPA_OFFLOAD_DEFAULT_PARTITION_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import MAX_QUERY_OPTIMISTIC_PRUNE_CLAUSE as MAX_QUERY_OPTIMISTIC_PRUNE_CLAUSE
from goe.offload.source_data.base import NO_MATCHING_PARTITION_EXCEPTION_TEXT as NO_MATCHING_PARTITION_EXCEPTION_TEXT
from goe.offload.source_data.base import NO_MAXVALUE_PARTITION_NOTICE_TEXT as NO_MAXVALUE_PARTITION_NOTICE_TEXT
from goe.offload.source_data.base import OFFLOAD_SOURCE_CLIENT_OFFLOAD as OFFLOAD_SOURCE_CLIENT_OFFLOAD
from goe.offload.source_data.base import (
    OFFLOAD_TYPE_CHANGE_FOR_PBO_EXCEPTION_TEXT as OFFLOAD_TYPE_CHANGE_FOR_PBO_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import PREDICATE_APPEND_HWM_MESSAGE_TEXT as PREDICATE_APPEND_HWM_MESSAGE_TEXT
from goe.offload.source_data.base import (
    PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT as PREDICATE_TYPE_INCOMPATIBLE_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import (
    PREDICATE_TYPE_NO_MODIFY_HV_EXCEPTION_TEXT as PREDICATE_TYPE_NO_MODIFY_HV_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import (
    PREDICATE_TYPE_NO_MODIFY_RESET_EXCEPTION_TEXT as PREDICATE_TYPE_NO_MODIFY_RESET_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import (
    PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT as PREDICATE_TYPE_OFFLOAD_TYPE_FULL_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import (
    PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT as PREDICATE_TYPE_REQUIRED_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import (
    RANGE_AND_PREDICATE_WITHOUT_PART_KEY_EXCEPTION_TEXT as RANGE_AND_PREDICATE_WITHOUT_PART_KEY_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import (
    TOO_MANY_PARTITION_NAMES_EXCEPTION_TEXT as TOO_MANY_PARTITION_NAMES_EXCEPTION_TEXT,
)
from goe.offload.source_data.base import OffloadSourceDataInterface as OffloadSourceDataInterface
from goe.offload.source_data.base import OffloadSourcePartition as OffloadSourcePartition
from goe.offload.source_data.base import OffloadSourcePartitions as OffloadSourcePartitions
from goe.offload.source_data.base import get_offload_type_for_config as get_offload_type_for_config
from goe.offload.source_data.base import is_default_partition as is_default_partition
from goe.offload.source_data.factory import offload_source_data_factory as offload_source_data_factory
from goe.offload.source_data.ipa_range import OffloadSourceDataIpaRange as OffloadSourceDataIpaRange
