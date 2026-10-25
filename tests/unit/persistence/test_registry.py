# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OracleConnectionSettings and OracleDatabaseRegistry."""

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import oracledb
import pytest
from sqlspec.core.sqlcommenter import SQLCommenterContext

import goe.persistence.registry as registry_module
from goe.observability import runtime
from goe.observability.config import ObservabilitySettings
from goe.observability.spans import traced_command
from goe.persistence.registry import (
    POOL_MAX_SESSIONS,
    POOL_PING_INTERVAL_SECONDS,
    OracleConnectionSettings,
    OracleDatabaseRegistry,
    OracleRegistryError,
)
from tests.unit.test_functions import FAKE_ORACLE_ENV, build_mock_options


class FakePool:
    """In-memory stand-in for an oracledb synchronous connection pool."""

    def __init__(self, version: str = "19.3.0.0.0") -> None:
        self.version = version
        self.acquired: list[MagicMock] = []
        self.released: list[MagicMock] = []
        self.dropped: list[MagicMock] = []
        self.closed = False

    def acquire(self) -> MagicMock:
        """Acquire a mock connection."""
        conn = MagicMock()
        conn.version = self.version
        self.acquired.append(conn)
        return conn

    def release(self, conn: MagicMock) -> None:
        """Release a mock connection back to the pool."""
        self.released.append(conn)

    def drop(self, conn: MagicMock) -> None:
        """Drop a mock connection from the pool."""
        self.dropped.append(conn)

    def close(self, *args: Any, **kwargs: Any) -> None:
        """Mark the pool closed."""
        del args, kwargs
        self.closed = True


class FakeAsyncPool:
    """In-memory stand-in for an oracledb asynchronous connection pool."""

    def __init__(self) -> None:
        self.acquired: list[MagicMock] = []
        self.released: list[MagicMock] = []
        self.closed = False

    async def acquire(self) -> MagicMock:
        """Acquire a mock async connection."""
        conn = MagicMock()
        self.acquired.append(conn)
        return conn

    async def release(self, conn: MagicMock, **kwargs: Any) -> None:
        """Release a mock async connection."""
        del kwargs
        self.released.append(conn)

    async def close(self, *args: Any, **kwargs: Any) -> None:
        """Mark the async pool closed."""
        del args, kwargs
        self.closed = True


@pytest.fixture(autouse=True)
def clear_registries() -> Iterator[None]:
    """Ensure every test starts and ends with an empty registry cache."""
    OracleDatabaseRegistry.close_all()
    yield
    OracleDatabaseRegistry.close_all()


@pytest.fixture
def settings() -> OracleConnectionSettings:
    """Return sample password-authenticated Oracle connection settings."""
    return OracleConnectionSettings(
        dsn="db:1521/svc",
        transport_dsn="tx:1521/svc",
        adm_user="GOE_ADM",
        adm_password="adm-secret",
        app_user="GOE_APP",
        app_password="app-secret",
    )


@pytest.fixture
def memory_runtime() -> Iterator[runtime.ObservabilityRuntime]:
    """Configure an in-memory observability runtime with SQLCommenter enabled."""
    obs_settings = ObservabilitySettings(enabled=True, exporter="memory", sqlcommenter=True)
    active = runtime.configure_observability(obs_settings, set_global=False)
    yield active
    runtime.shutdown_observability()


def test_settings_repr_hides_passwords(settings: OracleConnectionSettings) -> None:
    """Passwords never appear in repr(OracleConnectionSettings)."""
    rendered = repr(settings)
    assert "secret" not in rendered
    assert "GOE_ADM" in rendered
    assert "GOE_APP" in rendered


def test_settings_from_options_reads_connection_attributes() -> None:
    """OracleConnectionSettings.from_options reads the canonical offload.env attributes."""
    derived = OracleConnectionSettings.from_options(build_mock_options(FAKE_ORACLE_ENV))
    assert derived.dsn == "hostname:1521/service"
    assert derived.transport_dsn == "hostname:1521/service"
    assert derived.adm_user == "a"
    assert derived.app_user == "a"
    assert derived.use_wallet is False
    assert derived.thick_mode is False


def test_pool_parameters_for_password_authentication(settings: OracleConnectionSettings) -> None:
    """Admin and application pools configure FORCEGET, ping interval, and distinct credentials."""
    registry = OracleDatabaseRegistry(settings)
    adm = registry.adm_config.connection_config
    assert adm["dsn"] == "db:1521/svc"
    assert adm["user"] == "GOE_ADM"
    assert adm["password"] == "adm-secret"
    assert adm["min"] == 0
    assert adm["max"] == POOL_MAX_SESSIONS
    assert adm["getmode"] == oracledb.POOL_GETMODE_FORCEGET
    assert adm["ping_interval"] == POOL_PING_INTERVAL_SECONDS
    assert "thick_mode" not in adm
    assert registry.app_config.connection_config["dsn"] == "tx:1521/svc"
    assert registry.app_config.connection_config["user"] == "GOE_APP"


def test_pool_parameters_for_wallet_and_thick_mode() -> None:
    """Wallet and Thick mode set externalauth, homogeneous=False, and thick_mode=True without user/password."""
    wallet_settings = OracleConnectionSettings(
        dsn="db:1521/svc",
        transport_dsn="tx:1521/svc",
        use_wallet=True,
        thick_mode=True,
    )
    registry = OracleDatabaseRegistry(wallet_settings)
    for config in (registry.adm_config, registry.app_config):
        params = config.connection_config
        assert params["externalauth"] is True
        assert params["homogeneous"] is False
        assert "user" not in params
        assert "password" not in params
        assert params["thick_mode"] is True


def test_session_tracing_only_on_admin_pool(settings: OracleConnectionSettings) -> None:
    """Session tracing is enabled on the admin pool and disabled on the application pool."""
    registry = OracleDatabaseRegistry(settings)
    assert registry.adm_config.driver_features["enable_session_tracing"] is True
    assert registry.app_config.driver_features.get("enable_session_tracing", False) is False
    assert registry.adm_config.statement_config.enable_sqlcommenter is False
    assert registry.app_config.statement_config.enable_sqlcommenter is False
    assert registry.adm_config.driver_features["fetch_lobs"] is False
    assert registry.app_config.driver_features["fetch_lobs"] is False


def test_initialize_session_sets_tracefile_identifier_once() -> None:
    """The pool session callback sets TRACEFILE_IDENTIFIER and closes its cursor."""
    conn = MagicMock()
    OracleDatabaseRegistry.initialize_session(conn, None)
    conn.cursor.return_value.execute.assert_called_once_with('ALTER SESSION SET TRACEFILE_IDENTIFIER = "GOE"')
    conn.cursor.return_value.close.assert_called_once_with()


def test_drivers_share_pool_statement_cache(settings: OracleConnectionSettings) -> None:
    """Every driver built by driver_for shares the pool StatementCacheHolder."""
    registry = OracleDatabaseRegistry(settings)
    d1 = registry.driver_for(MagicMock())
    d2 = registry.driver_for(MagicMock())
    holder = registry.adm_config.driver_features["_statement_cache_holder"]
    assert d1._cache_holder is holder
    assert d2._cache_holder is holder


def test_adm_session_scopes_module_and_action(settings: OracleConnectionSettings) -> None:
    """adm_session scopes SQLCommenterContext to GOE and the caller action and releases the connection."""
    registry = OracleDatabaseRegistry(settings)
    pool = FakePool()
    registry.adm_config.connection_instance = pool
    holder = registry.adm_config.driver_features["_statement_cache_holder"]
    with registry.adm_session(action="get_columns") as driver:
        assert SQLCommenterContext.get() == {"module": "GOE", "action": "get_columns"}
        assert driver._cache_holder is holder
    assert len(pool.released) == 1


def test_app_transport_session_keeps_module_without_observability(settings: OracleConnectionSettings) -> None:
    """Transport sessions set module and action without writing trace attributes when observability is off."""
    runtime.shutdown_observability()
    registry = OracleDatabaseRegistry(settings)
    pool = FakePool()
    registry.app_config.connection_instance = pool
    with registry.app_transport_session("GOE", "A1B2C3_sales") as conn:
        assert conn.module == "GOE"
        assert conn.action == "A1B2C3_sales"
        assert "client_identifier" not in vars(conn)
    assert pool.released == [conn]


def test_app_transport_session_adds_trace_identity(
    settings: OracleConnectionSettings,
    memory_runtime: runtime.ObservabilityRuntime,
) -> None:
    """Transport sessions add client_identifier and econtext_id when observability is enabled, and drop isolated sessions."""
    del memory_runtime
    registry = OracleDatabaseRegistry(settings)
    pool = FakePool()
    registry.app_config.connection_instance = pool
    with (
        traced_command("OFFLOAD", "2f1b7c1e-0000-4000-8000-000000000040"),
        registry.app_transport_session("GOE", "A1B2C3_sales", isolate_session=True) as conn,
    ):
        assert conn.module == "GOE"
        assert conn.action == "A1B2C3_sales"
        assert conn.client_identifier == "2f1b7c1e-0000-4000-8000-000000000040"
        assert conn.econtext_id.startswith("00-")
    assert pool.dropped == [conn]
    assert pool.released == []


def test_proxy_ddl_session_uses_admin_password(
    settings: OracleConnectionSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proxy DDL sessions authenticate as adm_user[proxy_schema] with the admin password."""
    recorded: dict[str, Any] = {}
    proxy_conn = MagicMock()

    def fake_connect(**kwargs: Any) -> MagicMock:
        recorded.update(kwargs)
        return proxy_conn

    monkeypatch.setattr(registry_module.oracledb, "connect", fake_connect)
    registry = OracleDatabaseRegistry(settings)
    with registry.proxy_ddl_session("SH_H", action="AddColumn") as driver:
        assert recorded == {"user": "GOE_ADM[SH_H]", "password": "adm-secret", "dsn": "db:1521/svc"}
        assert driver.connection is proxy_conn
        proxy_conn.cursor.return_value.execute.assert_called_once_with('ALTER SESSION SET TRACEFILE_IDENTIFIER = "GOE"')
    proxy_conn.close.assert_called_once_with()


def test_proxy_ddl_session_with_wallet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wallet proxy DDL sessions authenticate as [proxy_schema] without a password."""
    recorded: dict[str, Any] = {}
    proxy_conn = MagicMock()

    def fake_connect(**kwargs: Any) -> MagicMock:
        recorded.update(kwargs)
        return proxy_conn

    monkeypatch.setattr(registry_module.oracledb, "connect", fake_connect)
    wallet_settings = OracleConnectionSettings(dsn="db:1521/svc", transport_dsn="tx:1521/svc", use_wallet=True)
    registry = OracleDatabaseRegistry(wallet_settings)
    with registry.proxy_ddl_session("SH_H", action="AddColumn"):
        assert recorded == {"user": "[SH_H]", "dsn": "db:1521/svc"}
    proxy_conn.close.assert_called_once_with()


def test_server_version_is_cached(settings: OracleConnectionSettings) -> None:
    """server_version acquires a pooled connection once and caches the version string."""
    registry = OracleDatabaseRegistry(settings)
    pool = FakePool(version="19.3.0.0.0")
    registry.adm_config.connection_instance = pool
    assert registry.server_version() == "19.3.0.0.0"
    assert registry.server_version() == "19.3.0.0.0"
    assert len(pool.acquired) == 1
    assert len(pool.released) == 1


def test_for_options_returns_one_registry_per_settings() -> None:
    """for_options caches one registry per connection settings until close_all is called."""
    opts = build_mock_options(FAKE_ORACLE_ENV)
    first = OracleDatabaseRegistry.for_options(opts)
    second = OracleDatabaseRegistry.for_options(opts)
    assert first is second
    OracleDatabaseRegistry.close_all()
    third = OracleDatabaseRegistry.for_options(opts)
    assert third is not first


def test_adm_async_session_scopes_module_and_action(settings: OracleConnectionSettings) -> None:
    """adm_async_session scopes SQLCommenterContext and yields an OracleAsyncDriver."""
    registry = OracleDatabaseRegistry(settings)
    registry.adm_async_config.connection_instance = FakeAsyncPool()

    async def exercise() -> tuple[dict[str, str], str]:
        async with registry.adm_async_session(action="get_schema_tables") as driver:
            return SQLCommenterContext.get(), type(driver).__name__

    ctx, driver_type = asyncio.run(exercise())
    assert ctx == {"module": "GOE", "action": "get_schema_tables"}
    assert driver_type == "OracleAsyncDriver"


def test_adm_async_config_rejects_thick_mode() -> None:
    """adm_async_config raises OracleRegistryError when Thick mode is enabled."""
    thick_settings = OracleConnectionSettings(dsn="db:1521/svc", transport_dsn="tx:1521/svc", thick_mode=True)
    registry = OracleDatabaseRegistry(thick_settings)
    with pytest.raises(OracleRegistryError, match="Thin mode"):
        _ = registry.adm_async_config
