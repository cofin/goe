# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""RDBMS/NLS helpers, option normalisers, BaseOperation, and OffloadOperation."""

import os
import os.path
import re
import traceback
from typing import TYPE_CHECKING, Any

from goe.config import orchestration_defaults
from goe.config.config_validation_functions import normalise_size_option
from goe.config.options import EXPECTED_OFFLOAD_ARGS
from goe.exceptions import OffloadException, OffloadOptionError, OptionValueError
from goe.filesystem.goe_dfs import (
    get_scheme_from_location_uri,
)
from goe.offload import offload_constants
from goe.offload.backend_api import IMPALA_NOSHUFFLE_HINT, IMPALA_SHUFFLE_HINT
from goe.offload.column_metadata import (
    GOE_TYPE_DATE,
    GOE_TYPE_DECIMAL,
    GOE_TYPE_DOUBLE,
    GOE_TYPE_INTEGER_1,
    GOE_TYPE_INTEGER_2,
    GOE_TYPE_INTEGER_4,
    GOE_TYPE_INTEGER_8,
    GOE_TYPE_INTEGER_38,
    GOE_TYPE_TIMESTAMP_TZ,
    GOE_TYPE_VARIABLE_STRING,
    match_table_column,
)
from goe.offload.offload import (
    active_data_append_options,
    normalise_less_than_options,
)
from goe.offload.offload_messages import (
    VERBOSE,
    VVERBOSE,
    OffloadMessages,
)
from goe.offload.offload_source_data import (
    get_offload_type_for_config,
)
from goe.offload.offload_source_table import (
    OFFLOAD_PARTITION_TYPE_LIST,
    OFFLOAD_PARTITION_TYPE_RANGE,
    OffloadSourceTableInterface,
)
from goe.offload.offload_transport import (
    validate_offload_transport_method,
)
from goe.offload.operation.data_type_controls import (
    DECIMAL_COL_TYPE_SYNTAX_TEMPLATE,
    canonical_columns_from_columns_csv,
)
from goe.offload.operation.ddl_file import normalise_ddl_file
from goe.offload.operation.partition_controls import (
    offload_options_to_partition_info,
    validate_offload_partition_columns,
    validate_offload_partition_functions,
    validate_offload_partition_granularity,
)
from goe.offload.operation.sort_columns import sort_columns_csv_to_sort_columns
from goe.offload.option_validation import (
    check_ipa_predicate_type_option_conflicts,
    check_opt_is_posint,
    normalise_data_sampling_options,
    normalise_offload_predicate_options,
    normalise_stats_options,
    normalise_verify_options,
)
from goe.offload.registry import (
    create_backend_api,
    create_frontend_api,
    create_repository_client,
)
from goe.orchestration.constants import (
    NLS_LANG_MISSING_CHARACTER_SET_EXCEPTION_TEMPLATE,
    OFFLOAD_OP_NAME,
    OFFLOAD_STATS_COPY_EXCEPTION_TEXT,
    vverbose,
)
from goe.orchestration.logging_init import log, strict_version_ready, version
from goe.persistence.models import (
    INCREMENTAL_PREDICATE_TYPE_LIST,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
    INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_PREDICATE,
    INCREMENTAL_PREDICATE_TYPE_RANGE,
    INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
    OffloadMetadata,
)
from goe.serializers import decode_json
from goe.util.string_utils import (
    all_int_chars,
    csv_split,
)

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.backend_table import BackendTableInterface


def ora_single_item_query(opts, qry, ora_conn=None, params={}):
    if ora_conn is not None:
        c = ora_conn.cursor()
        try:
            row = c.execute(qry, params).fetchone()
            return row[0] if row else row
        finally:
            c.close()
    frontend_api = create_frontend_api(opts.db_type, opts, messages=None)
    try:
        row = frontend_api.execute_query_fetch_one(qry, query_params=params or None)
        return row[0] if row else row
    finally:
        frontend_api.close()


def get_db_unique_name(opts):
    if opts.db_type == offload_constants.DBTYPE_ORACLE:
        sql = """
SELECT SYS_CONTEXT('USERENV', 'DB_UNIQUE_NAME') ||
       CASE
          WHEN version >= 12
          THEN CASE
                  WHEN SYS_CONTEXT('USERENV', 'CDB_NAME') IS NOT NULL
                  THEN '_' || SYS_CONTEXT('USERENV', 'CON_NAME')
               END
       END
FROM  (
       SELECT TO_NUMBER(REGEXP_SUBSTR(version, '[0-9]+')) AS version
       FROM   v$instance
      )
"""
        return ora_single_item_query(opts, sql)
    if opts.db_type == offload_constants.DBTYPE_MSSQL:
        try:
            return opts.rdbms_dsn.split("=")[1]
        except Exception:
            return ""


def get_rdbms_db_name(opts, ora_conn=None):
    if opts.db_type == offload_constants.DBTYPE_ORACLE:
        sql = """
SELECT CASE
          WHEN version < 12
          THEN SYS_CONTEXT('USERENV', 'DB_NAME')
          ELSE SYS_CONTEXT('USERENV', 'CON_NAME')
       END
FROM  (
       SELECT TO_NUMBER(REGEXP_SUBSTR(version, '[0-9]+')) AS version
       FROM   v$instance
      )
"""
        return ora_single_item_query(opts, sql, ora_conn)
    if opts.db_type == offload_constants.DBTYPE_MSSQL:
        try:
            return opts.rdbms_dsn.split("=")[1]
        except:
            return ""


def get_db_charset(opts):
    return ora_single_item_query(
        opts,
        "SELECT value FROM nls_database_parameters WHERE parameter = 'NLS_CHARACTERSET'",
    )


def nls_lang_exists():
    return os.environ.get("NLS_LANG")


def nls_lang_has_charset():
    nls_lang = nls_lang_exists()
    if nls_lang:
        return "." in nls_lang
    return False


def set_nls_lang_default(opts):
    os.environ["NLS_LANG"] = ".%s" % get_db_charset(opts)


def check_and_set_nls_lang(opts, messages=None):
    """TODO: We believe that we need to have NLS_LANG set correctly in order for query_import to offload data correctly? If that is the case if/when we implement query_import for non-Oracle, we need to cater for this."""
    if opts.db_type == offload_constants.DBTYPE_ORACLE:
        if not nls_lang_exists():
            set_nls_lang_default(opts)
            if messages:
                messages.warning(
                    'NLS_LANG not specified in environment, setting to "%s"' % os.environ["NLS_LANG"],
                    ansi_code="red",
                )
        elif not nls_lang_has_charset():
            raise OffloadException(NLS_LANG_MISSING_CHARACTER_SET_EXCEPTION_TEMPLATE % os.environ["NLS_LANG"])


def get_offload_type(
    owner,
    table_name,
    hybrid_operation,
    incr_append_capable,
    partition_type,
    hybrid_metadata,
    messages,
    with_messages=True,
):
    """Wrapper for get_offload_type_for_config that caters for speculative retrievals of offload_type
    Used when deciding whether to auto-enable subpartition offloads
    """
    ipa_options_specified = active_data_append_options(hybrid_operation, partition_type=partition_type)
    messages.debug("ipa_options_specified: %s" % str(ipa_options_specified))
    offload_type, _ = get_offload_type_for_config(
        owner,
        table_name,
        hybrid_operation.offload_type,
        incr_append_capable,
        ipa_options_specified,
        hybrid_metadata,
        messages,
        with_messages=with_messages,
    )
    return offload_type


def bool_option_from_string(opt_name, opt_val):
    return orchestration_defaults.bool_option_from_string(opt_name, opt_val)


def normalise_owner_table_options(options):
    """target/base needed for role separation"""
    if not options.owner_table or len(options.owner_table.split(".")) != 2:
        raise OffloadOptionError("Option -t or --table required in form SCHEMA.TABLENAME")

    options.owner, options.table_name = options.owner_table.split(".")

    if not hasattr(options, "target_owner_name") or not options.target_owner_name:
        options.target_owner_name = options.owner_table

    if not hasattr(options, "base_owner_name") or not options.base_owner_name:
        options.base_owner_name = options.owner_table

    if len(options.target_owner_name.split(".")) != 2:
        raise OffloadOptionError("Option --target-name required in form SCHEMA.TABLENAME")

    options.target_owner, options.target_name = options.target_owner_name.split(".")
    options.base_owner, options.base_name = options.base_owner_name.upper().split(".")


def normalise_datatype_control_options(opts):
    def upper_or_default(opts, option_name, prior_name=None):
        if hasattr(opts, option_name):
            if getattr(opts, option_name, None):
                setattr(opts, option_name, getattr(opts, option_name).upper())
            elif prior_name and getattr(opts, prior_name, None):
                setattr(opts, option_name, getattr(opts, prior_name).upper())

    upper_or_default(opts, "integer_1_columns_csv")
    upper_or_default(opts, "integer_2_columns_csv")
    upper_or_default(opts, "integer_4_columns_csv")
    upper_or_default(opts, "integer_8_columns_csv")
    upper_or_default(opts, "integer_38_columns_csv")
    upper_or_default(opts, "date_columns_csv")
    upper_or_default(opts, "double_columns_csv")
    upper_or_default(opts, "variable_string_columns_csv")
    upper_or_default(opts, "large_binary_columns_csv")
    upper_or_default(opts, "large_string_columns_csv")
    upper_or_default(opts, "binary_columns_csv")
    upper_or_default(opts, "interval_ds_columns_csv")
    upper_or_default(opts, "interval_ym_columns_csv")
    upper_or_default(opts, "timestamp_columns_csv")
    upper_or_default(opts, "timestamp_tz_columns_csv")
    upper_or_default(opts, "unicode_string_columns_csv")

    if hasattr(opts, "decimal_columns_csv_list"):
        if opts.decimal_columns_csv_list is None:
            opts.decimal_columns_csv_list = []
        if opts.decimal_columns_type_list is None:
            opts.decimal_columns_type_list = []


def normalise_insert_select_options(opts):
    if opts.impala_insert_hint:
        opts.impala_insert_hint = opts.impala_insert_hint.upper()
        if opts.impala_insert_hint not in [IMPALA_SHUFFLE_HINT, IMPALA_NOSHUFFLE_HINT]:
            raise OffloadOptionError("Invalid value for --impala-insert-hint: %s" % opts.impala_insert_hint)

    if opts.offload_chunk_column:
        opts.offload_chunk_column = opts.offload_chunk_column.upper()


def normalise_offload_transport_method(options, orchestration_config):
    """offload_transport_method is a hidden option derived from other config and has its own normalisation

    If an override has been specified then check so we can fail early
    """
    if options.offload_transport_method:
        options.offload_transport_method = options.offload_transport_method.upper()
        validate_offload_transport_method(
            options.offload_transport_method,
            orchestration_config,
            exception_class=OptionValueError,
        )


def normalise_offload_transport_user_options(options):
    """Mustn't be an offload"""
    if not hasattr(options, "offload_transport_method"):
        return

    if options.offload_transport_small_table_threshold:
        options.offload_transport_small_table_threshold = normalise_size_option(
            options.offload_transport_small_table_threshold,
            strict_name="--offload-transport-small-table-threshold",
            exc_cls=OptionValueError,
        )
    options.offload_transport_consistent_read = bool_option_from_string(
        "OFFLOAD_TRANSPORT_CONSISTENT_READ/--offload-transport-consistent-read",
        options.offload_transport_consistent_read,
    )
    options.offload_transport_parallelism = check_opt_is_posint(
        "OFFLOAD_TRANSPORT_PARALLELISM/--offload-transport-parallelism",
        options.offload_transport_parallelism,
    )
    options.offload_transport_fetch_size = check_opt_is_posint(
        "OFFLOAD_TRANSPORT_FETCH_SIZE/--offload-transport-fetch-size",
        options.offload_transport_fetch_size,
    )
    if options.offload_transport_snapshot:
        options.offload_transport_snapshot = check_opt_is_posint(
            "--offload-transport-snapshot",
            options.offload_transport_snapshot,
        )

    verify_json_option(
        "OFFLOAD_TRANSPORT_SPARK_PROPERTIES/--offload-transport-spark-properties",
        options.offload_transport_spark_properties,
    )

    if hasattr(options, "offload_transport_validation_polling_interval"):
        if isinstance(options.offload_transport_validation_polling_interval, str) and (
            re.search(r"^[\d\.]+$", options.offload_transport_validation_polling_interval)
            or options.offload_transport_validation_polling_interval
            == str(offload_constants.OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED)
        ):
            options.offload_transport_validation_polling_interval = float(
                options.offload_transport_validation_polling_interval
            )
        elif not isinstance(options.offload_transport_validation_polling_interval, (int, float)):
            raise OffloadOptionError(
                'Invalid value "%s" for --offload-transport-validation-polling-interval'
                % options.offload_transport_validation_polling_interval
            )
    else:
        options.offload_transport_validation_polling_interval = 0


def valid_canonical_decimal_spec(prec, spec, max_decimal_precision, max_decimal_scale):
    if prec < 1 or prec > max_decimal_precision or spec < 0 or spec > max_decimal_scale or spec > prec:
        return False
    return True


def option_is_in_list(options, option_name, cli_name, validation_list, to_upper=True):
    if hasattr(options, option_name) and getattr(options, option_name):
        opt_val = getattr(options, option_name)
        opt_val = opt_val.upper() if to_upper else opt_val.lower()
        if opt_val not in validation_list:
            raise OptionValueError("Unsupported value for %s: %s" % (cli_name, opt_val))
        return opt_val
    return None


def normalise_options(options, normalise_owner_table=True):
    """User has requested a with-predicate predicate type without providing a predicate"""
    if options.vverbose:
        options.verbose = True
    elif options.quiet:
        options.vverbose = options.verbose = False

    if hasattr(options, "log_level") and options.log_level:
        options.log_level = options.log_level.lower()
        if options.log_level not in [
            offload_constants.LOG_LEVEL_INFO,
            offload_constants.LOG_LEVEL_DETAIL,
            offload_constants.LOG_LEVEL_DEBUG,
        ]:
            raise OptionValueError("Invalid value for LOG_LEVEL: %s" % options.log_level)

    if options.reset_backend_table and options.reuse_backend_table:
        raise OptionValueError(
            "Conflicting options --reset-backend-table and --reuse-backend-table cannot be used together"
        )

    if options.reset_backend_table and not options.force:
        options.force = True

    if not options.execute:
        options.force = False

    if options.storage_compression:
        options.storage_compression = options.storage_compression.upper()
        if options.storage_compression not in [
            "NONE",
            "HIGH",
            "MED",
            offload_constants.FILE_STORAGE_COMPRESSION_CODEC_GZIP,
            offload_constants.FILE_STORAGE_COMPRESSION_CODEC_SNAPPY,
            offload_constants.FILE_STORAGE_COMPRESSION_CODEC_ZLIB,
        ]:
            raise OptionValueError(
                "Invalid value for --storage-compression, valid values: HIGH|MED|NONE|GZIP|ZLIB|SNAPPY"
            )

    if normalise_owner_table:
        normalise_owner_table_options(options)

    normalise_offload_transport_user_options(options)

    if options.target == offload_constants.DBTYPE_IMPALA:
        options.offload_distribute_enabled = False

    normalise_less_than_options(options, exc_cls=OffloadOptionError)

    options.offload_type = option_is_in_list(options, "offload_type", "--offload-type", ["FULL", "INCREMENTAL"])
    options.ipa_predicate_type = option_is_in_list(
        options,
        "ipa_predicate_type",
        "--offload-predicate-type",
        [
            INCREMENTAL_PREDICATE_TYPE_LIST,
            INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
            INCREMENTAL_PREDICATE_TYPE_RANGE,
            INCREMENTAL_PREDICATE_TYPE_PREDICATE,
            INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
            INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
        ],
    )
    if (
        options.ipa_predicate_type
        in [
            INCREMENTAL_PREDICATE_TYPE_PREDICATE,
            INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
            INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
        ]
        and not options.offload_predicate
    ):
        raise OptionValueError(
            "Option --offload-predicate is required when requesting INCREMENTAL_PREDICATE_TYPE: %s"
            % options.ipa_predicate_type
        )

    options.skip = options.skip if type(options.skip) is list else options.skip.lower().split(",")

    if options.offload_partition_lower_value and not all_int_chars(
        options.offload_partition_lower_value, allow_negative=True
    ):
        raise OptionValueError(
            "Invalid value for --partition-lower-value, must be an integral number: %s"
            % options.offload_partition_lower_value
        )

    if options.offload_partition_upper_value and not all_int_chars(
        options.offload_partition_upper_value, allow_negative=True
    ):
        raise OptionValueError(
            "Invalid value for --partition-upper-value, must be an integral number: %s"
            % options.offload_partition_upper_value
        )

    normalise_verify_options(options)
    normalise_data_sampling_options(options)
    normalise_offload_predicate_options(options)
    normalise_datatype_control_options(options)
    normalise_stats_options(options, options.target)


def verify_json_option(option_name, option_value):
    if option_value:
        try:
            properties = decode_json(option_value)
            if not isinstance(properties, dict):
                raise ValueError("Expected JSON object")

            invalid_props = [k for k, v in properties.items() if type(v) not in (str, int, float)]
            if invalid_props:
                [
                    log(
                        "Invalid property value for key/value pair: %s: %s" % (k, properties[k]),
                        detail=vverbose,
                    )
                    for k in invalid_props
                ]
                raise OffloadOptionError(
                    "Invalid property value in %s for keys: %s" % (option_name, str(invalid_props))
                )
        except OffloadOptionError:
            raise
        except Exception as ve:
            log(traceback.format_exc(), vverbose)
            raise OffloadOptionError("Invalid JSON value for %s: %s" % (option_name, str(ve)))


def get_default_location_fs_scheme(offload_target_table):
    """Return the fs scheme (e.g. hdfs or s3a) from the tables default location"""
    if offload_target_table.get_default_location():
        return get_scheme_from_location_uri(offload_target_table.get_default_location())
    return None


def normalise_storage_options(options, backend_api):
    options.storage_format = options.storage_format or backend_api.default_storage_format()
    if not backend_api.is_valid_storage_format(options.storage_format):
        raise OffloadException(
            "--storage-format value is not valid with %s: %s" % (backend_api.backend_db_name(), options.storage_format)
        )
    options.storage_compression = backend_api.default_storage_compression(
        options.storage_compression, options.storage_format
    )
    if not backend_api.is_valid_storage_compression(options.storage_compression, options.storage_format):
        raise OffloadException(
            "--storage-format value is not valid with %s: %s"
            % (backend_api.backend_db_name(), options.storage_compression)
        )


class BaseOperation:
    """Over time OffloadOperation and PresentOperation are converging. Too risky at the moment
    to completely merge them, using this base class to centralise some code.
    """

    allow_decimal_scale_rounding: Any
    allow_floating_point_conversions: Any
    allow_nanosecond_timestamp_columns: Any
    base_name: Any
    base_owner: Any
    base_owner_name: Any
    bucket_hash_col: Any
    column_transformation_list: Any
    compress_load_table: Any
    compute_load_table_stats: Any
    create_backend_db: Any
    data_sample_parallelism: Any
    data_sample_pct: Any
    date_columns_csv: Any
    ddl_file: Any
    decimal_columns_csv_list: Any
    decimal_columns_type_list: Any
    decimal_padding_digits: Any
    double_columns_csv: Any
    equal_to_values: Any
    error_after_step: Any
    error_before_step: Any
    execute: bool
    force: Any
    hive_column_stats: Any
    hwm_in_hybrid_view: Any
    impala_insert_hint: Any
    inflight_offload_predicate: Any
    integer_1_columns_csv: Any
    integer_2_columns_csv: Any
    integer_4_columns_csv: Any
    integer_8_columns_csv: Any
    integer_38_columns_csv: Any
    ipa_predicate_type: Any
    less_or_equal_value: Any
    less_than_value: Any
    max_offload_chunk_count: Any
    max_offload_chunk_size: Any
    not_null_columns_csv: Any
    offload_by_subpartition: Any
    offload_chunk_column: Any
    offload_distribute_enabled: Any
    offload_fs_container: Any
    offload_fs_prefix: Any
    offload_fs_scheme: Any
    offload_partition_columns: Any
    offload_partition_functions: Any
    offload_partition_granularity: Any
    offload_partition_lower_value: Any
    offload_partition_upper_value: Any
    offload_predicate: Any
    offload_predicate_modify_hybrid_view: Any
    offload_stats_method: Any
    offload_transport_consistent_read: Any
    offload_transport_dsn: Any
    offload_transport_fetch_size: Any
    offload_transport_jvm_overrides: Any
    offload_transport_method: Any
    offload_transport_parallelism: Any
    offload_transport_queue_name: Any
    offload_transport_small_table_threshold: Any
    offload_transport_snapshot: Any
    offload_transport_spark_properties: Any
    offload_transport_validation_polling_interval: Any
    offload_type: Any
    older_than_date: Any
    older_than_days: Any
    operation_name: Any
    owner: Any
    owner_table: Any
    partition_names: list[str]
    partition_names_csv: Any
    pre_offload_hybrid_metadata: Any
    preserve_load_table: Any
    purge_backend_table: Any
    reset_backend_table: Any
    reset_hybrid_view: Any
    reuse_backend_table: Any
    skip: Any
    sort_columns: Any
    sort_columns_csv: Any
    storage_compression: Any
    storage_format: Any
    suppress_stdout: Any
    synthetic_partition_digits: Any
    table_name: Any
    target_name: Any
    target_owner: Any
    target_owner_name: Any
    target_table_name: Any
    timestamp_tz_columns_csv: Any
    unicode_string_columns_csv: Any
    variable_string_columns_csv: Any
    ver_check: Any
    verify_parallelism: Any
    verify_row_count: Any

    def __init__(
        self,
        operation_name,
        config,
        messages,
        repo_client=None,
        execution_id=None,
        max_hybrid_name_length=None,
        **kwargs,
    ):
        """This is a hidden partition filter we can feed into "find partition" logic. Not exposed to the user The sorts of checks we do here do not require a backend connection: do_not_connect=True"""
        self.operation_name = operation_name
        self.execution_id = execution_id
        self.max_hybrid_name_length = max_hybrid_name_length
        self._orchestration_config = config
        self._messages = messages
        self.hwm_in_hybrid_view = None
        self.inflight_offload_predicate = None
        self.less_or_equal_value = None
        self.goe_version = strict_version_ready(version())
        self._existing_metadata = None

        self.offload_stats_method = self.offload_stats_method or orchestration_defaults.offload_stats_method_default(
            operation_name=operation_name
        )
        if self.offload_stats_method:
            self.offload_stats_method = self.offload_stats_method.upper()

        backend_api = create_backend_api(
            config.target,
            config,
            messages,
            dry_run=(not self.execute),
            do_not_connect=True,
        )

        if self.offload_stats_method == offload_constants.OFFLOAD_STATS_METHOD_COPY and not (
            backend_api.table_stats_get_supported() and backend_api.table_stats_set_supported()
        ):
            raise OptionValueError(
                "%s for %s backend: %s"
                % (
                    OFFLOAD_STATS_COPY_EXCEPTION_TEXT,
                    backend_api.backend_db_name(),
                    self.offload_stats_method,
                )
            )

        if self.offload_stats_method == offload_constants.OFFLOAD_STATS_METHOD_COPY and self.offload_predicate:
            messages.warning("Offload stats method COPY in incompatible with predicate-based offload")
            self.offload_stats_method = offload_constants.OFFLOAD_STATS_METHOD_NATIVE

        self._hash_distribution_threshold = config.hash_distribution_threshold

        self.max_offload_chunk_size = normalise_size_option(
            self.max_offload_chunk_size,
            binary_sizes=True,
            strict_name="MAX_OFFLOAD_CHUNK_SIZE/--max-offload-chunk-size",
            exc_cls=OptionValueError,
        )

        self.max_offload_chunk_count = check_opt_is_posint("--max-offload-chunk-count", self.max_offload_chunk_count)
        if (self.max_offload_chunk_count < 1) or (self.max_offload_chunk_count > 1000):
            raise OptionValueError(
                "Option MAX_OFFLOAD_CHUNK_COUNT/--max-offload-chunk-count must be between 1 and 1000"
            )

        self.sort_columns_csv = self.sort_columns_csv.upper() if self.sort_columns_csv else None
        self.sort_columns = None

        normalise_less_than_options(self)
        normalise_insert_select_options(self)
        normalise_owner_table_options(self)
        normalise_storage_options(self, backend_api)

        self._repo_client = None
        if repo_client:
            self._repo_client = repo_client

        self.partition_names_csv = self.partition_names_csv.upper() if self.partition_names_csv else None
        self.partition_names = self.partition_names_csv.split(",") if self.partition_names_csv else []

    @property
    def repo_client(self):
        if self._repo_client is None:
            self._repo_client = create_repository_client(
                self._orchestration_config,
                self._messages,
                dry_run=bool(not self.execute),
                trace_action="repo_client(OffloadOperation)",
            )
        return self._repo_client

    def vars(self):
        raise NotImplementedError("vars() has not been implemented for this operation")

    def default_bucket_hash_col(self, source_table, messages):
        raise NotImplementedError("default_bucket_hash_col() has not been implemented for this operation")

    def override_bucket_hash_col(self, new_bucket_hash_col, messages):
        """Pass messages as None to suppress any warnings/notices"""
        upper_or_none = lambda x: x.upper() if x else x
        if self.bucket_hash_col and upper_or_none(new_bucket_hash_col) != upper_or_none(self.bucket_hash_col):
            messages.notice("Retaining bucket hash column from original offload (ignoring --bucket-hash-column)")
        self.bucket_hash_col = upper_or_none(new_bucket_hash_col)

    def validate_bucket_hash_col(
        self,
        column_names,
        rdbms_table,
        messages,
        bucket_hash_column_supported,
    ):
        if not bucket_hash_column_supported:
            self.bucket_hash_col = None
            return

        if self.bucket_hash_col and self.bucket_hash_col.upper() not in column_names:
            raise OffloadException(
                "Column specified for --bucket-hash-column does not exist: %s" % self.bucket_hash_col.upper()
            )

        if not self.bucket_hash_col:
            if rdbms_table:
                size = (
                    rdbms_table.get_max_partition_size() if rdbms_table.is_partitioned() else rdbms_table.size_in_bytes
                )
                if bucket_hash_column_supported and (size or 0) >= self._hash_distribution_threshold:
                    self.bucket_hash_col = self.default_bucket_hash_col(rdbms_table, messages)
                    if not self.bucket_hash_col:
                        raise OffloadException(
                            "Unable to select a default bucket hash column, table cannot be offloaded"
                        )
        else:
            self.bucket_hash_col = self.bucket_hash_col.upper()

    def get_hybrid_metadata(self, force: bool = False) -> OffloadMetadata | None:
        """Get metadata for current table and add to state
        force can be used to ensure we read regardless of the reset status of the operation, but not store in state.
        """
        if not self._existing_metadata and not self.reset_backend_table:
            self._existing_metadata = self.repo_client.get_offload_metadata(self.owner, self.table_name)
        elif force:
            return self.repo_client.get_offload_metadata(self.owner, self.table_name)
        return self._existing_metadata

    def reset_hybrid_metadata(self, new_metadata):
        """If we're not in execute mode then we need to re-use the in-flight metadata"""
        if self.execute:
            self._existing_metadata = self.get_hybrid_metadata(force=True)
        else:
            self._existing_metadata = new_metadata
        return self._existing_metadata

    def enable_reset_backend_table(self):
        """If we need to programmatically enable backend reset then we also need to drop cached metadata."""
        self.reset_backend_table = True
        self._existing_metadata = None

    def set_bucket_info_from_metadata(self, existing_metadata, messages):
        if existing_metadata:
            self.override_bucket_hash_col(existing_metadata.offload_bucket_column, messages)
        else:
            self.bucket_hash_col = None

    def set_offload_partition_functions_from_metadata(self, existing_metadata):
        if existing_metadata and existing_metadata.offload_partition_functions:
            self.offload_partition_functions = csv_split(existing_metadata.offload_partition_functions)
        else:
            self.offload_partition_functions = None

    def set_offload_partition_functions(self, offload_partition_functions_override):
        if isinstance(offload_partition_functions_override, str):
            self.offload_partition_functions = csv_split(offload_partition_functions_override)
        else:
            self.offload_partition_functions = offload_partition_functions_override

    def defaults_for_fresh_offload(self, offload_source_table, offload_options, messages, offload_target_table):
        self.validate_partition_columns(
            offload_source_table.partition_columns,
            offload_source_table.columns,
            offload_target_table,
            messages,
            offload_source_table.partition_type,
        )
        self.validate_bucket_hash_col(
            offload_source_table.get_column_names(),
            offload_source_table,
            messages,
            offload_target_table.bucket_hash_column_supported(),
        )

    def defaults_for_existing_table(
        self,
        offload_target_table: "BackendTableInterface",
        messages: OffloadMessages,
    ) -> OffloadMetadata | None:
        """Default bucket hash column and datatype mappings from existing table
        This is required for setting up a pre-existing table and is used by
        incremental partition append.
        Pass messages as None to suppress any warnings/notices.

        If the table is empty but has metadata then we need to abort unless using --reuse-backend-table. If the table has rows but no metadata then we need to abort. If the table is empty then we allow the offload to continue. Only with --offload-predicate can we transition between INCREMENTAL_PREDICATE_TYPEs We are overwriting user input with value from metadata
        """
        existing_metadata = self.get_hybrid_metadata()

        if existing_metadata:
            if not offload_target_table.has_rows() and not self.reuse_backend_table:
                raise OffloadException(
                    offload_constants.METADATA_EMPTY_TABLE_EXCEPTION_TEMPLATE
                    % (self.owner.upper(), self.table_name.upper())
                )
        else:
            if offload_target_table.has_rows():
                raise OffloadException(
                    offload_constants.MISSING_METADATA_EXCEPTION_TEMPLATE % (self.owner, self.table_name)
                )
            messages.log(
                f"Allowing Offload to populate existing empty table: {offload_target_table.db_name}.{offload_target_table.table_name}",
                detail=VERBOSE,
            )
            return None

        self.set_bucket_info_from_metadata(existing_metadata, messages)

        if not self.offload_predicate or (
            self.offload_predicate and self.ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST
        ):
            if self.ipa_predicate_type and self.ipa_predicate_type != existing_metadata.incremental_predicate_type:
                raise OffloadException(offload_constants.IPA_PREDICATE_TYPE_CHANGE_EXCEPTION_TEXT)
            self.ipa_predicate_type = existing_metadata.incremental_predicate_type

        self.pre_offload_hybrid_metadata = existing_metadata
        self.offload_by_subpartition = bool(existing_metadata and existing_metadata.is_subpartition_offload())
        self.set_offload_partition_functions_from_metadata(existing_metadata)
        return existing_metadata

    def default_ipa_predicate_type(self, offload_source_table, messages):
        """ipa_predicate_type and offload_by_subpartition are intertwined, it's hard to
        set one without the other. We do some defaulting here, then subpartition work
        and finally validate ipa_predicate_type makes sense.

        No subpartition complications so use check_ipa_predicate_type_option_conflicts to throw exception
        """
        if not self.ipa_predicate_type and not self.offload_predicate and not self.offload_by_subpartition:
            rpa_opts_set = active_data_append_options(self, partition_type=OFFLOAD_PARTITION_TYPE_RANGE)
            lpa_opts_set = active_data_append_options(self, partition_type=OFFLOAD_PARTITION_TYPE_LIST)
            if offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_LIST and lpa_opts_set:
                self.ipa_predicate_type = INCREMENTAL_PREDICATE_TYPE_LIST
                messages.log(
                    "Defaulting INCREMENTAL_PREDICATE_TYPE=%s due to options: %s"
                    % (self.ipa_predicate_type, lpa_opts_set),
                    detail=VVERBOSE,
                )
            elif offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_LIST and rpa_opts_set:
                unsupported_range_types = offload_source_table.unsupported_partition_data_types(
                    partition_type_override=OFFLOAD_PARTITION_TYPE_RANGE
                )
                if unsupported_range_types:
                    messages.debug(
                        "default_ipa_predicate_type for LIST has unsupported_range_types: %s"
                        % str(unsupported_range_types)
                    )
                if not unsupported_range_types or not offload_source_table.offload_by_subpartition_capable():
                    self.ipa_predicate_type = INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE
                    messages.log(
                        "Defaulting INCREMENTAL_PREDICATE_TYPE=%s due to options: %s"
                        % (self.ipa_predicate_type, rpa_opts_set),
                        detail=VVERBOSE,
                    )
                    check_ipa_predicate_type_option_conflicts(self, rdbms_table=offload_source_table)
            elif offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_RANGE and rpa_opts_set:
                self.ipa_predicate_type = INCREMENTAL_PREDICATE_TYPE_RANGE
                messages.log(
                    "Defaulting INCREMENTAL_PREDICATE_TYPE=%s due to options: %s"
                    % (self.ipa_predicate_type, rpa_opts_set),
                    detail=VVERBOSE,
                )

    def validate_partition_columns(
        self,
        rdbms_partition_columns,
        rdbms_columns,
        backend_table,
        messages,
        rdbms_partition_type=None,
        backend_columns=None,
    ):
        """Validate offload_partition_columns and offload_partition_granularity attributes.
        Applies suitable defaults and ensures corresponding values are compatible with each other.
        backend_columns is used by join pushdown to spot when dates are offloaded as strings.
        """
        self.offload_partition_columns = validate_offload_partition_columns(
            self.offload_partition_columns,
            rdbms_columns,
            rdbms_partition_columns,
            rdbms_partition_type,
            self.offload_partition_functions,
            backend_table,
            messages,
            self.offload_chunk_column,
        )

        self.offload_partition_functions = validate_offload_partition_functions(
            self.offload_partition_functions,
            self.offload_partition_columns,
            backend_table,
            messages,
        )

        self.offload_partition_granularity = validate_offload_partition_granularity(
            self.offload_partition_granularity,
            self.offload_partition_columns,
            self.offload_partition_functions,
            rdbms_columns,
            rdbms_partition_columns,
            rdbms_partition_type,
            backend_table,
            messages,
            getattr(self, "variable_string_columns_csv", None),
            backend_columns=backend_columns,
        )

        if self.offload_partition_columns:
            messages.notice(
                "Partitioning backend table by: %s" % ",".join(self.offload_partition_columns),
                detail=VERBOSE,
            )
            messages.log(
                "Partition granularities: %s" % ",".join(self.offload_partition_granularity),
                detail=VVERBOSE,
            )

    def set_partition_info_on_canonical_columns(self, canonical_columns, rdbms_columns, backend_table):
        def get_partition_info(rdbms_column):
            return offload_options_to_partition_info(
                self.offload_partition_columns,
                self.offload_partition_functions,
                self.offload_partition_granularity,
                self.offload_partition_lower_value,
                self.offload_partition_upper_value,
                self.synthetic_partition_digits,
                rdbms_column,
                backend_table,
            )

        new_columns = []
        for canonical_column in canonical_columns:
            rdbms_column = match_table_column(canonical_column.name, rdbms_columns)
            canonical_column.partition_info = get_partition_info(rdbms_column)
            new_columns.append(canonical_column)
        return new_columns

    def validate_ipa_predicate_type(self, offload_source_table):
        """Check that ipa_predicate_type is valid for the offload source table.

        This is an incremental append offload with a modified user requested predicate type. We can validate the user requested transition is valid, valid_combinations in list of pairs below: (pre-offload predicate type, newly requested predicate type) First time predicate based offloads can only be PREDICATE
        """
        if not self.ipa_predicate_type:
            return
        valid_combinations = [
            (OFFLOAD_PARTITION_TYPE_RANGE, INCREMENTAL_PREDICATE_TYPE_RANGE),
            (
                OFFLOAD_PARTITION_TYPE_RANGE,
                INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
            ),
            (OFFLOAD_PARTITION_TYPE_LIST, INCREMENTAL_PREDICATE_TYPE_LIST),
            (OFFLOAD_PARTITION_TYPE_LIST, INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE),
            (
                OFFLOAD_PARTITION_TYPE_LIST,
                INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
            ),
        ]
        if (
            self.ipa_predicate_type != INCREMENTAL_PREDICATE_TYPE_PREDICATE
            and (offload_source_table.partition_type, self.ipa_predicate_type) not in valid_combinations
        ):
            raise OffloadException(
                "%s: %s/%s"
                % (
                    offload_constants.IPA_PREDICATE_TYPE_EXCEPTION_TEXT,
                    self.ipa_predicate_type,
                    offload_source_table.partition_type,
                )
            )

        check_ipa_predicate_type_option_conflicts(self, rdbms_table=offload_source_table)

        if (
            self.pre_offload_hybrid_metadata
            and self.pre_offload_hybrid_metadata.incremental_predicate_type != self.ipa_predicate_type
        ):
            if self.offload_predicate:
                valid_combinations = [
                    (
                        INCREMENTAL_PREDICATE_TYPE_RANGE,
                        INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
                    ),
                    (
                        INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
                        INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
                    ),
                ]
            else:
                valid_combinations = [
                    (
                        INCREMENTAL_PREDICATE_TYPE_RANGE_AND_PREDICATE,
                        INCREMENTAL_PREDICATE_TYPE_RANGE,
                    ),
                    (
                        INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE_AND_PREDICATE,
                        INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE,
                    ),
                ]
            if (
                self.pre_offload_hybrid_metadata.incremental_predicate_type,
                self.ipa_predicate_type,
            ) not in valid_combinations:
                raise OffloadException(
                    "INCREMENTAL_PREDICATE_TYPE %s is not valid for existing %s configuration"
                    % (
                        self.ipa_predicate_type,
                        self.pre_offload_hybrid_metadata.incremental_predicate_type,
                    )
                )

        if (
            not self.pre_offload_hybrid_metadata
            and self.offload_predicate
            and self.ipa_predicate_type != INCREMENTAL_PREDICATE_TYPE_PREDICATE
        ):
            raise OffloadException(
                "%s: %s"
                % (
                    offload_constants.IPA_PREDICATE_TYPE_FIRST_OFFLOAD_EXCEPTION_TEXT,
                    self.ipa_predicate_type,
                )
            )

    def validate_offload_by_subpartition(self, offload_source_table, messages, hybrid_metadata):
        """Method to be used for an offload to auto switch on offload_by_subpartition if sensible
        or validate correct use of --offload-by-subpartition when manually enabled.
        For IPA offloads we pickup the value from metadata and ignore user input.

        The user has already indicated they want LIST as RANGE so no auto enabling of offload_by_subpartition Ensure the use of --offload-by-subpartition was valid If this is a fresh offload then we need to default ipa_predicate_type based on subpartition level the table is capable of supporting offload_by_subpartition, now we need to check the operation makes sense the fn below tells offload_source_table to return subpartition scheme details in place of partition scheme details ipa_predicate_type was set based on top level so we need to blank it out
        """
        allow_auto_enable = True
        if hybrid_metadata:
            allow_auto_enable = False
            self.offload_by_subpartition = bool(hybrid_metadata and hybrid_metadata.is_subpartition_offload())
            if self.offload_by_subpartition:
                messages.log(
                    "Retaining --offload-by-subpartition from offloaded table",
                    detail=VVERBOSE,
                )

        if (
            allow_auto_enable
            and offload_source_table.partition_type == OFFLOAD_PARTITION_TYPE_LIST
            and self.ipa_predicate_type == INCREMENTAL_PREDICATE_TYPE_LIST_AS_RANGE
        ):
            allow_auto_enable = False

        if self.offload_by_subpartition:
            if offload_source_table.offload_by_subpartition_capable():
                offload_source_table.enable_offload_by_subpartition()
                if not hybrid_metadata:
                    self.default_ipa_predicate_type(offload_source_table, messages)
            else:
                messages.warning("Ignoring --offload-by-subpartition because partition scheme is unsupported")
                self.offload_by_subpartition = False
        elif allow_auto_enable and offload_source_table.offload_by_subpartition_capable(valid_for_auto_enable=True):
            messages.debug("Auto enable of offload_by_subpartition is True, checking details...")
            incr_append_capable = True
            offload_type = get_offload_type(
                self.owner,
                self.table_name,
                self,
                incr_append_capable,
                offload_source_table.subpartition_type,
                hybrid_metadata,
                messages,
                with_messages=False,
            )
            if offload_type == "INCREMENTAL":
                messages.notice(
                    "Setting --offload-by-subpartition due to partition scheme: %s/%s"
                    % (
                        offload_source_table.partition_type,
                        offload_source_table.subpartition_type,
                    )
                )
                self.offload_by_subpartition = True
                offload_source_table.enable_offload_by_subpartition()
                self.ipa_predicate_type = None
            else:
                messages.log(
                    "Leaving --offload-by-subpartition=false due to OFFLOAD_TYPE: %s" % offload_type,
                    detail=VVERBOSE,
                )

    def validate_sort_columns(
        self,
        offload_source_table: OffloadSourceTableInterface,
        messages: OffloadMessages,
        offload_options: "OrchestrationConfig",
        backend_cols: Any,
        hybrid_metadata: Any,
        backend_api: Any = None,
    ) -> None:
        """Default sort_columns for storage index benefit if not specified by the user.
        sort_columns_csv: The incoming option string which can be a CSV list of column names or:
            - the special token SORT_COLUMNS_NO_CHANGE which identifies the user has not asked for a change.
            - the special token SORT_COLUMNS_NONE which identifies the user has not asked for no sort columns.
        sort_columns: A Python list of column names defined by the user.
        backend_cols: A standalone parameter because this function may be used on tables that do not yet exist.

        Only warn the user if they input a specific value Sorting is supported
        """

        created_api = False
        if backend_api is None:
            backend_api = create_backend_api(
                offload_options.target,
                offload_options,
                messages,
                dry_run=bool(not self.execute),
            )
            created_api = False

        try:
            if not backend_api.sorted_table_supported():
                if self.sort_columns_csv and self.sort_columns_csv != offload_constants.SORT_COLUMNS_NO_CHANGE:
                    messages.warning(
                        "Ignoring --sort-columns in %s version %s"
                        % (backend_api.backend_db_name(), backend_api.target_version())
                    )
                self.sort_columns = None
                return

            if hybrid_metadata == "NONE":
                hybrid_metadata = self.get_hybrid_metadata()

            self.sort_columns = sort_columns_csv_to_sort_columns(
                self.sort_columns_csv,
                hybrid_metadata,
                offload_source_table,
                backend_cols,
                backend_api,
                messages,
            )
        finally:
            if created_api:
                backend_api.close()

    def _gen_base_canonical_overrides(
        self,
        backend_table,
        max_decimal_precision=None,
        max_decimal_scale=None,
        columns_override=None,
    ):
        max_decimal_precision = max_decimal_precision or 38
        max_decimal_scale = max_decimal_scale or 38
        reference_columns = columns_override or backend_table.get_columns()
        canonical_columns: list[Any] = []
        if self.integer_1_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_INTEGER_1,
                    self.integer_1_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        if self.integer_2_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_INTEGER_2,
                    self.integer_2_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        if self.integer_4_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_INTEGER_4,
                    self.integer_4_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        if self.integer_8_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_INTEGER_8,
                    self.integer_8_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        if self.integer_38_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_INTEGER_38,
                    self.integer_38_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        if self.date_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_DATE,
                    self.date_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        if self.decimal_columns_csv_list:
            assert type(self.decimal_columns_csv_list) is list, "%s is not list" % type(self.decimal_columns_csv_list)
            assert type(self.decimal_columns_type_list) is list, "%s is not list" % type(self.decimal_columns_type_list)
            if not self.decimal_columns_type_list or len(self.decimal_columns_csv_list) != len(
                self.decimal_columns_type_list
            ):
                log(
                    "--decimal-columns unbalanced list: %s" % str(self.decimal_columns_csv_list),
                    detail=vverbose,
                )
                log(
                    "--decimal-columns-type unbalanced list: %s" % str(self.decimal_columns_type_list),
                    detail=vverbose,
                )
                raise OffloadException(
                    "Unbalanced --decimal-columns, --decimal-columns-type pairs (--decimal-columns * %d, --decimal-columns-type * %d)"
                    % (
                        len(self.decimal_columns_csv_list),
                        len(self.decimal_columns_type_list or []),
                    )
                )
            for col_csv, spec_csv in zip(self.decimal_columns_csv_list, self.decimal_columns_type_list):
                if len(spec_csv.split(",")) != 2 or not re.match(r"^([1-9][0-9]?)\s*,\s*([0-9][0-9]?)$", spec_csv):
                    raise OffloadException(
                        "--decimal-columns-type "
                        + DECIMAL_COL_TYPE_SYNTAX_TEMPLATE.format(p=max_decimal_precision, s=max_decimal_scale)
                    )
                spec = [int(num) for num in spec_csv.split(",")]
                if not valid_canonical_decimal_spec(spec[0], spec[1], max_decimal_precision, max_decimal_scale):
                    raise OffloadException(
                        "--decimal-columns-type "
                        + DECIMAL_COL_TYPE_SYNTAX_TEMPLATE.format(p=max_decimal_precision, s=max_decimal_scale)
                    )
                if spec[0] > backend_table.max_decimal_precision():
                    raise OffloadException(
                        "--decimal-columns-type precision is beyond backend maximum: %s > %s"
                        % (spec[0], backend_table.max_decimal_precision())
                    )
                if spec[1] > backend_table.max_decimal_scale():
                    raise OffloadException(
                        "--decimal-columns-type scale is beyond backend maximum: %s > %s"
                        % (spec[1], backend_table.max_decimal_scale())
                    )
                canonical_columns.extend(
                    canonical_columns_from_columns_csv(
                        GOE_TYPE_DECIMAL,
                        col_csv,
                        canonical_columns,
                        reference_columns,
                        precision=spec[0],
                        scale=spec[1],
                    )
                )
        if self.timestamp_tz_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_TIMESTAMP_TZ,
                    self.timestamp_tz_columns_csv,
                    canonical_columns,
                    reference_columns,
                    scale=backend_table.max_datetime_scale(),
                )
            )
        return canonical_columns

    def _setup_offload_step(self, messages):
        assert messages
        messages.setup_offload_step(
            skip=self.skip,
            error_before_step=self.error_before_step,
            error_after_step=self.error_after_step,
            repo_client=self.repo_client,
        )

    def _vars(self, expected_args):
        """Return a dictionary of official attributes, none of the convenience attributes/methods we also store"""
        return {k: v for k, v in vars(self).items() if k in expected_args}


class OffloadOperation(BaseOperation):
    """Logic and values related to the process of offloading from OffloadSourceTable to a backend system"""

    def __init__(
        self,
        config,
        messages,
        repo_client=None,
        execution_id=None,
        max_hybrid_name_length=None,
        **kwargs,
    ):
        unexpected_keys = [k for k in kwargs if k not in EXPECTED_OFFLOAD_ARGS]
        assert not unexpected_keys, "Unexpected OffloadOperation keys: %s" % unexpected_keys
        vars(self).update(kwargs)

        BaseOperation.__init__(
            self,
            OFFLOAD_OP_NAME,
            config,
            messages,
            repo_client=repo_client,
            execution_id=execution_id,
            max_hybrid_name_length=max_hybrid_name_length,
        )

        normalise_stats_options(self, config.target)

        self.pre_offload_hybrid_metadata = None

        normalise_offload_transport_user_options(self)
        normalise_offload_transport_method(self, config)
        normalise_offload_predicate_options(self)
        normalise_verify_options(self)
        normalise_data_sampling_options(self)
        normalise_ddl_file(self, config, messages)

        self._setup_offload_step(messages)

    def vars(self):
        """Return a dictionary of official attributes, none of the convenience attributes/methods we also store"""
        return self._vars(EXPECTED_OFFLOAD_ARGS)

    def default_bucket_hash_col(self, source_table, messages):
        """Choose a default hashing column in order of preference below:
        1) If single column PK use that
        2) Choose most selective column based on optimiser stats
           Calculation for this is take NDV and reduce it proportionally to
           the number of NULLs in the column, then pick most selective
        3) No stats? Take first column from list of columns - and warn
        """
        return_hash_col = None

        if len(source_table.get_primary_key_columns()) == 1:
            return_hash_col = source_table.get_primary_key_columns()[0]
            messages.notice("Using primary key singleton %s as --bucket-hash-column" % return_hash_col.upper())
        elif source_table.stats_num_rows:
            return_hash_col = source_table.get_hash_bucket_candidate()
            if return_hash_col:
                messages.notice(
                    "Using selective column %s as --bucket-hash-column, based on optimizer statistics"
                    % return_hash_col.upper()
                )

        if not return_hash_col:
            return_hash_col = source_table.get_hash_bucket_last_resort()
            if return_hash_col:
                messages.warning(
                    "Using column %s as --bucket-hash-column, in lieu of primary key and optimizer statistics"
                    % return_hash_col.upper()
                )

        return return_hash_col

    def gen_canonical_overrides(self, backend_table, columns_override=None):
        """For Offload"""
        reference_columns = columns_override or backend_table.get_columns()
        canonical_columns = self._gen_base_canonical_overrides(
            backend_table,
            backend_table.max_decimal_precision(),
            backend_table.max_decimal_scale(),
            columns_override=reference_columns,
        )
        if self.double_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_DOUBLE,
                    self.double_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        if self.variable_string_columns_csv:
            canonical_columns.extend(
                canonical_columns_from_columns_csv(
                    GOE_TYPE_VARIABLE_STRING,
                    self.variable_string_columns_csv,
                    canonical_columns,
                    reference_columns,
                )
            )
        return canonical_columns

    @staticmethod
    def from_options(
        options,
        config,
        messages,
        repo_client=None,
        execution_id=None,
        max_hybrid_name_length=None,
    ):
        return OffloadOperation(
            config,
            messages,
            repo_client=repo_client,
            execution_id=execution_id,
            max_hybrid_name_length=max_hybrid_name_length,
            allow_decimal_scale_rounding=options.allow_decimal_scale_rounding,
            allow_floating_point_conversions=options.allow_floating_point_conversions,
            allow_nanosecond_timestamp_columns=options.allow_nanosecond_timestamp_columns,
            bucket_hash_col=options.bucket_hash_col,
            column_transformation_list=options.column_transformation_list,
            compress_load_table=options.compress_load_table,
            compute_load_table_stats=options.compute_load_table_stats,
            create_backend_db=options.create_backend_db,
            data_sample_parallelism=options.data_sample_parallelism,
            data_sample_pct=options.data_sample_pct,
            date_columns_csv=options.date_columns_csv,
            ddl_file=options.ddl_file,
            decimal_columns_csv_list=options.decimal_columns_csv_list,
            decimal_columns_type_list=options.decimal_columns_type_list,
            decimal_padding_digits=options.decimal_padding_digits,
            double_columns_csv=options.double_columns_csv,
            equal_to_values=options.equal_to_values,
            error_after_step=options.error_after_step,
            error_before_step=options.error_before_step,
            execute=options.execute,
            force=options.force,
            hive_column_stats=options.hive_column_stats,
            impala_insert_hint=options.impala_insert_hint,
            integer_1_columns_csv=options.integer_1_columns_csv,
            integer_2_columns_csv=options.integer_2_columns_csv,
            integer_4_columns_csv=options.integer_4_columns_csv,
            integer_8_columns_csv=options.integer_8_columns_csv,
            integer_38_columns_csv=options.integer_38_columns_csv,
            ipa_predicate_type=options.ipa_predicate_type,
            less_than_value=options.less_than_value,
            max_offload_chunk_count=options.max_offload_chunk_count,
            max_offload_chunk_size=options.max_offload_chunk_size,
            not_null_columns_csv=options.not_null_columns_csv,
            offload_by_subpartition=options.offload_by_subpartition,
            offload_chunk_column=options.offload_chunk_column,
            offload_distribute_enabled=options.offload_distribute_enabled,
            offload_fs_container=options.offload_fs_container,
            offload_fs_prefix=options.offload_fs_prefix,
            offload_fs_scheme=options.offload_fs_scheme,
            offload_partition_columns=options.offload_partition_columns,
            offload_partition_functions=options.offload_partition_functions,
            offload_partition_granularity=options.offload_partition_granularity,
            offload_partition_lower_value=options.offload_partition_lower_value,
            offload_partition_upper_value=options.offload_partition_upper_value,
            offload_stats_method=options.offload_stats_method,
            offload_transport_consistent_read=options.offload_transport_consistent_read,
            offload_transport_fetch_size=options.offload_transport_fetch_size,
            offload_transport_jvm_overrides=options.offload_transport_jvm_overrides,
            offload_transport_method=options.offload_transport_method,
            offload_transport_queue_name=options.offload_transport_queue_name,
            offload_transport_parallelism=options.offload_transport_parallelism,
            offload_transport_small_table_threshold=options.offload_transport_small_table_threshold,
            offload_transport_snapshot=options.offload_transport_snapshot,
            offload_transport_spark_properties=options.offload_transport_spark_properties,
            offload_transport_validation_polling_interval=options.offload_transport_validation_polling_interval,
            offload_type=options.offload_type,
            offload_predicate=options.offload_predicate,
            offload_predicate_modify_hybrid_view=options.offload_predicate_modify_hybrid_view,
            older_than_date=options.older_than_date,
            older_than_days=options.older_than_days,
            owner_table=options.owner_table,
            partition_names_csv=options.partition_names_csv,
            preserve_load_table=options.preserve_load_table,
            purge_backend_table=options.purge_backend_table,
            reset_backend_table=options.reset_backend_table,
            reset_hybrid_view=options.reset_hybrid_view,
            reuse_backend_table=options.reuse_backend_table,
            skip=options.skip,
            sort_columns_csv=options.sort_columns_csv,
            storage_format=options.storage_format,
            storage_compression=options.storage_compression,
            suppress_stdout=options.suppress_stdout,
            synthetic_partition_digits=options.synthetic_partition_digits,
            target_owner_name=options.target_owner_name,
            timestamp_tz_columns_csv=options.timestamp_tz_columns_csv,
            unicode_string_columns_csv=options.unicode_string_columns_csv,
            variable_string_columns_csv=options.variable_string_columns_csv,
            ver_check=options.ver_check,
            verify_row_count=options.verify_row_count,
            verify_parallelism=options.verify_parallelism,
        )

    @staticmethod
    def from_dict(
        operation_dict,
        config,
        messages,
        repo_client=None,
        execution_id=None,
        max_hybrid_name_length=None,
    ):
        """No defaults for offload_fs_ options below as they are overrides for OrchestrationConfig attributes."""
        unexpected_keys = [k for k in operation_dict if k not in EXPECTED_OFFLOAD_ARGS]
        assert not unexpected_keys, "Unexpected OffloadOperation keys: %s" % unexpected_keys
        return OffloadOperation(
            config,
            messages,
            repo_client=repo_client,
            execution_id=execution_id,
            max_hybrid_name_length=max_hybrid_name_length,
            allow_decimal_scale_rounding=operation_dict.get(
                "allow_decimal_scale_rounding",
                orchestration_defaults.allow_decimal_scale_rounding_default(),
            ),
            allow_floating_point_conversions=operation_dict.get(
                "allow_floating_point_conversions",
                orchestration_defaults.allow_floating_point_conversions_default(),
            ),
            allow_nanosecond_timestamp_columns=operation_dict.get(
                "allow_nanosecond_timestamp_columns",
                orchestration_defaults.allow_nanosecond_timestamp_columns_default(),
            ),
            bucket_hash_col=operation_dict.get("bucket_hash_col"),
            column_transformation_list=operation_dict.get("column_transformation_list"),
            compress_load_table=operation_dict.get(
                "compress_load_table",
                orchestration_defaults.compress_load_table_default(),
            ),
            compute_load_table_stats=operation_dict.get(
                "compute_load_table_stats",
                orchestration_defaults.compute_load_table_stats_default(),
            ),
            create_backend_db=operation_dict.get(
                "create_backend_db", orchestration_defaults.create_backend_db_default()
            ),
            data_sample_parallelism=operation_dict.get(
                "data_sample_parallelism",
                orchestration_defaults.data_sample_parallelism_default(),
            ),
            data_sample_pct=operation_dict.get("data_sample_pct", orchestration_defaults.data_sample_pct_default()),
            date_columns_csv=operation_dict.get("date_columns_csv"),
            ddl_file=operation_dict.get("ddl_file"),
            decimal_columns_csv_list=operation_dict.get("decimal_columns_csv_list"),
            decimal_columns_type_list=operation_dict.get("decimal_columns_type_list"),
            decimal_padding_digits=operation_dict.get(
                "decimal_padding_digits",
                orchestration_defaults.decimal_padding_digits_default(),
            ),
            double_columns_csv=operation_dict.get("double_columns_csv"),
            equal_to_values=operation_dict.get("equal_to_values"),
            error_after_step=operation_dict.get("error_after_step"),
            error_before_step=operation_dict.get("error_before_step"),
            execute=operation_dict.get("execute", orchestration_defaults.execute_default()),
            force=operation_dict.get("force", orchestration_defaults.force_default()),
            hive_column_stats=operation_dict.get(
                "hive_column_stats", orchestration_defaults.hive_column_stats_default()
            ),
            impala_insert_hint=operation_dict.get("impala_insert_hint"),
            integer_1_columns_csv=operation_dict.get("integer_1_columns_csv"),
            integer_2_columns_csv=operation_dict.get("integer_2_columns_csv"),
            integer_4_columns_csv=operation_dict.get("integer_4_columns_csv"),
            integer_8_columns_csv=operation_dict.get("integer_8_columns_csv"),
            integer_38_columns_csv=operation_dict.get("integer_38_columns_csv"),
            ipa_predicate_type=operation_dict.get("ipa_predicate_type"),
            less_than_value=operation_dict.get("less_than_value"),
            max_offload_chunk_count=operation_dict.get(
                "max_offload_chunk_count",
                orchestration_defaults.max_offload_chunk_count_default(),
            ),
            max_offload_chunk_size=operation_dict.get(
                "max_offload_chunk_size",
                orchestration_defaults.max_offload_chunk_size_default(),
            ),
            not_null_columns_csv=operation_dict.get("not_null_columns_csv"),
            offload_by_subpartition=operation_dict.get("offload_by_subpartition"),
            offload_chunk_column=operation_dict.get("offload_chunk_column"),
            offload_distribute_enabled=operation_dict.get(
                "offload_distribute_enabled",
                orchestration_defaults.offload_distribute_enabled_default(),
            ),
            offload_fs_container=operation_dict.get("offload_fs_container"),
            offload_fs_prefix=operation_dict.get("offload_fs_prefix"),
            offload_fs_scheme=operation_dict.get("offload_fs_scheme"),
            offload_partition_columns=operation_dict.get("offload_partition_columns"),
            offload_partition_functions=operation_dict.get("offload_partition_functions"),
            offload_partition_granularity=operation_dict.get("offload_partition_granularity"),
            offload_partition_lower_value=operation_dict.get("offload_partition_lower_value"),
            offload_partition_upper_value=operation_dict.get("offload_partition_upper_value"),
            offload_stats_method=operation_dict.get(
                "offload_stats_method",
                orchestration_defaults.offload_stats_method_default(operation_name=OFFLOAD_OP_NAME),
            ),
            offload_transport_consistent_read=operation_dict.get(
                "offload_transport_consistent_read",
                bool_option_from_string(
                    "OFFLOAD_TRANSPORT_CONSISTENT_READ",
                    orchestration_defaults.offload_transport_consistent_read_default(),
                ),
            ),
            offload_transport_fetch_size=operation_dict.get(
                "offload_transport_fetch_size",
                orchestration_defaults.offload_transport_fetch_size_default(),
            ),
            offload_transport_jvm_overrides=operation_dict.get("offload_transport_jvm_overrides"),
            offload_transport_queue_name=operation_dict.get("offload_transport_queue_name"),
            offload_transport_parallelism=operation_dict.get(
                "offload_transport_parallelism",
                orchestration_defaults.offload_transport_parallelism_default(),
            ),
            offload_transport_method=operation_dict.get("offload_transport_method"),
            offload_transport_small_table_threshold=operation_dict.get(
                "offload_transport_small_table_threshold",
                orchestration_defaults.offload_transport_small_table_threshold_default(),
            ),
            offload_transport_snapshot=operation_dict.get("offload_transport_snapshot"),
            offload_transport_spark_properties=operation_dict.get(
                "offload_transport_spark_properties",
                orchestration_defaults.offload_transport_spark_properties_default(),
            ),
            offload_transport_validation_polling_interval=operation_dict.get(
                "offload_transport_validation_polling_interval",
                orchestration_defaults.offload_transport_validation_polling_interval_default(),
            ),
            offload_type=operation_dict.get("offload_type"),
            offload_predicate=operation_dict.get("offload_predicate"),
            offload_predicate_modify_hybrid_view=operation_dict.get(
                "offload_predicate_modify_hybrid_view",
                orchestration_defaults.offload_predicate_modify_hybrid_view_default(),
            ),
            older_than_date=operation_dict.get("older_than_date"),
            older_than_days=operation_dict.get("older_than_days"),
            owner_table=operation_dict.get("owner_table"),
            partition_names_csv=operation_dict.get("partition_names_csv"),
            preserve_load_table=operation_dict.get(
                "preserve_load_table",
                orchestration_defaults.preserve_load_table_default(),
            ),
            purge_backend_table=operation_dict.get(
                "purge_backend_table",
                orchestration_defaults.purge_backend_table_default(),
            ),
            reset_backend_table=operation_dict.get("reset_backend_table", False),
            reset_hybrid_view=operation_dict.get("reset_hybrid_view", False),
            reuse_backend_table=operation_dict.get("reuse_backend_table", False),
            skip=operation_dict.get("skip", orchestration_defaults.skip_default()),
            sort_columns_csv=operation_dict.get("sort_columns_csv", orchestration_defaults.sort_columns_default()),
            storage_format=operation_dict.get("storage_format", orchestration_defaults.storage_format_default()),
            storage_compression=operation_dict.get(
                "storage_compression",
                orchestration_defaults.storage_compression_default(),
            ),
            suppress_stdout=operation_dict.get("suppress_stdout", orchestration_defaults.suppress_stdout_default()),
            synthetic_partition_digits=operation_dict.get(
                "synthetic_partition_digits",
                orchestration_defaults.synthetic_partition_digits_default(),
            ),
            target_owner_name=operation_dict.get("target_owner_name"),
            timestamp_tz_columns_csv=operation_dict.get("timestamp_tz_columns_csv"),
            unicode_string_columns_csv=operation_dict.get("unicode_string_columns_csv"),
            variable_string_columns_csv=operation_dict.get("variable_string_columns_csv"),
            ver_check=operation_dict.get("ver_check", orchestration_defaults.ver_check_default()),
            verify_parallelism=operation_dict.get(
                "verify_parallelism",
                orchestration_defaults.verify_parallelism_default(),
            ),
            verify_row_count=operation_dict.get("verify_row_count", orchestration_defaults.verify_row_count_default()),
        )
