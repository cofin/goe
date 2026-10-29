# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import Mock

import pytest

from goe.offload.offload_messages import OffloadMessages
from goe.offload.offload_transport import (
    OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
    OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
    OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
    OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    OffloadTransportException,
    choose_offload_transport_method,
    get_offload_transport_method_validation_fns,
    is_query_import_available,
    validate_offload_transport_method,
)
from goe.offload.oracle.oracle_column import (
    ORACLE_TYPE_VARCHAR2,
    OracleColumn,
)
from goe.offload.oracle.oracle_offload_source_table import OracleSourceTable
from goe.offload.registry import create_transport
from goe.offload.spark.dataproc_offload_transport import DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED
from goe.offload.transport.duckdb_constants import OFFLOAD_TRANSPORT_METHOD_DUCKDB
from goe.offload.transport.factory import (
    spark_dataproc_batches_jdbc_connectivity_checker,
    spark_dataproc_jdbc_connectivity_checker,
    spark_submit_jdbc_connectivity_checker,
)
from tests.unit.test_functions import (
    FAKE_ORACLE_BQ_ENV,
    build_mock_offload_operation,
    build_mock_options,
)

FRONTEND_COLUMNS = [
    OracleColumn(
        "COL_VARCHAR2",
        ORACLE_TYPE_VARCHAR2,
        char_length=100,
        data_length=100,
    )
]
CALLER_SA = "goe-caller@dp-project.iam.gserviceaccount.com"
DATAPROC_CALLER_SA = "dp-caller@dp-project.iam.gserviceaccount.com"


@pytest.fixture
def config():
    return build_mock_options(FAKE_ORACLE_BQ_ENV)


@pytest.fixture
def messages():
    return OffloadMessages()


@pytest.fixture
def oracle_table(config, messages):
    test_table_object = OracleSourceTable(
        "no_user",
        "no_table",
        config,
        messages,
        dry_run=True,
        do_not_connect=True,
    )
    test_table_object._columns = FRONTEND_COLUMNS
    test_table_object._columns_with_partition_info = FRONTEND_COLUMNS
    test_table_object._size_in_bytes = 1024 * 1024
    return test_table_object


@pytest.fixture
def fake_operation():
    return build_mock_offload_operation()


def test_query_import_construct(config, messages, oracle_table, fake_operation):
    fake_dfs_client = Mock()
    fake_target_table = Mock()
    _ = create_transport(
        OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
        oracle_table,
        fake_target_table,
        fake_operation,
        config,
        messages,
        fake_dfs_client,
    )


@pytest.mark.parametrize(
    "small_table_threshold,expected_status",
    [(0, False), (1, False), (999_999_999_999, True)],
)
def test_is_query_import_available(
    config,
    messages,
    oracle_table,
    fake_operation,
    small_table_threshold,
    expected_status,
):
    fake_operation.offload_transport_small_table_threshold = small_table_threshold
    assert is_query_import_available(fake_operation, config, oracle_table, messages=messages) == expected_status


def test_spark_submit_construct(config, messages, oracle_table, fake_operation):
    fake_dfs_client = Mock()
    fake_target_table = Mock()
    _ = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
        oracle_table,
        fake_target_table,
        fake_operation,
        config,
        messages,
        fake_dfs_client,
    )


def test_spark_submit_canary_construct():
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    _ = spark_submit_jdbc_connectivity_checker(config, messages)


def test_dataproc_cmd(config, messages, oracle_table, fake_operation):
    """batch option should NOT be in standard Managed Spark job commands."""
    fake_dfs_client = Mock()
    fake_target_table = Mock()
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
        oracle_table,
        fake_target_table,
        fake_operation,
        config,
        messages,
        fake_dfs_client,
    )
    cmd = client._gcloud_dataproc_submit_command()
    assert isinstance(cmd, list)

    assert f"--project={config.google_dataproc_project}" in cmd, f"project option is missing from cmd: {cmd}"
    assert f"--cluster={config.google_dataproc_cluster}" in cmd, f"cluster option is missing from cmd: {cmd}"
    assert f"--region={config.google_dataproc_region}" in cmd, f"region option is missing from cmd: {cmd}"
    assert all("--batch=" not in _ for _ in cmd), f"batch option is incorrectly in cmd: {cmd}"


def test_dataproc_canary_construct():
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    _ = spark_dataproc_jdbc_connectivity_checker(config, messages)


def test_dataproc_batches_cmd(config, messages, oracle_table, fake_operation):
    fake_dfs_client = Mock()
    fake_target_table = Mock()
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        oracle_table,
        fake_target_table,
        fake_operation,
        config,
        messages,
        fake_dfs_client,
    )
    cmd = client._gcloud_dataproc_submit_command()
    assert isinstance(cmd, list)

    assert f"--project={config.google_dataproc_project}" in cmd, f"project option is missing from cmd: {cmd}"
    assert f"--region={config.google_dataproc_region}" in cmd, f"region option is missing from cmd: {cmd}"
    assert any("--batch=" in _ for _ in cmd), f"batch option is missing from cmd: {cmd}"
    assert f"--service-account={config.google_dataproc_service_account}" in cmd, (
        f"service account option is missing from cmd: {cmd}"
    )
    assert f"--ttl={config.google_dataproc_batches_ttl}" in cmd, f"ttl option is missing from cmd: {cmd}"


def test_dataproc_batches_describe_cmd(config, messages, oracle_table, fake_operation):
    fake_dfs_client = Mock()
    fake_target_table = Mock()
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        oracle_table,
        fake_target_table,
        fake_operation,
        config,
        messages,
        fake_dfs_client,
    )
    batch_name = "my-unit-batch"
    cmd = client._gcloud_dataproc_describe_command(batch_name)
    assert isinstance(cmd, list)

    assert f"--project={config.google_dataproc_project}" in cmd, f"project option is missing from cmd: {cmd}"
    assert f"--region={config.google_dataproc_region}" in cmd, f"region option is missing from cmd: {cmd}"
    assert batch_name in cmd, f"batch '{batch_name}' is missing from cmd: {cmd}"


@pytest.mark.parametrize(
    "cmd_output,expect_exception",
    [
        (
            """{
  "createTime": "2024-04-26T08:10:01.214382Z",
  "creator": "sa@p.iam.gserviceaccount.com",
  "environmentConfig": {
    "executionConfig": {
      "serviceAccount": "sa@p.iam.gserviceaccount.com",
      "subnetworkUri": "projects/p/regions/west1/subnetworks/s",
      "ttl": "86400s"
    },
    "peripheralsConfig": {
      "sparkHistoryServerConfig": {}
    }
  },
  "name": "projects/p/locations/west1/batches/goe-batch-20240426080958",
  "operation": "projects/p/locations/west1/operations/b4873-4952-3f5d-884d-cec5a2d09",
  "state": "SUCCEEDED",
  "stateHistory": [
    {
      "state": "PENDING",
      "stateStartTime": "2024-04-26T08:10:01.214382Z"
    },
    {
      "state": "RUNNING",
      "stateStartTime": "2024-04-26T08:12:02.032731Z"
    }
  ],
  "stateTime": "2024-04-26T08:13:55.084692Z",
  "uuid": "12cea"
}""",
            False,
        ),
        (
            """{
  "createTime": "2024-04-26T10:09:11.916627Z",
  "creator": "sa@p.iam.gserviceaccount.com",
  "environmentConfig": {
    "executionConfig": {
      "serviceAccount": "sa@p.iam.gserviceaccount.com",
      "subnetworkUri": "projects/p/regions/west1/subnetworks/s",
      "ttl": "600s"
    },
    "peripheralsConfig": {
      "sparkHistoryServerConfig": {}
    }
  },
  "name": "projects/p/locations/west1/batches/goe-batch-20240426080958",
  "operation": "projects/p/locations/west1/operations/b4873-4952-3f5d-884d-cec5a2d09",
  "state": "CANCELLED",
  "stateHistory": [
    {
      "state": "PENDING",
      "stateStartTime": "2024-04-26T10:09:11.916627Z"
    },
    {
      "state": "RUNNING",
      "stateStartTime": "2024-04-26T10:10:33.461859Z"
    },
    {
      "state": "CANCELLING",
      "stateMessage": "Cancelling batch as ttl exceeded",
      "stateStartTime": "2024-04-26T10:19:12.387649Z"
    }
  ],
  "stateTime": "2024-04-26T10:19:12.454387Z",
  "uuid": "12cea"
}""",
            True,
        ),
        (
            """{
  "createTime": "2024-04-26T10:09:11.916627Z",
  "creator": "sa@p.iam.gserviceaccount.com",
  "environmentConfig": {
    "executionConfig": {
      "serviceAccount": "sa@p.iam.gserviceaccount.com",
      "subnetworkUri": "projects/p/regions/west1/subnetworks/s",
      "ttl": "600s"
    },
    "peripheralsConfig": {
      "sparkHistoryServerConfig": {}
    }
  },
  "name": "projects/p/locations/west1/batches/goe-batch-20240426080958",
  "operation": "projects/p/locations/west1/operations/a2d09",
  "state": "FAILED",
  "stateHistory": [
    {
      "state": "PENDING",
      "stateStartTime": "2024-04-26T10:25:59.242854Z"
    },
    {
      "state": "RUNNING",
      "stateStartTime": "2024-04-26T10:27:24.305264Z"
    }
  ],
  "stateMessage": "Job failed with message [SyntaxError: invalid syntax]. Additional details can be found at:\\nhttps://console.cloud.google.com/dataproc/batches/west1/goe-batch-20240426080958?project=p\\ngcloud dataproc batches wait 'goe-batch-20240426080958' --region 'west1' --project 'p'\\nhttps://console.cloud.google.com/storage/browser/dataproc-staging-west1-123-l/batch-3347f/\\ngs://dataproc-staging-west1-123-l/google-cloud-dataproc-metainfo/2ad11/jobs/srvls-batch-3347f/driveroutput.*",
  "stateTime": "2024-04-26T10:27:48.237750Z",
  "uuid": "12cea"
}""",
            True,
        ),
        (
            """{
    "createTime": "2026-05-13T08:05:33Z",
    "creator": "sa@p.iam.gserviceaccount.com",
    "name": "projects/p/locations/west1/batches/goe-batch-canary",
    "state": "FAILED",
    "stateMessage": "Task was not acquired.",
    "uuid": "12cea"
}""",
            True,
        ),
    ],
)
def test_dataproc_batch_describe(
    config,
    messages,
    oracle_table,
    fake_operation,
    cmd_output: str,
    expect_exception: bool,
):
    fake_dfs_client = Mock()
    fake_target_table = Mock()
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        oracle_table,
        fake_target_table,
        fake_operation,
        config,
        messages,
        fake_dfs_client,
    )
    if expect_exception:
        with pytest.raises(Exception) as _:
            client._verify_batch_describe_response(cmd_output)
    else:
        client._verify_batch_describe_response(cmd_output)


@pytest.mark.parametrize(
    "offload_parallelism,offload_spark_props,expected_result",
    [
        (4, {}, []),
        (
            12,
            {},
            [
                "spark.executor.cores=16",
            ],
        ),
        (
            32,
            {},
            [
                "spark.executor.cores=16",
            ],
        ),
        (
            34,
            {},
            [
                "spark.executor.cores=16",
                "spark.executor.instances=3",
            ],
        ),
        (
            48,
            {},
            [
                "spark.executor.cores=16",
                "spark.executor.instances=3",
            ],
        ),
        (
            49,
            {},
            [
                "spark.executor.cores=16",
                "spark.executor.instances=4",
            ],
        ),
        (
            64,
            {"spark.executor.cores": 1},
            [],
        ),
        (
            64,
            {"spark.executor.instances": 1},
            [],
        ),
        (
            64,
            {"spark.executor.unrelated": 123},
            [
                "spark.executor.cores=16",
                "spark.executor.instances=4",
            ],
        ),
    ],
)
def test_dataproc_batches_tune_dataproc_for_parallelism(
    config,
    messages,
    oracle_table,
    fake_operation,
    offload_parallelism: int,
    offload_spark_props: dict,
    expected_result: list,
):
    fake_dfs_client = Mock()
    fake_target_table = Mock()
    fake_operation.offload_transport_parallelism = offload_parallelism
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        oracle_table,
        fake_target_table,
        fake_operation,
        config,
        messages,
        fake_dfs_client,
    )
    if offload_spark_props:
        client._spark_config_properties = offload_spark_props
    result = client._tune_dataproc_for_parallelism()
    assert result == expected_result


def test_dataproc_batches_canary_construct():
    config = build_mock_options(FAKE_ORACLE_BQ_ENV)
    messages = OffloadMessages()
    _ = spark_dataproc_batches_jdbc_connectivity_checker(config, messages)


@pytest.fixture
def no_ambient_impersonation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove caller impersonation variables inherited from the developer shell."""
    monkeypatch.delenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT", raising=False)
    monkeypatch.delenv("GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT", raising=False)


@pytest.fixture
def impersonating_config(no_ambient_impersonation: None):
    """Return a BigQuery config whose gcloud caller impersonates CALLER_SA."""
    return build_mock_options({**FAKE_ORACLE_BQ_ENV, "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": CALLER_SA})


def test_dataproc_batches_cmd_separates_runtime_and_caller_identity(
    impersonating_config, messages, oracle_table, fake_operation
):
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        oracle_table,
        Mock(),
        fake_operation,
        impersonating_config,
        messages,
        Mock(),
    )
    submit_cmd = client._gcloud_dataproc_submit_command()
    describe_cmd = client._gcloud_dataproc_describe_command("my-unit-batch")
    assert f"--service-account={impersonating_config.google_dataproc_service_account}" in submit_cmd
    assert f"--impersonate-service-account={CALLER_SA}" in submit_cmd
    assert f"--impersonate-service-account={CALLER_SA}" in describe_cmd


def test_dataproc_cluster_cmd_impersonates_caller_not_runtime_sa(
    impersonating_config, messages, oracle_table, fake_operation
):
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
        oracle_table,
        Mock(),
        fake_operation,
        impersonating_config,
        messages,
        Mock(),
    )
    cmd = client._gcloud_dataproc_submit_command()
    assert f"--impersonate-service-account={CALLER_SA}" in cmd
    assert f"--impersonate-service-account={impersonating_config.google_dataproc_service_account}" not in cmd


def test_dataproc_cluster_cmd_warns_when_only_runtime_sa_is_set(
    config, messages, oracle_table, fake_operation, no_ambient_impersonation
):
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
        oracle_table,
        Mock(),
        fake_operation,
        config,
        messages,
        Mock(),
    )
    cmd = client._gcloud_dataproc_submit_command()
    assert all(not _.startswith("--impersonate-service-account=") for _ in cmd), cmd
    assert DATAPROC_CLUSTER_SERVICE_ACCOUNT_IGNORED in messages.messages["warnings"]


def test_dataproc_specific_caller_overrides_general_impersonation(
    messages, oracle_table, fake_operation, no_ambient_impersonation
):
    config = build_mock_options(
        {
            **FAKE_ORACLE_BQ_ENV,
            "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": CALLER_SA,
            "GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT": DATAPROC_CALLER_SA,
        }
    )
    client = create_transport(
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        oracle_table,
        Mock(),
        fake_operation,
        config,
        messages,
        Mock(),
    )
    assert f"--impersonate-service-account={DATAPROC_CALLER_SA}" in client._gcloud_dataproc_submit_command()


def test_validation_fns_cover_every_selectable_method(config, messages) -> None:
    """Every concrete transport method has an availability check."""
    fns = get_offload_transport_method_validation_fns(config, messages=messages)
    assert set(fns) == {
        OFFLOAD_TRANSPORT_METHOD_DUCKDB,
        OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_BATCHES_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_DATAPROC_GCLOUD,
        OFFLOAD_TRANSPORT_METHOD_SPARK_LIVY,
        OFFLOAD_TRANSPORT_METHOD_SPARK_SUBMIT,
        OFFLOAD_TRANSPORT_METHOD_SPARK_THRIFT,
    }


def test_validate_rejects_unknown_method(config, messages) -> None:
    """Unknown transport methods are rejected before any availability check."""
    with pytest.raises(OffloadTransportException, match="Unsupported transport method"):
        validate_offload_transport_method("NOT_A_METHOD", config, messages=messages)


@pytest.mark.parametrize("removed_method", ["SQ" + "OOP", "SQ" + "OOP_BY_QUERY"])
def test_validate_rejects_removed_transport_methods(config, messages, removed_method: str) -> None:
    """Removed legacy transport methods are rejected as unsupported."""
    with pytest.raises(OffloadTransportException, match="Unsupported transport method"):
        validate_offload_transport_method(removed_method, config, messages=messages)


def test_choose_method_refuses_mssql(messages) -> None:
    """MSSQL and other non-Oracle frontends are refused during transport selection."""
    mssql_config = Mock(offload_transport="AUTO", db_type="mssql")
    with pytest.raises(OffloadTransportException, match="Unsupported DB type: mssql"):
        choose_offload_transport_method(Mock(), None, mssql_config, messages)
    other_config = Mock(offload_transport="AUTO", db_type="snowflake")
    with pytest.raises(OffloadTransportException, match="Unsupported DB type"):
        choose_offload_transport_method(Mock(), None, other_config, messages)
