# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Pooled SQLSpec Oracle configurations for the GOE admin, application, and Listener roles.

``OracleDatabaseRegistry`` owns one ``OracleSyncConfig`` per role and one ``OracleAsyncConfig`` for Listener admin
reads. Drivers are always built with their pool's ``statement_config`` and ``driver_features`` so every driver of a
pool shares one SQLSpec ``StatementCacheHolder`` and one observability runtime. The pool ``session_callback`` sets
``TRACEFILE_IDENTIFIER`` once per physical connection. Admin drivers use SQLSpec session tracing; transport sessions
keep the caller's ``MODULE`` and ``ACTION`` because ``LOG_SQL_STATS_QUERY_TEXT`` finds transport SQL in ``gv$sql``
by those values.
"""

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, ClassVar, Final, Literal

import oracledb
from sqlspec.adapters.oracledb import OracleAsyncConfig, OracleAsyncDriver, OracleSyncConfig, OracleSyncDriver
from sqlspec.adapters.oracledb.core import apply_oracle_session_trace_attributes
from sqlspec.core.sqlcommenter import SQLCommenterContext

from goe.exceptions import GOEError
from goe.observability.context import get_current_trace_context
from goe.observability.db import build_db_observability_config
from goe.observability.runtime import get_observability_runtime
from goe.offload.frontend_api import FRONTEND_TRACE_ID, FRONTEND_TRACE_MODULE
from goe.typing import FrozenBaseStruct

__all__ = (
    "ADM_DRIVER_FEATURES",
    "APP_DRIVER_FEATURES",
    "POOL_MAX_SESSIONS",
    "POOL_PING_INTERVAL_SECONDS",
    "TRACEFILE_IDENTIFIER_SQL",
    "OracleConnectionSettings",
    "OracleDatabaseRegistry",
    "OracleRegistryError",
    "OracleRole",
)

type OracleRole = Literal["adm", "app"]

POOL_MAX_SESSIONS: Final = 8
POOL_PING_INTERVAL_SECONDS: Final = 60
TRACEFILE_IDENTIFIER_SQL: Final = f'ALTER SESSION SET TRACEFILE_IDENTIFIER = "{FRONTEND_TRACE_ID}"'
ADM_DRIVER_FEATURES: Final[dict[str, Any]] = {
    "enable_session_tracing": True,
    "enable_lowercase_column_names": True,
    "fetch_lobs": False,
}
APP_DRIVER_FEATURES: Final[dict[str, Any]] = {"enable_lowercase_column_names": True, "fetch_lobs": False}


class OracleRegistryError(GOEError):
    """Raised when a registry session cannot be provided for the configured connection mode."""


class OracleConnectionSettings(FrozenBaseStruct, frozen=True, kw_only=True):
    """Oracle connection inputs for one deployment; hashable process cache key."""

    dsn: str
    transport_dsn: str
    adm_user: str | None = None
    adm_password: str | None = None
    app_user: str | None = None
    app_password: str | None = None
    use_wallet: bool = False
    thick_mode: bool = False

    def __repr__(self) -> str:
        """Return a representation without passwords."""
        return (
            f"OracleConnectionSettings(dsn={self.dsn!r}, transport_dsn={self.transport_dsn!r}, "
            f"adm_user={self.adm_user!r}, app_user={self.app_user!r}, use_wallet={self.use_wallet!r}, "
            f"thick_mode={self.thick_mode!r})"
        )

    @classmethod
    def from_options(cls, connection_options: Any) -> "OracleConnectionSettings":
        """Build settings from the GOE settings object (``rdbms_dsn``, ``ora_adm_*``, ``rdbms_app_*``, wallet, Thick)."""
        return cls(
            dsn=connection_options.rdbms_dsn,
            transport_dsn=connection_options.offload_transport_dsn or connection_options.rdbms_dsn,
            adm_user=connection_options.ora_adm_user,
            adm_password=connection_options.ora_adm_pass,
            app_user=connection_options.rdbms_app_user,
            app_password=connection_options.rdbms_app_pass,
            use_wallet=bool(connection_options.use_oracle_wallet),
            thick_mode=bool(connection_options.oracledb_thick_mode),
        )


class OracleDatabaseRegistry:
    """Process-cached SQLSpec connection pool registry for Oracle admin, application, and Listener roles."""

    _instances: ClassVar[dict[OracleConnectionSettings, "OracleDatabaseRegistry"]] = {}
    _instances_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, settings: OracleConnectionSettings) -> None:
        """Initialize role pool configurations without opening database connections."""
        self._settings = settings
        self._observability_config = build_db_observability_config()
        self._adm_config = self._sync_config("adm")
        self._app_config = self._sync_config("app")
        self._adm_async_config: OracleAsyncConfig | None = None
        self._server_version: str | None = None
        self._lock = threading.Lock()

    @property
    def settings(self) -> OracleConnectionSettings:
        """Return the immutable connection settings for this registry."""
        return self._settings

    @property
    def adm_config(self) -> OracleSyncConfig:
        """Return the synchronous pool configuration for the admin/repository role."""
        return self._adm_config

    @property
    def app_config(self) -> OracleSyncConfig:
        """Return the synchronous pool configuration for the application/transport role."""
        return self._app_config

    @property
    def adm_async_config(self) -> OracleAsyncConfig:
        """Return the lazily constructed Thin-mode async pool configuration for Listener reads."""
        if self._settings.thick_mode or self._settings.use_wallet:
            raise OracleRegistryError(
                "Listener async Oracle sessions require python-oracledb Thin mode without Oracle Wallet external authentication"
            )
        if self._adm_async_config is None:
            with self._lock:
                if self._adm_async_config is None:
                    self._adm_async_config = OracleAsyncConfig(
                        connection_config=self._async_pool_parameters(),
                        driver_features=dict(ADM_DRIVER_FEATURES),
                        observability_config=self._observability_config,
                    )
        return self._adm_async_config

    @classmethod
    def for_options(cls, connection_options: Any) -> "OracleDatabaseRegistry":
        """Return the cached registry for ``connection_options``, creating it on first use."""
        settings = OracleConnectionSettings.from_options(connection_options)
        with cls._instances_lock:
            registry = cls._instances.get(settings)
            if registry is None:
                registry = cls(settings)
                cls._instances[settings] = registry
            return registry

    @classmethod
    def close_all(cls) -> None:
        """Close and evict all cached registries."""
        with cls._instances_lock:
            registries = list(cls._instances.values())
            cls._instances.clear()
        for registry in registries:
            registry.close()

    @staticmethod
    def initialize_session(connection: Any, requested_tag: str | None = None) -> None:
        """Configure a newly created physical connection in the synchronous pool."""
        del requested_tag
        cursor = connection.cursor()
        try:
            cursor.execute(TRACEFILE_IDENTIFIER_SQL)
        finally:
            cursor.close()

    @staticmethod
    async def initialize_async_session(connection: Any, requested_tag: str | None = None) -> None:
        """Configure a newly created physical connection in the asynchronous pool."""
        del requested_tag
        cursor = connection.cursor()
        try:
            await cursor.execute(TRACEFILE_IDENTIFIER_SQL)
        finally:
            cursor.close()

    def driver_for(self, connection: Any, role: OracleRole = "adm") -> OracleSyncDriver:
        """Build an OracleSyncDriver sharing the role pool's statement cache and observability runtime."""
        config = self._config(role)
        driver = OracleSyncDriver(
            connection=connection,
            statement_config=config.statement_config,
            driver_features=config.driver_features,
        )
        driver.attach_observability(config.get_observability_runtime())
        return driver

    @contextmanager
    def adm_session(self, *, action: str) -> Iterator[OracleSyncDriver]:
        """Yield a pooled synchronous admin driver scoped to ``action``."""
        with (
            SQLCommenterContext.scope({"module": FRONTEND_TRACE_MODULE, "action": action}),
            self._adm_config.provide_session() as driver,
        ):
            yield driver

    @asynccontextmanager
    async def adm_async_session(self, *, action: str) -> AsyncIterator[OracleAsyncDriver]:
        """Yield a pooled asynchronous admin driver scoped to ``action``."""
        with SQLCommenterContext.scope({"module": FRONTEND_TRACE_MODULE, "action": action}):
            async with self.adm_async_config.provide_session() as driver:
                yield driver

    def lease(self, role: OracleRole, *, action: str) -> Any:
        """Acquire a connection from the role pool and tag its session trace attributes."""
        connection = self._config(role).provide_pool().acquire()
        self._apply_trace_attributes(connection, module=FRONTEND_TRACE_MODULE, action=action)
        return connection

    def release(self, role: OracleRole, connection: Any, *, discard: bool = False) -> None:
        """Return a leased connection to the role pool, or drop it when ``discard`` is True."""
        pool = self._config(role).provide_pool()
        if discard:
            pool.drop(connection)
        else:
            pool.release(connection)

    @contextmanager
    def app_transport_session(self, module: str, action: str, *, isolate_session: bool = False) -> Iterator[Any]:
        """Acquire a transport connection, apply module/action and trace identity, and release or drop on exit."""
        pool = self._app_config.provide_pool()
        connection = pool.acquire()
        try:
            self._apply_trace_attributes(connection, module=module, action=action)
            yield connection
        finally:
            if isolate_session:
                pool.drop(connection)
            else:
                pool.release(connection)

    def connect_proxy(self, proxy_schema: str, *, action: str) -> Any:
        """Open a standalone proxy connection for ``proxy_schema`` using admin credentials or Wallet."""
        self._ensure_client_mode()
        if self._settings.use_wallet:
            connection = oracledb.connect(user=f"[{proxy_schema}]", dsn=self._settings.dsn)
        else:
            connection = oracledb.connect(
                user=f"{self._settings.adm_user}[{proxy_schema}]",
                password=self._settings.adm_password,
                dsn=self._settings.dsn,
            )
        self.initialize_session(connection)
        self._apply_trace_attributes(connection, module=FRONTEND_TRACE_MODULE, action=action)
        return connection

    @contextmanager
    def proxy_ddl_session(self, proxy_schema: str, *, action: str) -> Iterator[OracleSyncDriver]:
        """Yield a standalone proxy driver for ``proxy_schema`` and close the connection on exit."""
        connection = self.connect_proxy(proxy_schema, action=action)
        try:
            with SQLCommenterContext.scope({"module": FRONTEND_TRACE_MODULE, "action": action}):
                yield self.driver_for(connection)
        finally:
            connection.close()

    def server_version(self) -> str:
        """Return the Oracle database server version string, cached once per registry."""
        if self._server_version is None:
            with self._lock:
                if self._server_version is None:
                    pool = self._adm_config.provide_pool()
                    connection = pool.acquire()
                    try:
                        self._server_version = str(connection.version)
                    finally:
                        pool.release(connection)
        return self._server_version

    def close(self) -> None:
        """Close any initialized synchronous connection pools."""
        for config in (self._adm_config, self._app_config):
            if config.connection_instance is not None:
                config.close_pool()

    async def aclose(self) -> None:
        """Close the asynchronous connection pool when initialized."""
        if self._adm_async_config is not None and self._adm_async_config.connection_instance is not None:
            await self._adm_async_config.close_pool()

    def _config(self, role: OracleRole) -> OracleSyncConfig:
        """Return the synchronous pool configuration for ``role``."""
        return self._adm_config if role == "adm" else self._app_config

    def _sync_config(self, role: OracleRole) -> OracleSyncConfig:
        """Build the synchronous pool configuration for ``role``."""
        features = ADM_DRIVER_FEATURES if role == "adm" else APP_DRIVER_FEATURES
        return OracleSyncConfig(
            connection_config=self._pool_parameters(role),
            driver_features=dict(features),
            observability_config=self._observability_config,
        )

    def _pool_parameters(self, role: OracleRole) -> dict[str, Any]:
        """Return python-oracledb pool parameters for ``role``."""
        settings = self._settings
        if role == "adm":
            user, password, dsn = settings.adm_user, settings.adm_password, settings.dsn
        else:
            user, password, dsn = settings.app_user, settings.app_password, settings.transport_dsn
        parameters: dict[str, Any] = {
            "dsn": dsn,
            "min": 0,
            "max": POOL_MAX_SESSIONS,
            "increment": 1,
            "getmode": oracledb.POOL_GETMODE_FORCEGET,
            "ping_interval": POOL_PING_INTERVAL_SECONDS,
            "session_callback": OracleDatabaseRegistry.initialize_session,
        }
        if settings.thick_mode:
            parameters["thick_mode"] = True
        if settings.use_wallet:
            parameters["externalauth"] = True
            parameters["homogeneous"] = False
        else:
            parameters["user"] = user
            parameters["password"] = password
        return parameters

    def _async_pool_parameters(self) -> dict[str, Any]:
        """Return Thin-mode async pool parameters for the admin role."""
        parameters = self._pool_parameters("adm")
        parameters.pop("thick_mode", None)
        parameters["session_callback"] = OracleDatabaseRegistry.initialize_async_session
        return parameters

    def _ensure_client_mode(self) -> None:
        """Initialize python-oracledb Thick mode on demand when configured."""
        if self._settings.thick_mode and oracledb.is_thin_mode():
            oracledb.init_oracle_client()

    @staticmethod
    def _apply_trace_attributes(connection: Any, *, module: str, action: str) -> None:
        """Set MODULE and ACTION, plus CLIENT_IDENTIFIER and ECID when observability is enabled."""
        if not get_observability_runtime().enabled:
            connection.module = module
            connection.action = action
            return
        snapshot = get_current_trace_context()
        apply_oracle_session_trace_attributes(
            connection,
            module=module,
            action=action,
            client_identifier=snapshot.execution_id or "",
            econtext_id=snapshot.traceparent or "",
        )
