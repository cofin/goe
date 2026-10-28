# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Spark Submit offload transport implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from goe.config import orchestration_defaults
from goe.offload.frontend_api import FRONTEND_TRACE_MODULE
from goe.offload.offload_messages import VVERBOSE
from goe.offload.registry import create_transport_rdbms_api
from goe.offload.transport.constants import (
    MISSING_ROWS_SPARK_WARNING,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    SPARK_OPTIONS_FILE_PREFIX,
    SPARK_SUBMIT_SPARK_YARN_MASTER,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
)
from goe.offload.transport.spark.polling import OffloadTransportSpark
from goe.orchestration import command_steps
from goe.util.string_utils import write_temp_file

if TYPE_CHECKING:
    from goe.orchestration.models import OffloadSourcePartitions


class OffloadTransportSparkSubmit(OffloadTransportSpark):
    """Use Python via spark-submit to transport data."""

    def __init__(
        self,
        offload_source_table: Any,
        offload_target_table: Any,
        offload_operation: Any,
        offload_options: Any,
        messages: Any,
        dfs_client: Any,
    ) -> None:
        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        self._load_table_compression_pyspark_settings()
        self._spark_submit_executable = offload_options.offload_transport_spark_submit_executable
        self._offload_transport_spark_submit_master_url = offload_options.offload_transport_spark_submit_master_url
        assert self._spark_submit_executable

    @classmethod
    def for_canary(cls, offload_options: Any, messages: Any) -> OffloadTransportSparkSubmit:
        """Construct a lightweight instance configured for RDBMS connectivity canary checks."""
        instance = cls.__new__(cls)
        instance._spark_submit_executable = offload_options.offload_transport_spark_submit_executable
        assert instance._spark_submit_executable
        instance._offload_options = offload_options
        instance._messages = messages
        instance._dry_run = False
        instance._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT
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
        instance._offload_transport_spark_submit_master_url = offload_options.offload_transport_spark_submit_master_url
        instance._spark_files_csv = offload_options.offload_transport_spark_files
        instance._spark_jars_csv = offload_options.offload_transport_spark_jars
        instance._target_table = None
        instance._rdbms_table = None
        instance._staging_format = None
        return instance

    def transport(self, partition_chunk: OffloadSourcePartitions | None = None) -> int | None:
        """Run Spark transport via spark-submit."""
        self._reset_transport_context()
        return self._messages.offload_step(
            command_steps.STEP_STAGING_TRANSPORT,
            lambda: self._execute_transport_step(partition_chunk),
            execute=(not self._dry_run),
        )

    def ping_source_rdbms(self) -> bool:
        """Verify RDBMS connectivity from Spark Submit."""
        return self._verify_rdbms_connectivity()

    def _execute_transport_step(self, partition_chunk: OffloadSourcePartitions | None = None) -> int | None:
        row_count = self._spark_submit_import(partition_chunk)
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

    def _derive_spark_submit_cmd_arg(self) -> list[str]:
        if self._spark_submit_executable == "spark-submit" and not self._standalone_spark():
            return [
                "export",
                "SPARK_MAJOR_VERSION=2",
                ";",
                self._spark_submit_executable,
            ]
        return [self._spark_submit_executable]

    def _get_spark_submit_command(self, pyspark_body: str) -> tuple[list[Any], list[dict[str, str]], list[list[str]]]:
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

        spark_submit_binary = self._derive_spark_submit_cmd_arg()
        spark_master = (
            self._offload_transport_spark_submit_master_url
            if self._standalone_spark()
            else SPARK_SUBMIT_SPARK_YARN_MASTER
        )
        spark_master_opt = ["--master", spark_master] if spark_master else []
        spark_config_props: list[str] = []
        no_log_password: list[dict[str, str]] = []
        for k, v in self._spark_config_properties.items():
            spark_config_props.extend(["--conf", f"{k}={self._cli_safe_password_value(k, v)}"])
        if "spark.jdbc.password" in self._spark_config_properties and not self._offload_transport_password_alias:
            password_config_to_obscure = f"spark.jdbc.password={self._cli_safe_password_value('spark.jdbc.password', self._spark_config_properties['spark.jdbc.password'])}"
            no_log_password = [{"item": password_config_to_obscure, "prior": "--conf"}]
        if (
            "spark.cores.max" not in self._spark_config_properties
            and self._offload_transport_parallelism
            and spark_master != SPARK_SUBMIT_SPARK_YARN_MASTER
        ):
            spark_config_props.extend(
                [
                    "--conf",
                    f"spark.cores.max={self._offload_transport_parallelism!s}",
                ]
            )

        driver_memory_opt = self._option_from_properties("--driver-memory", "spark.driver.memory")
        executor_memory_opt = self._option_from_properties("--executor-memory", "spark.executor.memory")

        jvm_opts = (
            ["--driver-java-options", f"{self._offload_transport_jvm_overrides}"]
            if self._offload_transport_jvm_overrides
            else []
        )
        jars_opt = ["--jars", remote_spark_jars_csv] if remote_spark_jars_csv else []
        files_opt = ["--files", remote_spark_files_csv] if remote_spark_files_csv else []
        spark_submit_cmd = (
            spark_submit_binary
            + jvm_opts
            + spark_master_opt
            + driver_memory_opt
            + executor_memory_opt
            + jars_opt
            + files_opt
            + spark_config_props
        )
        if self._offload_options.vverbose:
            spark_submit_cmd.append("--verbose")
        if self._offload_transport_queue_name:
            spark_submit_cmd.append(f"--queue={self._offload_transport_queue_name}")

        spark_submit_cmd.append(options_file_remote_path)
        return spark_submit_cmd, no_log_password, py_rm_commands

    def _spark_submit_import(self, partition_chunk: Any = None) -> int | None:
        self._refresh_rdbms_action()

        if self._nothing_to_do(partition_chunk):
            return 0

        rows_imported = None
        pyspark_body = self._get_pyspark_body(partition_chunk)
        (
            spark_submit_cmd,
            no_log_password,
            py_rm_commands,
        ) = self._get_spark_submit_command(pyspark_body)

        self._start_validation_polling_thread()
        _, cmd_out = self._run_os_cmd(self._ssh_cmd_prefix() + spark_submit_cmd, no_log_items=no_log_password)
        self._stop_validation_polling_thread()

        if not self._dry_run:
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

    def _verify_rdbms_connectivity(self) -> bool:
        rdbms_source_query = f"({self._rdbms_api.get_rdbms_canary_query()}) v"
        pyspark_body = self._get_pyspark_body(canary_query=rdbms_source_query)
        self.log("PySpark: " + pyspark_body, detail=VVERBOSE)
        (
            spark_submit_cmd,
            no_log_password,
            py_rm_commands,
        ) = self._get_spark_submit_command(pyspark_body)
        self._run_os_cmd(self._ssh_cmd_prefix() + spark_submit_cmd, no_log_items=no_log_password)
        for rm_cmd in py_rm_commands:
            self._run_os_cmd(rm_cmd)
        return True


__all__ = ["OffloadTransportSparkSubmit"]
