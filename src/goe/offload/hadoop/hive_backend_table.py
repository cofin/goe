# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""BackendHiveTable: Library for logic/interaction with a table that will
be either:
  1) The target of an offload
  2) The source of a present
"""

import logging

from goe.offload.hadoop.hadoop_backend_api import (
    hive_enable_dynamic_partitions_for_insert_sqls,
)
from goe.offload.hadoop.hadoop_backend_table import BackendHadoopTable
from goe.offload.offload_constants import (
    FILE_STORAGE_COMPRESSION_CODEC_ZLIB,
    FILE_STORAGE_FORMAT_ORC,
    OFFLOAD_STATS_METHOD_HISTORY,
    OFFLOAD_STATS_METHOD_NATIVE,
    OFFLOAD_STATS_METHOD_NONE,
)
from goe.offload.schema.column_spec import HADOOP_TYPE_BIGINT, HADOOP_TYPE_DECIMAL, get_column_names, valid_column_list

HASH_BUCKET_EXPRESSION = "CAST(COALESCE(PMOD(HASH(%(dividend)s),%(divisor)s),0) AS SMALLINT)"


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class BackendHiveTable(BackendHadoopTable):
    """Hive implementation
    Assumes backend system is HiveQL via HS2 in a Hadoop cluster
    """

    def __init__(
        self,
        db_name,
        table_name,
        backend_type,
        orchestration_options,
        messages,
        orchestration_operation=None,
        hybrid_metadata=None,
        dry_run=False,
        existing_backend_api=None,
        do_not_connect=False,
    ):
        """CONSTRUCTOR"""
        super().__init__(
            db_name,
            table_name,
            backend_type,
            orchestration_options,
            messages,
            orchestration_operation=orchestration_operation,
            hybrid_metadata=hybrid_metadata,
            dry_run=dry_run,
            existing_backend_api=existing_backend_api,
            do_not_connect=do_not_connect,
        )

        logger.info("BackendHiveTable setup: (%s, %s)" % (db_name, table_name))
        if dry_run:
            logger.info("* Dry run *")
        setattr(self, "_log_profile_after_final_table_load", False)
        setattr(self, "_log_profile_after_verification_queries", False)

    def compute_final_table_stats(self, incremental_stats, materialized_join=False):
        if self.table_stats_compute_supported():
            self._compute_hive_table_statistics(incremental_stats, materialized_join=materialized_join)

    def _create_new_backend_table(self, sort_column_names=None, with_terminator=False):
        """Generate & execute DDL to create a table in Hive.
        The table doesn't exist but self._columns should have been set and
        be ready to drive both columns and partition details.
        sort_column_names irrelevant to table DDL in Hive.
        """
        assert self._columns and valid_column_list(self._columns)

        partition_column_names = get_column_names(self.get_partition_columns())

        location = self._get_data_table_hdfs_dir()
        storage_format = getattr(self._orchestration_config, "storage_format", None)
        if storage_format == FILE_STORAGE_FORMAT_ORC:
            table_properties = {
                "orc.compress": (self._user_requested_storage_compression or FILE_STORAGE_COMPRESSION_CODEC_ZLIB)
            }
        else:
            table_properties = {}
        return self._db_api.create_table(
            self.db_name,
            self.table_name,
            self.get_columns(),
            partition_column_names,
            storage_format=storage_format,
            location=location,
            table_properties=table_properties,
            with_terminator=with_terminator,
        )

    def _final_insert_format_sql(
        self,
        select_expr_tuples,
        filter_clauses,
        sort_expr_list,
        for_materialized_join=False,
    ):
        """Format INSERT/SELECT for Hive."""
        assert select_expr_tuples
        assert isinstance(select_expr_tuples, list)
        if filter_clauses:
            assert isinstance(filter_clauses, list)

        dist_cols: list = get_column_names(self.get_partition_columns()) if self._offload_distribute_enabled else []

        partition_expr_tuples = [
            (self.get_final_table_cast(_), _) for _ in get_column_names(self.get_partition_columns())
        ]

        return self._db_api.gen_insert_select_sql_text(
            self.db_name,
            self.table_name,
            self._load_db_name,
            self._load_table_name,
            select_expr_tuples=select_expr_tuples,
            partition_expr_tuples=partition_expr_tuples,
            filter_clauses=filter_clauses,
            sort_expr_list=sort_expr_list,
            distribute_columns=dist_cols,
        )

    def _final_insert_query_options(self):
        """Returns a dict of Hive query options to be executed before the final insert."""
        query_options = hive_enable_dynamic_partitions_for_insert_sqls(
            max_dynamic_partitions=self._hive_max_dynamic_partitions,
            max_dynamic_partitions_pernode=self._hive_max_dynamic_partitions_pernode,
            as_dict=True,
        )
        stats_autogather = bool(not self._db_api.get_session_option("hive.stats.autogather") == "false")
        if self._hive_optimize_sort_dynamic_partition:
            query_options["hive.optimize.sort.dynamic.partition"] = "true"
        if self._offload_stats_method == OFFLOAD_STATS_METHOD_NONE and stats_autogather:
            query_options["hive.stats.autogather"] = "false"
        if (
            self._offload_stats_method in [OFFLOAD_STATS_METHOD_NATIVE, OFFLOAD_STATS_METHOD_HISTORY]
            and not stats_autogather
        ):
            query_options["hive.stats.autogather"] = "true"
        if self._db_api.get_session_option("hive.enforce.sorting") == "false":
            query_options["hive.enforce.sorting"] = "true"
        return query_options

    def _gen_synthetic_part_number_granularity_sql_expr(
        self,
        column_expr,
        backend_col,
        granularity,
        synthetic_partition_digits,
        with_padding=True,
    ):
        """On Hadoop CAST(DECIMAL as *INT) truncates decimal places, no rounding"""
        decimal_int = bool(backend_col.data_type == HADOOP_TYPE_DECIMAL and backend_col.data_scale == 0)
        cast_type = backend_col.format_data_type() if decimal_int else HADOOP_TYPE_BIGINT
        to_synth_expr = "CAST(FLOOR(CAST(%s AS %s) / %s) * %s AS STRING)" % (
            column_expr,
            cast_type,
            granularity,
            granularity,
        )
        if with_padding:
            return "LPAD(CAST(%s AS STRING), %s, '0')" % (
                to_synth_expr,
                synthetic_partition_digits,
            )
        return to_synth_expr

    def _tzoffset_to_timestamp_sql_expression(self, col_name):
        """Hive tzoffset SQL expression"""
        raise NotImplementedError("_tzoffset_to_timestamp_sql_expression() is not implemented for Hive class")

    def _validate_staged_data_query_options(self):
        """Hive override facilitating Load Table stats."""
        if not self._user_requested_compute_load_table_stats:
            return {"hive.compute.query.using.stats": "false"}
        return {}
