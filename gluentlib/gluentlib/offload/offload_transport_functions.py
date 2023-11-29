#! /usr/bin/env python3
""" OffloadTransportFunctions: Library of functions used in gluent.py and data transport modules
    LICENSE_TEXT
"""

import decimal
import logging
from getpass import getuser
import math
import os
from re import sub
from socket import gethostname, getfqdn
import subprocess
from subprocess import PIPE, STDOUT
import sys
from typing import Optional, TYPE_CHECKING

import cx_Oracle as cxo

from gluentlib.offload.frontend_api import FRONTEND_TRACE_MODULE
from gluentlib.offload.offload_constants import FILE_STORAGE_FORMAT_AVRO, HADOOP_BASED_BACKEND_DISTRIBUTIONS
from gluentlib.offload.offload_messages import VERBOSE, VVERBOSE
from gluentlib.orchestration import orchestration_constants
from gluentlib.util.misc_functions import get_os_username, obscure_list_items, standard_file_name,\
    MAX_SUPPORTED_PRECISION

if TYPE_CHECKING:
    from gluentlib.offload.backend_table import BackendTableInterface
    from gluentlib.offload.offload_messages import OffloadMessages
    from gluentlib.offload.offload_source_data import OffloadSourcePartitions
    from gluentlib.offload.offload_source_table import OffloadSourceTableInterface
    from gluentlib.offload.offload_transport import OffloadTransport
    from gluentlib.offload.predicate_offload import GenericPredicate
    from gluentlib.orchestration.execution_id import ExecutionId
    from gluentlib.persistence.orchestration_repo_client import OrchestrationRepoClientInterface


class OffloadTransportException(Exception):
    pass


###############################################################################
# CONSTANTS
###############################################################################

logger = logging.getLogger(__name__)
# Disabling logging by default
logger.addHandler(logging.NullHandler())


###########################################################################
# GLOBAL FUNCTIONS
###########################################################################

def offload_transport_file_name(name_prefix, extension=''):
    return standard_file_name(name_prefix, extension=extension)


def load_db_hdfs_path(load_db_name, offload_options):
    assert load_db_name
    assert offload_options.hdfs_load
    return os.path.join(offload_options.hdfs_load, load_db_name + offload_options.hdfs_db_path_suffix)


def avsc_hdfs_path(load_db_name, schema_filename, offload_options):
    if offload_options.backend_distribution not in HADOOP_BASED_BACKEND_DISTRIBUTIONS:
        # No HDFS in play
        return None
    return os.path.join(load_db_hdfs_path(load_db_name, offload_options), schema_filename)


def schema_paths(target_owner, table_name, load_db_name, offload_options, local_extension_override=None):
    owner_table = '%s.%s' % (target_owner, table_name)
    if local_extension_override:
        schema_filename = offload_transport_file_name(owner_table, extension=local_extension_override)
    elif offload_options.offload_staging_format == FILE_STORAGE_FORMAT_AVRO:
        schema_filename = offload_transport_file_name(owner_table, extension='.avsc')
    else:
        schema_filename = offload_transport_file_name(owner_table)
    local_schema_path = os.path.join(offload_options.log_path, schema_filename)
    return local_schema_path, avsc_hdfs_path(load_db_name, schema_filename, offload_options)


def ssh_cmd_prefix(ssh_user, host):
    assert ssh_user
    assert host
    if ssh_user == getuser() and host == 'localhost':
        return []
    return ['ssh', '-tq', ssh_user + '@' + host]


def scp_to_cmd(user, host, from_path, to_path):
    if user == getuser() and host == 'localhost':
        if to_path[0] != '/':
            to_path = os.path.join(os.environ.get('HOME'), to_path)
        return ['scp', from_path, to_path]
    return ['scp', from_path, '%s@%s:%s' % (user, host, to_path)]


def get_rdbms_connection_for_oracle(ora_user, ora_pass, ora_dsn, use_oracle_wallet=False, ora_trace_id='GLUENT'):
    if use_oracle_wallet:
        ora_conn = cxo.connect(dsn=ora_dsn)
    else:
        ora_conn = cxo.connect(ora_user, ora_pass, ora_dsn)
    session_cursor = ora_conn.cursor()
    try:
        session_cursor.execute('ALTER SESSION SET TRACEFILE_IDENTIFIER="%s"' % ora_trace_id)
    finally:
        session_cursor.close()
    ora_conn.module = FRONTEND_TRACE_MODULE
    return ora_conn


def credential_provider_path_jvm_override(credential_provider_path):
    """ return a JVM override clause to point to credential provider file
    """
    if not credential_provider_path:
        return ''
    return '-Dhadoop.security.credential.provider.path=%s' % credential_provider_path


def write_progress_to_stdout():
    try:
        sys.stdout.write('.')
        sys.stdout.flush()
    except OSError:
        # Writing dots to screen is non-essential, if we lost stdout then press on anyway.
        pass


def finish_progress_on_stdout():
    try:
        sys.stdout.write('\n')
        sys.stdout.flush()
    except OSError:
        # Writing dots to screen is non-essential, if we lost stdout then press on anyway.
        pass


def run_os_cmd(cmd, messages, offload_options, dry_run=False, optional=False, force=False,
               silent=False, no_log_items=[]):
    """ Run an os command and:
          - Throw an exception if the return code is non-zero (and optional=False)
          - Put a dot on stdout for each line logged to give the impression of progress
          - Logs all command output at VVERBOSE level
        silent: No stdout unless vverbose is requested.
        The returned output is str, working on the assumption that output to screen will be unicode.
    """
    messages.log('_run_os_cmd()', detail=VVERBOSE)
    assert isinstance(cmd, list)
    ok_types = set([str, str])
    token_types = set([type(_) for _ in cmd])
    assert ok_types.issuperset(token_types), 'All command tokens must be strings, found: ' + str(list(token_types.difference(ok_types)))

    messages.log('OS cmd: ' + ' '.join(obscure_list_items(cmd, no_log_items)), detail=VVERBOSE if silent else VERBOSE)

    if dry_run:
        return 0, None

    output = ''
    proc = subprocess.Popen(cmd, stdout=PIPE, stderr=STDOUT)
    for line in proc.stdout:
        line = line.decode()
        output += line
        messages.log(line.strip(), detail=VVERBOSE)
        if not offload_options.vverbose and not silent:
            write_progress_to_stdout()
    if not offload_options.vverbose and not offload_options.quiet and output and not silent:
        finish_progress_on_stdout()

    cmd_returncode = proc.wait()
    messages.log('returncode: %s' % cmd_returncode, detail=VVERBOSE)
    if cmd_returncode and not offload_options.vverbose and (not offload_options.quiet or not optional) and not silent:
        try:
            sys.stdout.write(output)
        except OSError:
            # Writing to screen is non-essential, if we lost stdout then we still have the log file.
            pass

    if not optional and cmd_returncode:
        raise OffloadTransportException('Required shell cmd failed with return code %s' % cmd_returncode)

    return cmd_returncode, output


def hs2_connection_log_message(host, port, offload_options, service_name):
    if offload_options.ldap_user and (offload_options.ldap_password or offload_options.ldap_password_file):
        return 'Connecting to %s (%s:%s) with LDAP as %s' % (service_name, host, port, offload_options.ldap_user)
    elif offload_options.kerberos_service:
        return 'Connecting to %s (%s:%s) - Kerberos service %s' % (service_name, host, port,
                                                                   offload_options.kerberos_service)
    else:
        return 'Connecting to %s (%s:%s) unsecured using: %s authentication' % (service_name, host, port, offload_options.hiveserver2_auth_mechanism)


def running_as_same_user_and_host(ssh_user, target_host):
    return bool(get_os_username() == ssh_user
                and (target_host == 'localhost' or target_host in (gethostname(), getfqdn())))


def offload_chunk_backend_bytes(pre_load_backend_bytes, post_load_backend_bytes, messages):
    if pre_load_backend_bytes is not None and post_load_backend_bytes is not None:
        return post_load_backend_bytes - pre_load_backend_bytes
    else:
        messages.log(f'Unable to calculate backend bytes: {post_load_backend_bytes} - {pre_load_backend_bytes}',
                     detail=VVERBOSE)
        return None


def transport_and_load_offload_chunk(data_transport_client: "OffloadTransport",
                                     offload_source_table: "OffloadSourceTableInterface",
                                     offload_target_table: "BackendTableInterface",
                                     execution_id: "ExecutionId",
                                     repo_client: "OrchestrationRepoClientInterface",
                                     messages: "OffloadMessages",
                                     partition_chunk: Optional["OffloadSourcePartitions"] = None,
                                     chunk_count: int = 0, sync: bool = True,
                                     offload_predicate: Optional["GenericPredicate"] = None,
                                     dry_run: bool = False):
    """ Offload transport steps for a regular offload chunk, used in gluent.py.
    """

    def get_frontend_bytes():
        try:
            if offload_predicate:
                messages.log('Unable to calculate frontend bytes for predicate based Offload', detail=VVERBOSE)
                return None
            elif partition_chunk:
                return partition_chunk.size_in_bytes()
            else:
                return offload_source_table.size_in_bytes
        except Exception as exc:
            # This is for instrumentation and non-essential
            messages.warning('Unable to calculate transport frontend bytes due to exception: {}'.format(str(exc)))

    chunk_id = repo_client.start_offload_chunk(
        execution_id, offload_source_table.owner, offload_source_table.table_name,
        offload_target_table.db_name, offload_target_table.table_name, chunk_number=chunk_count+1,
        offload_partitions=partition_chunk.get_partitions() if partition_chunk else None,
        offload_partition_level=offload_source_table.offload_partition_level
    )

    try:
        if chunk_count > 0:
            offload_target_table.empty_staging_area_step(data_transport_client.get_staging_file())

        rows_staged = data_transport_client.transport(partition_chunk=partition_chunk)
        transport_bytes = data_transport_client.get_transport_bytes()
        staging_columns = data_transport_client.get_staging_file().get_staging_columns()

        offload_target_table.validate_staged_data_step(offload_source_table.partition_columns,
                                                       offload_source_table.columns,
                                                       rows_staged, staging_columns)

        offload_target_table.validate_type_conversions_step(staging_columns)

        pre_load_backend_bytes = offload_target_table.get_table_size() if not dry_run else None
        offload_target_table.load_final_table_step(sync=sync)
        post_load_backend_bytes = offload_target_table.get_table_size(no_cache=True) if not dry_run else None
        backend_byte_delta = offload_chunk_backend_bytes(pre_load_backend_bytes, post_load_backend_bytes, messages)
        frontend_bytes = get_frontend_bytes()

        repo_client.end_offload_chunk(chunk_id, orchestration_constants.COMMAND_SUCCESS,
                                      row_count=rows_staged, frontend_bytes=frontend_bytes,
                                      transport_bytes=transport_bytes, backend_bytes=backend_byte_delta)

        return rows_staged
    except Exception as exc:
        repo_client.end_offload_chunk(chunk_id, orchestration_constants.COMMAND_ERROR)
        raise


def split_ranges_for_id_range(id_min, id_max, parallelism):
    """ Take a range of numbers and split them into sub-ranges based on parallelism where pairs can be used in
        comparisons like:
            id >= i and id < j
        Arithmetic and returned values are Decimal in order to support numeric precision greater than float can support.
        For example:
            id_min=1, id_max=10, parallelism=2
        should result in:
            [(1, 6), (6, 11)
    """
    decimal.getcontext().prec = MAX_SUPPORTED_PRECISION
    if not isinstance(id_min, decimal.Decimal):
        id_min = decimal.Decimal(str(id_min))
    if not isinstance(id_max, decimal.Decimal):
        id_max = decimal.Decimal(str(id_max))
    range_delta = (id_max - id_min + 1) / parallelism
    id_ranges = [(id_min + (range_delta * _), id_min + (range_delta * _) + range_delta)
                 for _ in range(parallelism)]
    return id_ranges


def split_lists_for_id_list(id_list: list, parallelism: int, round_robin=True, as_csvs=False) -> list:
    """ Take a list of values, split them into sub-ranges based on parallelism and then, optionally, convert to CSVs.
        The splitting into sub-ranges can be contiguous or round-robin.
        Example input:
            [8, 4, 1, 3, 6, 9]
        parallelism=2, round_robin=True, as_csvs=False should result in:
            [(8, 1, 6), (4, 3, 9)]
        parallelism=2, round_robin=False, as_csvs=False should result in:
            [(8, 4, 1), (3, 6, 9)]
        parallelism=2, round_robin=True, as_csvs=True should result in:
            ['8,1,6', '4,3,9']
        Note that empty lists when converted to CSVs are None and not ''. This is because None is False.
    """
    def to_csv(l):
        if not l:
            return None
        else:
            return ','.join(_ if isinstance(_, str) else str(_)for _ in l)

    if not id_list:
        return []
    if round_robin:
        sublists = [id_list[_::parallelism] for _ in range(parallelism)]
    else:
        chunk_size = math.ceil(len(id_list) / parallelism)
        sublists = [id_list[_ * chunk_size:(_ + 1) * chunk_size] for _ in range(parallelism)]

    if as_csvs:
        return [to_csv(_) for _ in sublists]
    else:
        return sublists