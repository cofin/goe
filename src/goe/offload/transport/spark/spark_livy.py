# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Spark Livy REST offload transport implementation."""

from __future__ import annotations

import os
import re
import time
from typing import Any

from goe.config import orchestration_defaults
from goe.filesystem.goe_dfs_factory import get_dfs_from_options
from goe.offload.frontend_api import FRONTEND_TRACE_MODULE
from goe.offload.offload_constants import LIVY_MAX_SESSIONS
from goe.offload.offload_messages import VERBOSE, VVERBOSE
from goe.offload.offload_transport_functions import (
    finish_progress_on_stdout,
    write_progress_to_stdout,
)
from goe.offload.registry import create_transport_rdbms_api
from goe.offload.spark.offload_transport_livy_requests import OffloadTransportLivyRequests
from goe.offload.transport.constants import (
    GOE_LISTENER_JAR,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    TRANSPORT_CXT_BYTES,
    TRANSPORT_CXT_ROWS,
    YARN_TRANSPORT_NAME,
)
from goe.offload.transport.protocol import OffloadTransportException
from goe.offload.transport.spark.polling import OffloadTransportSpark
from goe.orchestration import command_steps
from goe.serializers import encode_json

URL_SEP = "/"
LIVY_SESSIONS_SUBURL = "sessions"
LIVY_LOG_QUEUE_PATTERN = r"^\s*queue:\s*%s$"
LIVY_CONNECT_POLL_DELAY = 2
LIVY_CONNECT_MAX_POLLS = 30
LIVY_STATEMENT_POLL_DELAY = 5


class OffloadTransportSparkLivy(OffloadTransportSpark):
    """Use PySpark via Livy REST interface to transport data."""

    def __init__(
        self,
        offload_source_table: Any,
        offload_target_table: Any,
        offload_operation: Any,
        offload_options: Any,
        messages: Any,
        dfs_client: Any,
    ) -> None:
        self._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY
        super().__init__(
            offload_source_table,
            offload_target_table,
            offload_operation,
            offload_options,
            messages,
            dfs_client,
        )
        assert offload_options.offload_transport_livy_api_url, "REST API URL has not been defined"
        self._api_url = offload_options.offload_transport_livy_api_url
        self._livy_requests = OffloadTransportLivyRequests(offload_options, messages)
        self._livy_max_sessions = (
            int(offload_options.offload_transport_livy_max_sessions)
            if offload_options.offload_transport_livy_max_sessions
            else LIVY_MAX_SESSIONS
        )
        self._idle_session_timeout = int(offload_options.offload_transport_livy_idle_session_timeout)
        self._load_table_compression_pyspark_settings()

    @classmethod
    def for_canary(cls, offload_options: Any, messages: Any) -> OffloadTransportSparkLivy:
        """Construct a lightweight instance configured for RDBMS connectivity canary checks."""
        instance = cls.__new__(cls)
        assert offload_options.offload_transport_livy_api_url, "REST API URL has not been defined"
        instance._offload_options = offload_options
        instance._messages = messages
        instance._dry_run = False
        instance._api_url = offload_options.offload_transport_livy_api_url
        instance._livy_requests = OffloadTransportLivyRequests(offload_options, messages)
        instance._livy_max_sessions = (
            int(offload_options.offload_transport_livy_max_sessions)
            if offload_options.offload_transport_livy_max_sessions
            else LIVY_MAX_SESSIONS
        )
        instance._idle_session_timeout = 30
        instance._dfs_client = get_dfs_from_options(
            instance._offload_options,
            messages=instance._messages,
            dry_run=instance._dry_run,
        )
        instance._backend_dfs = instance._dfs_client.backend_dfs
        instance._offload_transport_method = OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY
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
        instance._target_table = None
        instance._rdbms_table = None
        instance._staging_format = None
        return instance

    def transport(self, partition_chunk: Any = None) -> int | None:
        """Run Spark transport via Livy REST session."""
        self._reset_transport_context()
        return self._messages.offload_step(
            command_steps.STEP_STAGING_TRANSPORT,
            lambda: self._execute_transport_step(partition_chunk),
            execute=(not self._dry_run),
        )

    def ping_source_rdbms(self) -> bool:
        """Verify RDBMS connectivity from Livy Spark session."""
        return self._verify_rdbms_connectivity()

    def _execute_transport_step(self, partition_chunk: Any = None) -> int | None:
        row_count = self._livy_import(partition_chunk)
        staged_bytes = self._check_and_log_transported_files(row_count)
        self._transport_context[TRANSPORT_CXT_BYTES] = staged_bytes
        self._transport_context[TRANSPORT_CXT_ROWS] = row_count
        self._target_table.post_transport_tasks(self._staging_file)
        return row_count

    def _get_transport_app_name(
        self,
        sep: str = ".",
        ts: bool = False,
        name_override: str | None = None,
    ) -> str:
        return YARN_TRANSPORT_NAME

    def _column_type_read_remappings(self) -> list[str] | str:
        return self._offload_transport_type_remappings(return_as_list=False, remap_sep="=")

    def _close_livy_session(self, session_url: str | None) -> None:
        if not session_url:
            return
        try:
            self.log(f"Closing session: {session_url}", detail=VVERBOSE)
            self._livy_requests.delete(session_url)
        except Exception:
            self.log(f"Unable to close session: {session_url}", detail=VVERBOSE)

    def _log_app_info(self, resp_json: dict[str, Any], last_log_msg: Any) -> Any:
        if resp_json.get("log"):
            log_msg = resp_json["log"]
            if log_msg != last_log_msg:
                self._messages.log_timestamp(detail=VVERBOSE)
                self.log(
                    ("\n".join(_ for _ in log_msg) if isinstance(log_msg, list) else str(log_msg)),
                    detail=VVERBOSE,
                )
            return log_msg
        return None

    def _get_api_sessions_url(self) -> str:
        return URL_SEP.join([self._api_url, LIVY_SESSIONS_SUBURL])

    def _copy_goe_listener_jar_to_dfs(self) -> str:
        self.debug("_copy_goe_listener_jar_to_dfs()")
        spark_listener_jar_local_path = self._local_goe_listener_jar()
        if self._standalone_spark():
            return self._remote_copy_transport_file(spark_listener_jar_local_path, self._offload_transport_cmd_host)
        spark_listener_jar_remote_path = os.path.join(self._offload_options.hdfs_home, GOE_LISTENER_JAR)
        self.log_dfs_cmd(f'copy_from_local("{spark_listener_jar_local_path}", "{spark_listener_jar_remote_path}")')
        if not self._dry_run:
            self._dfs_client.copy_from_local(
                spark_listener_jar_local_path,
                spark_listener_jar_remote_path,
                overwrite=True,
            )
        return spark_listener_jar_remote_path

    def _add_payload_option_from_spark_properties(
        self, payload: dict[str, Any], key_name: str, property_name: str
    ) -> None:
        kv = self._option_from_properties(key_name, property_name)
        if kv:
            self.log(f"Adding {kv[0]} = {kv[1]} to session payload", detail=VVERBOSE)
            payload[kv[0]] = kv[1]

    def _create_livy_session(self) -> str | None:
        last_log_msg, session_url = None, None
        remote_jar_file_path = (
            self._copy_goe_listener_jar_to_dfs() if self._spark_listener_included_in_config() else None
        )

        data: dict[str, Any] = {
            "kind": "pyspark",
            "heartbeatTimeoutInSecond": self._idle_session_timeout,
            "name": self._get_transport_app_name(),
            "conf": self._spark_config_properties,
            "jars": [remote_jar_file_path] if remote_jar_file_path else None,
        }
        if self._offload_transport_queue_name:
            data["queue"] = self._offload_transport_queue_name
        self._add_payload_option_from_spark_properties(data, "driverMemory", "spark.driver.memory")
        self._add_payload_option_from_spark_properties(data, "executorMemory", "spark.executor.memory")
        self.log(
            "%s: Requesting Livy session: %s"
            % (
                self._str_time(),
                str({k: data[k] for k in ["kind", "heartbeatTimeoutInSecond", "name"]}),
            ),
            detail=VVERBOSE,
        )

        resp = self._livy_requests.post(self._get_api_sessions_url(), data=encode_json(data))
        if resp.ok:
            self.log(f"Livy session id: {resp.json().get('id')}", detail=VVERBOSE)
            session_url = (self._api_url + resp.headers["location"]) if resp.headers.get("location") else None
            session_state = None
            polls = 0
            while polls <= LIVY_CONNECT_MAX_POLLS and session_url:
                session_state = resp.json()["state"]
                if session_state == "idle" and session_url:
                    if not self._offload_options.vverbose:
                        finish_progress_on_stdout()
                    self.log(f"REST session started: {session_url}", detail=VVERBOSE)
                    return session_url
                if session_state == "starting":
                    last_log_msg = self._log_app_info(resp.json(), last_log_msg)
                    time.sleep(LIVY_CONNECT_POLL_DELAY)
                    polls += 1
                    self.log(f"{self._str_time()}: Polling session with state: {session_state}", detail=VVERBOSE)
                    resp = self._livy_requests.get(session_url)
                    if not resp.ok:
                        self.log(f"Response code: {resp.status_code}", detail=VERBOSE)
                        self.log(f"Response text: {resp.text}", detail=VERBOSE)
                        self._close_livy_session(session_url)
                        resp.raise_for_status()
                    elif not self._offload_options.vverbose:
                        write_progress_to_stdout()
                else:
                    self.log(f"Response text: {resp.text}", detail=VVERBOSE)
                    self._close_livy_session(session_url)
                    raise OffloadTransportException(f"REST session was not created: state={session_state}")
            self.log(f"Response text: {resp.text}", detail=VVERBOSE)
            self._close_livy_session(session_url)
            raise OffloadTransportException(f"REST session was not created, timing out: state={session_state}")
        self.log(f"Response code: {resp.status_code}", detail=VERBOSE)
        self.log(f"Response text: {resp.text}", detail=VERBOSE)
        resp.raise_for_status()
        return None

    def _is_goe_usable_session(self, job_dict: dict[str, Any], ignore_session_state: bool = False) -> bool:
        if job_dict.get("kind") != "pyspark" or (job_dict.get("state") != "idle" and not ignore_session_state):
            return False
        if self._offload_transport_queue_name:
            pattern = re.compile(
                LIVY_LOG_QUEUE_PATTERN % self._offload_transport_queue_name,
                re.IGNORECASE,
            )
            return bool([_ for _ in (job_dict.get("log") or []) if pattern.search(_)])
        return True

    def _attach_livy_session(self) -> str | None:
        resp = self._livy_requests.get(self._get_api_sessions_url())
        if resp.ok:
            sessions = resp.json()["sessions"] or []
            goe_usable_sessions = [_ for _ in sessions if self._is_goe_usable_session(_)]
            self.log(f"Found {len(goe_usable_sessions)} usable Livy sessions", detail=VVERBOSE)
            if len(goe_usable_sessions) > 0:
                use_session = goe_usable_sessions.pop()
                self.log(
                    f"Re-using Livy session: {use_session['id']!s}/{use_session.get('appId')}",
                    detail=VERBOSE,
                )
                return URL_SEP.join([self._get_api_sessions_url(), str(use_session["id"])])
            all_goe_sessions = [_ for _ in sessions if self._is_goe_usable_session(_, ignore_session_state=True)]
            self.log(f"No usable Livy sessions out of total: {len(all_goe_sessions)}", detail=VVERBOSE)
            if len(all_goe_sessions) < self._livy_max_sessions:
                return self._create_livy_session()
            self.log(f"All goe capable Livy sessions: {all_goe_sessions!s}", detail=VVERBOSE)
            raise OffloadTransportException(
                f"Exceeded maximum Livy sessions for offload transport: {self._livy_max_sessions!s}"
            )
        self.log(f"Response code: {resp.status_code}", detail=VERBOSE)
        self.log(f"Response text: {resp.text}", detail=VERBOSE)
        resp.raise_for_status()
        return None

    def _submit_pyspark_to_session(self, session_url: str | None, payload_data: str) -> str | None:
        assert session_url is not None
        last_log_msg = None
        statements_url = URL_SEP.join([session_url, "statements"])
        payload = {"code": payload_data}
        resp = self._livy_requests.post(statements_url, data=encode_json(payload))
        if resp.ok:
            statement_url = (self._api_url + resp.headers["location"]) if resp.headers.get("location") else None
            self.log(f"Submitted REST statement: {statement_url}", detail=VERBOSE)
            while True:
                statement_state = resp.json()["state"]
                if statement_state == "available":
                    self.log(f"REST statement complete: {statement_url}", detail=VVERBOSE)
                    statement_output = resp.json().get("output")
                    self.log(f"Output: {statement_output}", detail=VVERBOSE)
                    status = statement_output.get("status") if statement_output else None
                    if status != "ok":
                        raise OffloadTransportException(f"Spark statement has failed with status: {status}")
                    return str(statement_output.get("data")).replace("\\n", "\n")
                if statement_state in ("running", "waiting"):
                    last_log_msg = self._log_app_info(resp.json(), last_log_msg)
                    time.sleep(LIVY_STATEMENT_POLL_DELAY)
                    self.log(f"{self._str_time()}: Polling statement with state: {statement_state}", detail=VVERBOSE)
                    resp = self._livy_requests.get(statement_url)
                    if not resp.ok:
                        self.log(f"Response code: {resp.status_code}", detail=VERBOSE)
                        self.log(f"Response text: {resp.text}", detail=VERBOSE)
                        resp.raise_for_status()
                else:
                    self.log(f"Response text: {resp.text}", detail=VVERBOSE)
                    raise OffloadTransportException(f"Spark statement has unexpected state: {statement_state}")
        else:
            self.log(f"Response code: {resp.status_code}", detail=VERBOSE)
            self.log(f"Response text: {resp.text}", detail=VERBOSE)
            resp.raise_for_status()
        return None

    def _livy_import(self, partition_chunk: Any = None) -> int | None:
        self._refresh_rdbms_action()

        if self._nothing_to_do(partition_chunk):
            return 0

        pyspark_body = self._get_pyspark_body(partition_chunk, create_spark_context=False)
        self.log("PySpark: " + pyspark_body, detail=VVERBOSE)
        session_url = self._attach_livy_session()
        if not self._dry_run:
            self._start_validation_polling_thread()
            self._submit_pyspark_to_session(session_url, pyspark_body)
            self._stop_validation_polling_thread()
            rows_imported = self._rdbms_api.log_sql_stats(
                self._rdbms_module,
                self._rdbms_action,
                self._drain_validation_polling_thread_queue(),
                validation_polling_interval=self._validation_polling_interval,
            )
            self._check_rows_imported(rows_imported)
            return rows_imported
        return None

    def _verify_rdbms_connectivity(self) -> bool:
        rdbms_source_query = f"({self._rdbms_api.get_rdbms_canary_query()}) v"
        pyspark_body = self._get_pyspark_body(canary_query=rdbms_source_query)
        self.log("PySpark: " + pyspark_body, detail=VVERBOSE)
        session_url = self._attach_livy_session()
        self._submit_pyspark_to_session(session_url, pyspark_body)
        return True


__all__ = [
    "LIVY_CONNECT_MAX_POLLS",
    "LIVY_CONNECT_POLL_DELAY",
    "LIVY_LOG_QUEUE_PATTERN",
    "LIVY_SESSIONS_SUBURL",
    "LIVY_STATEMENT_POLL_DELAY",
    "URL_SEP",
    "OffloadTransportSparkLivy",
]
