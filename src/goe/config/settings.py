# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Declarative, side-effect-free settings structs for GOE."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Annotated, Any, Literal, cast

import msgspec

from goe.config.config_file import load_env
from goe.exceptions import ConfigurationError
from goe.serializers import decode_json
from goe.typing import FrozenBaseStruct
from goe.util.string_utils import split_csv

__all__ = (
    "BigQueryConfig",
    "GOESettings",
    "HadoopConfig",
    "ListenerConfig",
    "ObservabilityConfig",
    "OracleConfig",
    "SnowflakeConfig",
    "SparkTransportConfig",
    "SynapseConfig",
)

type PositiveInt = Annotated[int, msgspec.Meta(ge=1)]
type PortNumber = Annotated[int, msgspec.Meta(ge=1, le=65535)]
type NonEmptyStr = Annotated[str, msgspec.Meta(min_length=1)]
type FsScheme = Literal["gs", "s3", "s3a", "abfs", "abfss", "wasb", "wasbs", "hdfs", "webhdfs", "file", "sftp"]


class OracleConfig(FrozenBaseStruct, frozen=True):
    """Oracle frontend and repository connection settings."""

    adm_user: str = ""
    adm_pass: str = ""
    app_user: str = ""
    app_pass: str = ""
    repo_user: str = ""
    repo_pass: str = ""
    dsn: str = ""
    use_oracle_wallet: bool = False
    thick_client_lib_dir: str | None = None
    thick_client_config_dir: str | None = None


class BigQueryConfig(FrozenBaseStruct, frozen=True):
    """Google BigQuery backend settings."""

    project: str | None = None
    dataset_location: str | None = None
    kms_key_name: str | None = None
    dataproc_project: str | None = None
    dataproc_region: str | None = None
    dataproc_cluster: str | None = None


class SnowflakeConfig(FrozenBaseStruct, frozen=True):
    """Snowflake backend settings."""

    account: str | None = None
    user: str | None = None
    password: str | None = None
    warehouse: str | None = None
    role: str | None = None
    database: str | None = None
    file_format_prefix: str = "GOE_FF"
    stage: str | None = None
    integration: str | None = None


class SynapseConfig(FrozenBaseStruct, frozen=True):
    """Azure Synapse backend settings."""

    server: str | None = None
    database: str | None = None
    user: str | None = None
    password: str | None = None
    auth_mechanism: str = "ActiveDirectoryPassword"
    driver: str = "ODBC Driver 18 for SQL Server"
    external_data_source: str | None = None
    file_format: str | None = None
    msi_client_id: str | None = None


class HadoopConfig(FrozenBaseStruct, frozen=True):
    """Hadoop, Hive, and Impala backend settings."""

    distro: Literal["CDH", "HDP", "CDP", "GCP", "AWS", "GENERIC"] = "GENERIC"
    hive_server_hosts: tuple[str, ...] = ()
    hive_server_port: PortNumber = 10000
    hive_server_user: str | None = None
    hive_server_pass: str | None = None
    hive_server_auth_mechanism: str = "PLAIN"
    hdfs_hosts: tuple[str, ...] = ()
    hdfs_data_dir: str = "/user/goe/offload"
    hdfs_load_dir: str = "/user/goe/load"
    ssh_user: str = "goe"
    kerberos_service: str | None = None
    kerberos_principal: str | None = None
    webhdfs_host: str | None = None
    webhdfs_port: PortNumber = 50070
    webhdfs_verify_ssl: bool | str = True


class SparkTransportConfig(FrozenBaseStruct, frozen=True):
    """Spark, Dataproc, Livy, and Thriftserver transport settings."""

    cmd_hosts: tuple[str, ...] = ()
    transport_user: str | None = None
    spark_submit_executable: str = "spark-submit"
    livy_api_url: str | None = None
    livy_verify_ssl: bool | str = True
    livy_max_sessions: PositiveInt = 4
    thrift_host: str | None = None
    thrift_port: PortNumber = 10015
    queue_name: str | None = None
    rdbms_session_parameters: dict[str, str] = {}


class ListenerConfig(FrozenBaseStruct, frozen=True):
    """GOE Listener HTTP, worker, and telemetry heartbeat settings."""

    host: str = "0.0.0.0"
    port: PortNumber = 8000
    http_workers: PositiveInt = 2
    shared_secret: str | None = None
    redis_url: str | None = None
    heartbeat_interval_seconds: PositiveInt = 60
    endpoint_host_override: str | None = None


class ObservabilityConfig(FrozenBaseStruct, frozen=True):
    """OpenTelemetry tracing, metrics, and log correlation settings."""

    enabled: bool = False
    service_name: str = "goe"
    exporter_protocol: Literal["grpc", "http/protobuf", "console", "none"] = "grpc"
    otlp_endpoint: str | None = None
    sample_ratio: Annotated[float, msgspec.Meta(ge=0.0, le=1.0)] = 1.0
    db_trace_correlation: bool = True
    log_correlation: bool = True


class GOESettings(FrozenBaseStruct, frozen=True):
    """Root immutable settings object for GOE."""

    db_type: Literal["oracle", "mssql"] = "oracle"
    backend_distribution: str = "GOOGLE"
    target: Literal["bigquery", "snowflake", "synapse", "hadoop", "impala", "spark"] = "bigquery"
    offload_home: str = "/opt/goe/offload"
    log_dir: str = "/opt/goe/offload/log"
    offload_fs_scheme: FsScheme = "gs"
    offload_fs_container: str | None = None
    offload_fs_prefix: str = ""
    offload_transport_method: str = "AUTO"
    offload_transport_parallelism: PositiveInt = 4
    oracle: OracleConfig = OracleConfig()
    bigquery: BigQueryConfig = BigQueryConfig()
    snowflake: SnowflakeConfig = SnowflakeConfig()
    synapse: SynapseConfig = SynapseConfig()
    hadoop: HadoopConfig = HadoopConfig()
    spark_transport: SparkTransportConfig = SparkTransportConfig()
    listener: ListenerConfig = ListenerConfig()
    observability: ObservabilityConfig = ObservabilityConfig()

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        env_file: str | None = None,
    ) -> GOESettings:
        """Construct and validate GOESettings from environment variables without I/O side effects."""
        if environ is None:
            if env_file is not None or (
                not os.environ.get("PYTEST_CURRENT_TEST")
                and os.environ.get("GOE_NO_AUTOLOAD_ENV", "").lower() not in ("1", "true")
            ):
                load_env(path=env_file, override=env_file is not None)
            source_env: Mapping[str, str] = os.environ
        else:
            source_env = environ
        raw = _build_raw_settings_mapping(source_env)
        try:
            return msgspec.convert(raw, type=cls, strict=False)
        except msgspec.ValidationError as exc:
            raise ConfigurationError(str(exc), details={"environment_error": str(exc)}) from exc

    def with_dfs_override(
        self,
        *,
        scheme: str | None = None,
        container: str | None = None,
        prefix: str | None = None,
    ) -> GOESettings:
        """Return a new GOESettings instance with overridden DFS storage coordinates."""
        resolved_scheme = cast(FsScheme, scheme.lower()) if scheme is not None else self.offload_fs_scheme
        try:
            updated = msgspec.structs.replace(
                self,
                offload_fs_scheme=resolved_scheme,
                offload_fs_container=container if container is not None else self.offload_fs_container,
                offload_fs_prefix=prefix if prefix is not None else self.offload_fs_prefix,
            )
            return msgspec.convert(msgspec.to_builtins(updated), type=GOESettings, strict=False)
        except msgspec.ValidationError as exc:
            raise ConfigurationError(str(exc), details={"dfs_override_error": str(exc)}) from exc

    def redacted_dict(self) -> dict[str, Any]:
        """Return a dictionary representation with sensitive credential fields redacted."""
        payload = cast(dict[str, Any], msgspec.to_builtins(self))
        for section, keys in _SENSITIVE_SECTION_KEYS.items():
            sub = payload.get(section)
            if isinstance(sub, dict):
                for key in keys:
                    if sub.get(key):
                        sub[key] = "***"
        return payload


_SENSITIVE_SECTION_KEYS: dict[str, tuple[str, ...]] = {
    "oracle": ("adm_pass", "app_pass", "repo_pass"),
    "snowflake": ("password",),
    "synapse": ("password",),
    "hadoop": ("hive_server_pass",),
    "listener": ("shared_secret",),
}


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    """Parse an environment boolean value."""
    if raw is None or not raw.strip():
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ConfigurationError(f"Invalid boolean environment value: {raw!r}")


def _parse_verify_ssl(raw: str | None, *, default: bool = True) -> bool | str:
    """Parse an SSL verification setting that may be a boolean or CA bundle path."""
    if raw is None or not raw.strip():
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return raw.strip()


def _parse_session_parameters(raw: str | None) -> dict[str, str]:
    """Decode a JSON dictionary of RDBMS session parameters."""
    if raw is None or not raw.strip():
        return {}
    try:
        decoded = decode_json(raw)
    except Exception as exc:
        raise ConfigurationError(f"Invalid JSON in OFFLOAD_TRANSPORT_RDBMS_SESSION_PARAMETERS: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ConfigurationError("OFFLOAD_TRANSPORT_RDBMS_SESSION_PARAMETERS must decode to a JSON object")
    return {str(k): str(v) for k, v in decoded.items()}


def _normalize_target(raw: str | None) -> str:
    """Normalize QUERY_ENGINE into a canonical target name."""
    if not raw or not raw.strip():
        return "bigquery"
    lowered = raw.strip().lower()
    if lowered == "hive":
        return "hadoop"
    return lowered


def _normalize_hadoop_distro(raw: str | None) -> str:
    """Normalize BACKEND_DISTRIBUTION into a canonical HadoopConfig distro token."""
    if not raw or not raw.strip():
        return "GENERIC"
    upper = raw.strip().upper()
    if upper in ("CDH", "HDP", "CDP", "GCP", "AWS", "GENERIC"):
        return upper
    return "GENERIC"


def _build_raw_settings_mapping(env: Mapping[str, str]) -> dict[str, Any]:
    """Build a raw nested dictionary from environment variables for msgspec conversion."""
    offload_home = env.get("OFFLOAD_HOME") or "/opt/goe/offload"
    log_dir = env.get("OFFLOAD_LOGDIR") or f"{offload_home}/log"
    db_type_raw = (env.get("FRONTEND_DISTRIBUTION") or env.get("SRCDB_VENDOR") or "oracle").strip().lower()
    fs_scheme_raw = (env.get("OFFLOAD_FS_SCHEME") or "gs").strip().lower()
    if fs_scheme_raw == "inherit":
        fs_scheme_raw = "hdfs"

    raw_protocol = (env.get("GOE_OTEL_PROTOCOL") or "grpc").strip().lower()

    return {
        "db_type": db_type_raw,
        "backend_distribution": (env.get("BACKEND_DISTRIBUTION") or "GOOGLE").strip().upper(),
        "target": _normalize_target(env.get("QUERY_ENGINE")),
        "offload_home": offload_home,
        "log_dir": log_dir,
        "offload_fs_scheme": fs_scheme_raw,
        "offload_fs_container": env.get("OFFLOAD_FS_CONTAINER") or None,
        "offload_fs_prefix": env.get("OFFLOAD_FS_PREFIX") or "",
        "offload_transport_method": (env.get("OFFLOAD_TRANSPORT") or "AUTO").strip().upper(),
        "offload_transport_parallelism": env.get("OFFLOAD_TRANSPORT_PARALLELISM") or 4,
        "oracle": {
            "adm_user": env.get("ORA_ADM_USER") or "",
            "adm_pass": env.get("ORA_ADM_PASS") or "",
            "app_user": env.get("ORA_APP_USER") or "",
            "app_pass": env.get("ORA_APP_PASS") or "",
            "repo_user": env.get("ORA_REPO_USER") or "",
            "repo_pass": env.get("ORA_REPO_PASS") or "",
            "dsn": env.get("ORA_CONN") or "",
            "use_oracle_wallet": _parse_bool(env.get("USE_ORACLE_WALLET"), default=False),
            "thick_client_lib_dir": env.get("ORACLE_CLIENT_LIB_DIR") or None,
            "thick_client_config_dir": env.get("ORACLE_CLIENT_CONFIG_DIR") or None,
        },
        "bigquery": {
            "project": env.get("BIGQUERY_DATASET_PROJECT") or env.get("GOOGLE_CLOUD_PROJECT") or None,
            "dataset_location": env.get("BIGQUERY_DATASET_LOCATION") or None,
            "kms_key_name": env.get("GOOGLE_KMS_KEY_NAME") or None,
            "dataproc_project": env.get("GOOGLE_DATAPROC_PROJECT") or None,
            "dataproc_region": env.get("GOOGLE_DATAPROC_REGION") or None,
            "dataproc_cluster": env.get("GOOGLE_DATAPROC_CLUSTER") or None,
        },
        "snowflake": {
            "account": env.get("SNOWFLAKE_ACCOUNT") or None,
            "user": env.get("SNOWFLAKE_USER") or None,
            "password": env.get("SNOWFLAKE_PASS") or None,
            "warehouse": env.get("SNOWFLAKE_WAREHOUSE") or None,
            "role": env.get("SNOWFLAKE_ROLE") or None,
            "database": env.get("SNOWFLAKE_DATABASE") or None,
            "file_format_prefix": env.get("SNOWFLAKE_FILE_FORMAT_PREFIX") or "GOE_FF",
            "stage": env.get("SNOWFLAKE_STAGE") or None,
            "integration": env.get("SNOWFLAKE_INTEGRATION") or None,
        },
        "synapse": {
            "server": env.get("SYNAPSE_SERVER") or None,
            "database": env.get("SYNAPSE_DATABASE") or None,
            "user": env.get("SYNAPSE_USER") or None,
            "password": env.get("SYNAPSE_PASS") or None,
            "auth_mechanism": env.get("SYNAPSE_AUTH_MECHANISM") or "ActiveDirectoryPassword",
            "driver": env.get("BACKEND_ODBC_DRIVER_NAME") or "ODBC Driver 18 for SQL Server",
            "external_data_source": env.get("SYNAPSE_DATA_SOURCE") or None,
            "file_format": env.get("SYNAPSE_FILE_FORMAT") or None,
            "msi_client_id": env.get("SYNAPSE_MSI_CLIENT_ID") or None,
        },
        "hadoop": {
            "distro": _normalize_hadoop_distro(env.get("BACKEND_DISTRIBUTION")),
            "hive_server_hosts": tuple(split_csv(env.get("HIVE_SERVER_HOST"))),
            "hive_server_port": env.get("HIVE_SERVER_PORT") or 10000,
            "hive_server_user": env.get("HIVE_SERVER_USER") or None,
            "hive_server_pass": env.get("HIVE_SERVER_PASS") or None,
            "hive_server_auth_mechanism": env.get("HIVE_SERVER_AUTH_MECHANISM") or "PLAIN",
            "hdfs_hosts": tuple(split_csv(env.get("HDFS_CMD_HOST") or env.get("HDFS_HOST"))),
            "hdfs_data_dir": env.get("HDFS_DATA") or "/user/goe/offload",
            "hdfs_load_dir": env.get("HDFS_LOAD") or "/user/goe/load",
            "ssh_user": env.get("HADOOP_SSH_USER") or "goe",
            "kerberos_service": env.get("KERBEROS_SERVICE") or None,
            "kerberos_principal": env.get("KERBEROS_PRINCIPAL") or None,
            "webhdfs_host": env.get("WEBHDFS_HOST") or None,
            "webhdfs_port": env.get("WEBHDFS_PORT") or 50070,
            "webhdfs_verify_ssl": _parse_verify_ssl(env.get("WEBHDFS_VERIFY_SSL"), default=True),
        },
        "spark_transport": {
            "cmd_hosts": tuple(split_csv(env.get("OFFLOAD_TRANSPORT_CMD_HOST"))),
            "transport_user": env.get("OFFLOAD_TRANSPORT_USER") or None,
            "spark_submit_executable": env.get("OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE") or "spark-submit",
            "livy_api_url": env.get("OFFLOAD_TRANSPORT_LIVY_API_URL") or None,
            "livy_verify_ssl": _parse_verify_ssl(env.get("OFFLOAD_TRANSPORT_LIVY_API_VERIFY_SSL"), default=True),
            "livy_max_sessions": env.get("OFFLOAD_TRANSPORT_LIVY_MAX_SESSIONS") or 4,
            "thrift_host": env.get("OFFLOAD_TRANSPORT_SPARK_THRIFT_HOST") or None,
            "thrift_port": env.get("OFFLOAD_TRANSPORT_SPARK_THRIFT_PORT") or 10015,
            "queue_name": env.get("OFFLOAD_TRANSPORT_SPARK_QUEUE_NAME") or None,
            "rdbms_session_parameters": _parse_session_parameters(
                env.get("OFFLOAD_TRANSPORT_RDBMS_SESSION_PARAMETERS")
            ),
        },
        "listener": {
            "host": env.get("OFFLOAD_LISTENER_HOST") or "0.0.0.0",
            "port": env.get("OFFLOAD_LISTENER_PORT") or 8000,
            "http_workers": env.get("OFFLOAD_LISTENER_HTTP_WORKERS") or 2,
            "shared_secret": env.get("OFFLOAD_LISTENER_SHARED_TOKEN") or None,
            "redis_url": env.get("OFFLOAD_LISTENER_REDIS_URL") or None,
            "heartbeat_interval_seconds": env.get("OFFLOAD_LISTENER_HEARTBEAT_INTERVAL") or 60,
            "endpoint_host_override": env.get("OFFLOAD_LISTENER_ENDPOINT_HOST_OVERRIDE") or None,
        },
        "observability": {
            "enabled": _parse_bool(env.get("GOE_OTEL_ENABLED"), default=False),
            "service_name": env.get("GOE_OTEL_SERVICE_NAME") or "goe",
            "exporter_protocol": raw_protocol,
            "otlp_endpoint": env.get("GOE_OTEL_ENDPOINT") or env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
            "sample_ratio": env.get("GOE_OTEL_SAMPLE_RATE") or 1.0,
            "db_trace_correlation": _parse_bool(env.get("GOE_OTEL_SQLCOMMENTER"), default=True),
            "log_correlation": _parse_bool(env.get("GOE_OTEL_LOG_CORRELATION"), default=True),
        },
    }
