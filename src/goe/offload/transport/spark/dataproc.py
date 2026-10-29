# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""GCP Dataproc Cluster and Serverless Batches Spark transport implementations."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any, Self

from goe.config import orchestration_defaults
from goe.config.gcp_credentials import resolve_gcloud_impersonation_principal
from goe.offload.frontend_api import FRONTEND_TRACE_MODULE
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.registry import create_transport_rdbms_api
from goe.offload.transport.constants import (
    MISSING_ROWS_SPARK_WARNING,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE,
    SPARK_OPTIONS_FILE_PREFIX,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
)
from goe.offload.transport.protocol import OffloadTransportException
from goe.offload.transport.spark.polling import OffloadTransportSpark
from goe.orchestration import command_steps
from goe.serializers import decode_json
from goe.util.string_utils import write_temp_file

if TYPE_CHECKING:
    from goe.config.orchestration_config import OrchestrationConfig
    from goe.offload.backend_table import BackendTableInterface
    from goe.offload.offload_messages import OffloadMessages
    from goe.offload.offload_source_table import OffloadSourceTableInterface

GCLOUD_PROPERTY_SEPARATOR = ",GSEP,"
GCLOUD_BATCHES_STATE_CANCELLED = "CANCELLED"
GCLOUD_BATCHES_STATE_FAILED = "FAILED"
GCLOUD_BATCHES_STATE_MESSAGE_TASK_NOT_ACQUIRED = "Task was not acquired"
DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED = (
    "GOOGLE_DATAPROC_SERVICE_ACCOUNT is the Managed Spark serverless runtime service account and is not used to "
    "submit jobs to a permanent cluster. Set GOOGLE_IMPERSONATE_SERVICE_ACCOUNT or "
    "GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT for gcloud caller impersonation"
)


class OffloadTransportSparkBatchesGcloud(OffloadTransportSpark):
    """Submit PySpark to Managed Spark Serverless Batches via gcloud to transport data."""

    def __init__(
        self,
        offload_source_table: OffloadSourceTableInterface,
        offload_target_table: BackendTableInterface,
        offload_operation: Any,
        offload_options: OrchestrationConfig,
        messages: OffloadMessages,
        dfs_client: Any,
    ) -> None:
        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        self._load_table_compression_pyspark_settings()
        self._offload_fs_container: str | None = offload_options.offload_fs_container
        self._dataproc_cluster = offload_options.google_dataproc_cluster
        self._dataproc_project = offload_options.google_dataproc_project
        self._dataproc_region = offload_options.google_dataproc_region
        self._dataproc_service_account = offload_options.google_dataproc_service_account
        self._dataproc_batches_subnet = offload_options.google_dataproc_batches_subnet
        self._dataproc_batches_ttl = offload_options.google_dataproc_batches_ttl
        self._dataproc_batches_version = offload_options.google_dataproc_batches_version
        self._is_canary = False

    @classmethod
    def for_canary(cls, offload_options: Any, messages: Any) -> Self:
        """Construct a lightweight instance configured for RDBMS connectivity canary checks."""
        instance = cls.__new__(cls)
        instance._offload_options = offload_options
        instance._messages = messages
        instance._dry_run = False
        instance._is_canary = True
        instance._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD
        instance._create_basic_connectivity_attributes(offload_options)
        instance._offload_transport_consistent_read = orchestration_defaults.bool_option_from_string(
            "OFFLOAD_TRANSPORT_CONSISTENT_READ",
            orchestration_defaults.offload_transport_consistent_read_default(),
        )
        instance._offload_transport_fetch_size = orchestration_defaults.offload_transport_fetch_size_default()
        instance._offload_transport_jvm_overrides = orchestration_defaults.offload_transport_spark_overrides_default()
        instance._offload_transport_queue_name = orchestration_defaults.offload_transport_spark_queue_name_default()
        instance._offload_transport_parallelism = 1
        instance._validation_polling_interval = (
            orchestration_defaults.offload_transport_validation_polling_interval_default()
        )
        instance._spark_config_properties = instance._prepare_spark_config_properties(
            orchestration_defaults.offload_transport_spark_properties_default()
        )
        instance._rdbms_api = create_transport_rdbms_api(
            "dummy_owner",
            "dummy_table",
            instance._offload_options,
            instance._messages,
            dry_run=instance._dry_run,
        )
        instance._rdbms_module = FRONTEND_TRACE_MODULE
        instance._rdbms_action = instance._rdbms_api.generate_transport_action()
        instance._offload_fs_container = getattr(offload_options, "offload_fs_container", None)
        instance._dataproc_cluster = getattr(offload_options, "google_dataproc_cluster", None)
        instance._dataproc_project = getattr(offload_options, "google_dataproc_project", None)
        instance._dataproc_region = getattr(offload_options, "google_dataproc_region", None)
        instance._dataproc_service_account = getattr(offload_options, "google_dataproc_service_account", None)
        instance._dataproc_batches_subnet = getattr(offload_options, "google_dataproc_batches_subnet", None)
        instance._dataproc_batches_ttl = getattr(offload_options, "google_dataproc_batches_ttl", None)
        instance._dataproc_batches_version = getattr(offload_options, "google_dataproc_batches_version", None)
        instance._spark_files_csv = getattr(offload_options, "offload_transport_spark_files", None)
        instance._spark_jars_csv = getattr(offload_options, "offload_transport_spark_jars", None)
        instance._target_table = None
        instance._rdbms_table = None
        instance._staging_format = None
        return instance

    def transport(self, partition_chunk: Any = None) -> int | None:
        """Run Spark transport via gcloud dataproc batches."""
        self._reset_transport_context()
        return self._messages.offload_step(
            command_steps.STEP_STAGING_TRANSPORT,
            lambda: self._execute_transport_step(partition_chunk),
            execute=(not self._dry_run),
        )

    def ping_source_rdbms(self) -> bool:
        """Verify RDBMS connectivity from Managed Spark."""
        return self._verify_rdbms_connectivity()

    def _execute_transport_step(self, partition_chunk: Any = None) -> int | None:
        row_count = self._spark_gcloud_import(partition_chunk)
        staged_bytes = self._check_and_log_transported_files(row_count)
        self._transport_context[TRANSPORT_CXT_BYTES] = staged_bytes
        self._transport_context[TRANSPORT_CXT_ROWS] = row_count
        self._target_table.post_transport_tasks(self._staging_file)
        return row_count

    def _spark_cli_safe_value(self, cmd_option_string: str) -> str:
        return self._ssh_cli_safe_value(cmd_option_string)

    def _cli_safe_password_value(self, key: str, value: Any) -> Any:
        if key == "spark.jdbc.password":
            return self._spark_cli_safe_value(value)
        return value

    def _column_type_read_remappings(self) -> list[str] | str:
        return self._offload_transport_type_remappings(return_as_list=False, remap_sep="=")

    def _remote_copy_spark_control_file(
        self, options_file_local_path: str, suffix: str = ""
    ) -> tuple[list[list[str]], str]:
        return self._remote_copy_transport_control_file(
            options_file_local_path,
            self._offload_transport_cmd_host,
            prefix=SPARK_OPTIONS_FILE_PREFIX,
            suffix=suffix,
        )

    def _gcloud_impersonation_options(self) -> list[str]:
        principal = resolve_gcloud_impersonation_principal(self._offload_options)
        return [f"--impersonate-service-account={principal}"] if principal else []

    def _gcloud_dataproc_describe_command(self, batch_name: str) -> list[str]:
        gcloud_cmd = [
            OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE,
            "dataproc",
            "batches",
            "describe",
            batch_name,
            "--format=json",
        ]
        if self._dataproc_project:
            gcloud_cmd.append(f"--project={self._dataproc_project}")
        if self._dataproc_region:
            gcloud_cmd.append(f"--region={self._dataproc_region}")
        gcloud_cmd.extend(self._gcloud_impersonation_options())
        return gcloud_cmd

    def _gcloud_dataproc_submit_command(self, id: str | None = None) -> list[str]:
        gcloud_cmd = [
            OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE,
            "dataproc",
            "batches",
            "submit",
            "pyspark",
        ]
        if self._dataproc_project:
            gcloud_cmd.append(f"--project={self._dataproc_project}")
        if self._dataproc_region:
            gcloud_cmd.append(f"--region={self._dataproc_region}")
        gcloud_cmd.append(f"--batch={id}")
        if self._dataproc_service_account:
            gcloud_cmd.append(f"--service-account={self._dataproc_service_account}")
        gcloud_cmd.extend(self._gcloud_impersonation_options())
        if self._dataproc_batches_version:
            gcloud_cmd.append(f"--version={self._dataproc_batches_version}")
        if self._dataproc_batches_subnet:
            gcloud_cmd.append(f"--subnet={self._dataproc_batches_subnet}")
        if self._dataproc_batches_ttl:
            gcloud_cmd.append(f"--ttl={self._dataproc_batches_ttl}")
        gcloud_cmd.append(f"--deps-bucket={self._offload_fs_container}")
        return gcloud_cmd

    def _get_batch_name(self) -> str:
        if getattr(self, "_is_canary", False):
            return self._get_transport_app_name(sep="-", ts=True, name_override="canary").lower()[:64]
        batch_name_root = re.sub(r"[^a-zA-Z0-9\-]+", "", self._target_db_name + "-" + self._load_table_name)
        return self._get_transport_app_name(sep="-", ts=True, name_override=batch_name_root).lower()[:64]

    def _get_spark_gcloud_command(self, pyspark_body: str, id: str | None = None) -> tuple[list[Any], list[Any], Any]:
        self.log("PySpark: " + pyspark_body, detail=VVERBOSE)
        options_file_local_path = write_temp_file(pyspark_body, prefix=SPARK_OPTIONS_FILE_PREFIX, suffix="py")
        py_rm_commands, options_file_remote_path = self._remote_copy_spark_control_file(
            options_file_local_path, suffix="py"
        )
        if self._spark_listener_included_in_config():
            spark_listener_jar_local_path = self._local_goe_listener_jar()
            spark_listener_jar_remote_path = self._remote_copy_transport_file(
                spark_listener_jar_local_path, self._offload_transport_cmd_host
            )
        else:
            spark_listener_jar_remote_path = None
        self.log(f"Written PySpark file: {options_file_remote_path}", detail=VVERBOSE)

        remote_spark_files_csv = self._remote_copy_transport_file_csv(
            self._spark_files_csv, self._offload_transport_cmd_host
        )
        remote_spark_jars_csv = self._remote_copy_transport_file_csv(
            self._spark_jars_csv, self._offload_transport_cmd_host
        )

        if spark_listener_jar_remote_path:
            if remote_spark_jars_csv:
                remote_spark_jars_csv = f"{spark_listener_jar_remote_path},{remote_spark_jars_csv}"
            else:
                remote_spark_jars_csv = spark_listener_jar_remote_path

        gcloud_cmd = self._gcloud_dataproc_submit_command(id=id)

        spark_config_props: list[str] = []
        no_log_password: list[dict[str, str]] = []
        for k, v in self._spark_config_properties.items():
            spark_config_props.append(f"{k}={self._cli_safe_password_value(k, v)}")
        if "spark.jdbc.password" in self._spark_config_properties and not self._offload_transport_password_alias:
            password_config_to_obscure = f"spark.jdbc.password={self._cli_safe_password_value('spark.jdbc.password', self._spark_config_properties['spark.jdbc.password'])}"
            no_log_password = [{"item": password_config_to_obscure, "prior": "--conf"}]

        spark_config_props.extend(self._tune_dataproc_for_parallelism())

        if self._offload_transport_jvm_overrides:
            spark_config_props.extend(
                [
                    f"spark.driver.extraJavaOptions={self._offload_transport_jvm_overrides}",
                    f"spark.executor.extraJavaOptions={self._offload_transport_jvm_overrides}",
                ]
            )

        if spark_config_props:
            properties_clause = [
                f"--properties=^{GCLOUD_PROPERTY_SEPARATOR}^" + GCLOUD_PROPERTY_SEPARATOR.join(spark_config_props)
            ]
        else:
            properties_clause = []

        jars_opt = [f"--jars={remote_spark_jars_csv}"] if remote_spark_jars_csv else []
        files_opt = [f"--files={remote_spark_files_csv}"] if remote_spark_files_csv else []

        cmd = gcloud_cmd + [options_file_remote_path] + jars_opt + files_opt + properties_clause
        return cmd, no_log_password, py_rm_commands

    def _spark_gcloud_import(self, partition_chunk: Any = None) -> int | None:
        self._refresh_rdbms_action()

        if self._nothing_to_do(partition_chunk):
            return 0

        rows_imported = None
        pyspark_body = self._get_pyspark_body(partition_chunk)
        batch_name = self._get_batch_name()
        (
            spark_gcloud_cmd,
            no_log_password,
            py_rm_commands,
        ) = self._get_spark_gcloud_command(pyspark_body, id=batch_name)

        self._start_validation_polling_thread()
        _, cmd_out = self._run_os_cmd(self._ssh_cmd_prefix() + spark_gcloud_cmd, no_log_items=no_log_password)
        self._stop_validation_polling_thread()

        if not self._dry_run:
            self._verify_batch(batch_name)
            rows_imported = self._get_rows_imported_from_spark_log(cmd_out)
            rows_imported_from_sql_stats = self._rdbms_api.log_sql_stats(
                self._rdbms_module,
                self._rdbms_action,
                self._drain_validation_polling_thread_queue(),
                validation_polling_interval=self._validation_polling_interval,
            )
            if rows_imported is None:
                if rows_imported_from_sql_stats is None:
                    self.warning(MISSING_ROWS_SPARK_WARNING)
                else:
                    self.warning(f"{MISSING_ROWS_SPARK_WARNING}, falling back on RDBMS SQL statistics")
                    rows_imported = rows_imported_from_sql_stats

        for rm_cmd in py_rm_commands:
            self._run_os_cmd(rm_cmd)

        self._check_rows_imported(rows_imported)
        return rows_imported

    def _executor_cores(self) -> int | None:
        if self._offload_transport_parallelism > 8:
            return 16
        if self._offload_transport_parallelism > 4:
            return 8
        return None

    def _executor_instances(self) -> int | None:
        if self._offload_transport_parallelism <= 32:
            return None
        return math.ceil(self._offload_transport_parallelism / 16)

    def _tune_dataproc_for_parallelism(self) -> list[str]:
        if (
            "spark.executor.cores" not in self._spark_config_properties
            and "spark.executor.instances" not in self._spark_config_properties
            and self._offload_transport_parallelism
        ):
            props: list[str] = []
            cores = self._executor_cores()
            instances = self._executor_instances()
            if cores:
                props.append(f"spark.executor.cores={cores}")
            if instances:
                props.append(f"spark.executor.instances={instances}")
            return props
        return []

    def _verify_batch(self, batch_name: str) -> None:
        describe_cmd = self._gcloud_dataproc_describe_command(batch_name)
        rc, describe_cmd_output = self._run_os_cmd(self._ssh_cmd_prefix() + describe_cmd, optional=True)
        if rc == 0 and describe_cmd_output:
            self._verify_batch_describe_response(describe_cmd_output)

    def _verify_batch_describe_response(self, describe_output: str) -> bool:
        try:
            response_dict = decode_json(describe_output)
        except Exception as exc:
            self.log(f"Exception describing Managed Spark batch: {exc!s}", detail=VERBOSE)
            return False
        state = response_dict.get("state")
        state_message = response_dict.get("stateMessage", "")
        if state and state in [
            GCLOUD_BATCHES_STATE_CANCELLED,
            GCLOUD_BATCHES_STATE_FAILED,
        ]:
            if state == GCLOUD_BATCHES_STATE_CANCELLED:
                raise OffloadTransportException(
                    "Dataproc batch is incomplete due to TTL, increase GOOGLE_DATAPROC_BATCHES_TTL"
                )
            if GCLOUD_BATCHES_STATE_MESSAGE_TASK_NOT_ACQUIRED in state_message:
                raise OffloadTransportException(
                    f"Managed Spark batch failed with stateMessage containing "
                    f"'{GCLOUD_BATCHES_STATE_MESSAGE_TASK_NOT_ACQUIRED}'. "
                    "The likely cause is missing VPC network/firewall prerequisites for Managed Spark serverless"
                )
            raise OffloadTransportException(f"Managed Spark batch failed with state: {state}")
        return True

    def _verify_rdbms_connectivity(self) -> bool:
        rdbms_source_query = f"({self._rdbms_api.get_rdbms_canary_query()}) v"
        pyspark_body = self._get_pyspark_body(canary_query=rdbms_source_query)
        self.log("PySpark: " + pyspark_body, detail=VVERBOSE)
        batch_name = self._get_batch_name()
        (
            spark_gcloud_cmd,
            no_log_password,
            py_rm_commands,
        ) = self._get_spark_gcloud_command(pyspark_body, id=batch_name)
        self._run_os_cmd(self._ssh_cmd_prefix() + spark_gcloud_cmd, no_log_items=no_log_password)
        for rm_cmd in py_rm_commands:
            self._run_os_cmd(rm_cmd)
        self._verify_batch(batch_name)
        return True


class OffloadTransportSparkDataprocGcloud(OffloadTransportSparkBatchesGcloud):
    """Submit PySpark to a permanent Managed Spark Dataproc cluster via gcloud."""

    @classmethod
    def for_canary(cls, offload_options: Any, messages: Any) -> Self:
        """Construct a lightweight Dataproc cluster instance configured for canary checks."""
        instance = super().for_canary(offload_options, messages)
        instance._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD
        return instance

    def _gcloud_dataproc_submit_command(self, id: str | None = None) -> list[str]:
        gcloud_cmd = [
            OFFLOAD_TRANSPORT_SPARK_GCLOUD_EXECUTABLE,
            "dataproc",
            "jobs",
            "submit",
            "pyspark",
        ]
        if not self._dataproc_cluster:
            raise OffloadTransportException("Missing mandatory configuration: GOOGLE_DATAPROC_CLUSTER")
        gcloud_cmd.append(f"--cluster={self._dataproc_cluster}")
        if self._dataproc_project:
            gcloud_cmd.append(f"--project={self._dataproc_project}")
        if self._dataproc_region:
            gcloud_cmd.append(f"--region={self._dataproc_region}")
        impersonation_options = self._gcloud_impersonation_options()
        if self._dataproc_service_account and not impersonation_options:
            self._messages.warning(DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED)
        gcloud_cmd.extend(impersonation_options)
        return gcloud_cmd

    def _tune_dataproc_for_parallelism(self) -> list[str]:
        return []

    def _verify_batch(self, batch_name: str) -> None:
        return None


OffloadTransportSparkGcloudBatches = OffloadTransportSparkBatchesGcloud
OffloadTransportSparkGcloudDataproc = OffloadTransportSparkDataprocGcloud

__all__ = [
    "DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED",
    "GCLOUD_BATCHES_STATE_CANCELLED",
    "GCLOUD_BATCHES_STATE_FAILED",
    "GCLOUD_BATCHES_STATE_MESSAGE_TASK_NOT_ACQUIRED",
    "GCLOUD_PROPERTY_SEPARATOR",
    "OffloadTransportSparkBatchesGcloud",
    "OffloadTransportSparkDataprocGcloud",
    "OffloadTransportSparkGcloudBatches",
    "OffloadTransportSparkGcloudDataproc",
]
