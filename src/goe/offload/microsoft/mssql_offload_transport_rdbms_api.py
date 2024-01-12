#! /usr/bin/env python3
""" OffloadTransportMSSQLApi: Library for logic/interaction with source MSSQL system during offload transport.
    LICENSE_TEXT
"""

from contextlib import contextmanager

from goe.offload.offload_constants import OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED
from goe.offload.offload_transport_rdbms_api import OffloadTransportRdbmsApiInterface
from goe.util.misc_functions import id_generator


###########################################################################
# CONSTANTS
###########################################################################

###########################################################################
# GLOBAL FUNCTIONS
###########################################################################

###########################################################################
# OffloadTransportMSSQLApi
###########################################################################

class OffloadTransportMSSQLApi(OffloadTransportRdbmsApiInterface):
    """ MSSQL specific methods
    """

    def __init__(self, rdbms_owner, rdbms_table_name, offload_options, messages,
                 incremental_update_extractor=None, dry_run=False):
        super().__init__(rdbms_owner, rdbms_table_name, offload_options, messages,
                         incremental_update_extractor=incremental_update_extractor, dry_run=dry_run)
        self.debug('OffloadTransportMSSQLApi setup: (%s, %s)' % (rdbms_owner, rdbms_table_name))

    ###########################################################################
    # PRIVATE METHODS
    ###########################################################################

    ###########################################################################
    # PUBLIC METHODS
    ###########################################################################

    def generate_transport_action(self):
        id_str = id_generator()
        return ('%s_%s' % (id_str, self._rdbms_table_name.lower()))

    def get_rdbms_query_cast(self, column_expression, rdbms_column, staging_column, max_ts_scale,
                             convert_expressions_on_rdbms_side=False, for_spark=False, nan_values_as_null=False):
        """ Returns an expression suitable for reading a specific column from the RDBMS table  """
        self.debug('get_rdbms_query_cast()')
        raise NotImplementedError('MSSQL get_rdbms_query_cast() pending implementation')

    def get_rdbms_session_setup_commands(self, module, action, custom_session_parameters, include_fixed_sqoop=True,
                                         for_plsql=False, include_semi_colons=False, escape_semi_colons=False,
                                         max_ts_scale=None) -> list:
        raise NotImplementedError('MSSQL get_rdbms_session_setup_commands() not implemented.')

    def get_rdbms_session_setup_hint(self, custom_session_parameters, max_ts_scale):
        """ No session setup hints required on MSSQL """
        return ''

    def get_rdbms_scn(self):
        raise NotImplementedError('MSSQL get_rdbms_scn() not implemented.')

    def get_transport_split_type(self, partition_chunk, rdbms_table, parallelism, rdbms_partition_type,
                                 rdbms_columns, offload_by_subpartition, predicate_offload_clause) -> tuple:
        raise NotImplementedError('MSSQL get_transport_split_type() not implemented.')

    def get_transport_row_source_query(self, partition_by_prm, rdbms_table, consistent_read, parallelism,
                                       offload_by_subpartition, mod_column, predicate_offload_clause,
                                       partition_chunk=None, pad=None) -> str:
        raise NotImplementedError('MSSQL get_transport_row_source_query() not implemented.')

    def get_transport_row_source_query_hint_block(self) -> str:
        raise NotImplementedError('MSSQL get_transport_row_source_query_hint_block() not implemented.')

    def jdbc_driver_name(self) -> str:
        return None

    def jdbc_url(self):
        return '"jdbc:sqlserver://' + self._offload_transport_dsn + '"'

    def log_sql_stats(self, module, action, payload,
                      validation_polling_interval=OFFLOAD_TRANSPORT_VALIDATION_POLLER_DISABLED):
        raise NotImplementedError('MSSQL log_sql_stats() not implemented.')

    def get_rdbms_canary_query(self):
        return 'SELECT 1'

    @contextmanager
    def query_import_extraction(self, staging_columns, source_query, source_binds,
                                fetch_size, compress, rdbms_session_setup_commands):
        raise NotImplementedError('MSSQL query_import_extraction() not implemented')

    def sqoop_rdbms_specific_jvm_overrides(self, rdbms_session_setup_commands) -> list:
        return []

    def sqoop_rdbms_specific_jvm_table_options(self, partition_chunk, partition_type=None,
                                               is_iot=False, consistent_read=False) -> list:
        return []

    def sqoop_rdbms_specific_options(self) -> list:
        return []

    def sqoop_rdbms_specific_table_options(self, rdbms_owner, table_name) -> list:
        return ['--', '--schema', rdbms_owner,
                '--table', self._ssh_cli_safe_value(table_name)]