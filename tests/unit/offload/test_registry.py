# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the declarative AdapterRegistry and adapter constructors."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from goe.exceptions import OffloadException
from goe.offload.offload_constants import DBTYPE_SYNAPSE
from goe.offload.offload_messages import VVERBOSE
from goe.offload.registry import (
    ADAPTER_REGISTRY,
    AdapterEntry,
    AdapterKind,
    AdapterNotRegisteredError,
    AdapterRegistry,
    LazyTarget,
    create_backend_api,
    create_backend_table,
    create_query_import_encoder,
    create_source_table,
    create_transport,
)
from goe.offload.transport.constants import OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT
from goe.offload.transport.query_import import OffloadTransportQueryImport
from goe.typing import FrozenBaseStruct
from goe.util.module_loader import MissingOptionalDependencyError

_EXTRA_PROBE_MODULES = {
    "hadoop": "impala",
    "snowflake": "snowflake.connector",
    "synapse": "pyodbc",
    "sql_server": "mssql_python",
}


def test_resolve_dry_run_returns_target_without_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify resolve_dry_run returns LazyTarget without importing the adapter module."""
    monkeypatch.delitem(sys.modules, "goe.offload.microsoft.synapse_backend_api", raising=False)
    target = ADAPTER_REGISTRY.resolve_dry_run(AdapterKind.BACKEND_API, DBTYPE_SYNAPSE)
    assert target == LazyTarget("goe.offload.microsoft.synapse_backend_api", "BackendSynapseApi", "synapse")
    assert target.path == "goe.offload.microsoft.synapse_backend_api:BackendSynapseApi"
    assert "goe.offload.microsoft.synapse_backend_api" not in sys.modules


def test_resolve_loads_registered_class() -> None:
    """Verify resolve imports and returns the registered adapter class."""
    cls = ADAPTER_REGISTRY.resolve(AdapterKind.TRANSPORT, OFFLOAD_TRANSPORT_METHOD_QUERY_IMPORT)
    assert cls is OffloadTransportQueryImport


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        (AdapterKind.FRONTEND_API, "teradata"),
        (AdapterKind.SOURCE_TABLE, "teradata"),
        (AdapterKind.TRANSPORT_RDBMS_API, "teradata"),
        (AdapterKind.REPOSITORY_CLIENT, "teradata"),
        (AdapterKind.TRANSPORT, "SQOOP"),
        (AdapterKind.TRANSPORT, "SQOOP_BY_QUERY"),
        (AdapterKind.STAGING_FILE, "PARQUET:hive"),
    ],
)
def test_unregistered_adapters_raise(kind: AdapterKind, key: str) -> None:
    """Verify unregistered or removed adapters raise AdapterNotRegisteredError."""
    with pytest.raises(AdapterNotRegisteredError, match=f"No {kind.value} adapter registered for: {key}") as exc_info:
        ADAPTER_REGISTRY.resolve_dry_run(kind, key)
    assert isinstance(exc_info.value, OffloadException)


def test_registered_keys() -> None:
    """Verify the exact set of retained keys for each AdapterKind."""
    assert ADAPTER_REGISTRY.keys(AdapterKind.FRONTEND_API) == ("mssql", "oracle")
    assert ADAPTER_REGISTRY.keys(AdapterKind.SOURCE_TABLE) == ("mssql", "oracle")
    assert ADAPTER_REGISTRY.keys(AdapterKind.TRANSPORT_RDBMS_API) == ("mssql", "oracle")
    assert ADAPTER_REGISTRY.keys(AdapterKind.TRANSPORT) == (
        "DUCKDB",
        "QUERY_IMPORT",
        "SPARK_BATCHES_GCLOUD",
        "SPARK_DATAPROC_GCLOUD",
        "SPARK_LIVY",
        "SPARK_SUBMIT",
        "SPARK_THRIFT",
    )
    assert ADAPTER_REGISTRY.keys(AdapterKind.BACKEND_API) == (
        "bigquery",
        "hive",
        "impala",
        "snowflake",
        "spark",
        "synapse",
    )
    assert ADAPTER_REGISTRY.keys(AdapterKind.BACKEND_TABLE) == (
        "bigquery",
        "hive",
        "impala",
        "snowflake",
        "synapse",
    )
    assert ADAPTER_REGISTRY.keys(AdapterKind.STAGING_FILE) == (
        "AVRO:bigquery",
        "AVRO:hive",
        "AVRO:impala",
        "AVRO:snowflake",
        "PARQUET:bigquery",
        "PARQUET:snowflake",
        "PARQUET:synapse",
    )
    assert ADAPTER_REGISTRY.keys(AdapterKind.QUERY_IMPORT_ENCODER) == ("AVRO", "PARQUET")
    assert ADAPTER_REGISTRY.keys(AdapterKind.REPOSITORY_CLIENT) == ("oracle",)


def test_duplicate_registration_is_rejected() -> None:
    """Verify duplicate adapter registration raises ValueError."""
    entry = AdapterEntry(
        AdapterKind.REPOSITORY_CLIENT,
        "oracle",
        LazyTarget("goe.persistence.oracle.oracle_repository", "OracleRepositoryService"),
    )
    with pytest.raises(ValueError, match="Duplicate adapter registration"):
        AdapterRegistry((entry, entry))


@pytest.mark.parametrize(
    "entry",
    ADAPTER_REGISTRY.entries(),
    ids=lambda e: f"{e.kind.value}:{e.key}",
)
def test_every_target_loads(entry: AdapterEntry) -> None:
    """Verify every registered target resolves to its expected class when extras are installed."""
    if entry.target.extra in _EXTRA_PROBE_MODULES:
        pytest.importorskip(_EXTRA_PROBE_MODULES[entry.target.extra])
    loaded_cls = ADAPTER_REGISTRY.resolve(entry.kind, entry.key)
    assert loaded_cls.__name__ == entry.target.attribute


def test_create_backend_api_dry_run_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_backend_api derives dry_run from execute and do_not_connect."""
    fake_cls = Mock()
    monkeypatch.setattr(AdapterRegistry, "resolve", lambda self, kind, key: fake_cls)
    messages = Mock()

    create_backend_api("bigquery", SimpleNamespace(execute=True), messages)
    assert fake_cls.call_args.kwargs["dry_run"] is False

    create_backend_api("bigquery", SimpleNamespace(), messages, do_not_connect=True)
    assert fake_cls.call_args.kwargs["dry_run"] is True

    create_backend_api("bigquery", SimpleNamespace(), messages, do_not_connect=False)
    assert fake_cls.call_args.kwargs["dry_run"] is False


def test_create_backend_table_uses_operation_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_backend_table prefers operation execute flag and operation hybrid metadata."""
    fake_cls = Mock()
    monkeypatch.setattr(AdapterRegistry, "resolve", lambda self, kind, key: fake_cls)
    messages = Mock()
    operation = Mock(execute=False)
    operation.get_hybrid_metadata.return_value = "meta"

    create_backend_table(
        "db",
        "t",
        "bigquery",
        SimpleNamespace(execute=True),
        messages,
        orchestration_operation=operation,
    )
    assert fake_cls.call_args.kwargs["dry_run"] is True
    assert fake_cls.call_args.kwargs["hybrid_metadata"] == "meta"


def test_create_source_table_passes_conn_only_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_source_table omits conn when None and enables subpartition offload when requested."""
    fake_cls = Mock()
    monkeypatch.setattr(AdapterRegistry, "resolve", lambda self, kind, key: fake_cls)
    messages = Mock()

    create_source_table("o", "t", SimpleNamespace(db_type="mssql"), messages)
    assert "conn" not in fake_cls.call_args.kwargs

    create_source_table(
        "o",
        "t",
        SimpleNamespace(db_type="oracle"),
        messages,
        conn="c",
        offload_by_subpartition=True,
    )
    assert fake_cls.call_args.kwargs["conn"] == "c"
    fake_cls.return_value.enable_offload_by_subpartition.assert_called_once_with()


def test_create_transport_logs_class_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_transport logs the resolved class name at VVERBOSE."""
    fake_cls = Mock()
    fake_cls.__name__ = "FakeTransport"
    monkeypatch.setattr(AdapterRegistry, "resolve", lambda self, kind, key: fake_cls)
    messages = Mock()

    create_transport("QUERY_IMPORT", "src", "tgt", "op", "opts", messages, "dfs")
    fake_cls.assert_called_once_with("src", "tgt", "op", "opts", messages, "dfs")
    messages.log.assert_called_once_with("Data transport method: FakeTransport", detail=VVERBOSE)


def test_create_query_import_encoder_schema_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_query_import_encoder requests string schema for Avro and object schema for Parquet."""
    fake_cls = Mock()
    monkeypatch.setattr(AdapterRegistry, "resolve", lambda self, kind, key: fake_cls)
    messages = Mock()

    staging_avro = Mock(file_format="AVRO")
    create_query_import_encoder(staging_avro, messages)
    staging_avro.get_file_schema_json.assert_called_once_with(as_string=True)

    staging_parquet = Mock(file_format="PARQUET")
    create_query_import_encoder(staging_parquet, messages)
    staging_parquet.get_file_schema_json.assert_called_once_with(as_string=False)


def test_lazy_target_and_adapter_entry_use_frozen_base_struct_and_ensure_module() -> None:
    """LazyTarget and AdapterEntry inherit from FrozenBaseStruct and surface MissingOptionalDependencyError."""
    assert issubclass(LazyTarget, FrozenBaseStruct)
    assert issubclass(AdapterEntry, FrozenBaseStruct)

    target = LazyTarget("nonexistent_mod_xyz_999", "Cls", "synapse")
    with pytest.raises(MissingOptionalDependencyError, match="synapse"):
        target.load()
