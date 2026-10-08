# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Litestar Security configuration for x-goe-console-key authentication."""

import secrets
from datetime import UTC, datetime
from typing import ClassVar

from litestar.connection import ASGIConnection
from litestar.openapi.spec import SecurityScheme
from litestar_security import (
    Authenticated,
    AuthenticationEvidence,
    AuthenticationMechanism,
    AuthenticationOutcome,
    CredentialExtraction,
    CredentialSlot,
    CredentialVerifier,
    IdentityResolver,
    InvalidCredentials,
    NoCredentials,
    PresentedCredential,
    Principal,
    SecurityConfig,
)

from goe.listener.config import settings

API_KEY_HEADER = "x-goe-console-key"


class ConsoleKeySlot(CredentialSlot[str | None]):
    """Extract the x-goe-console-key header from the incoming ASGI connection."""

    name: ClassVar[str] = "header:x-goe-console-key"

    def extract(self, connection: ASGIConnection) -> CredentialExtraction[str | None]:
        """Extract the console key header or fall back to local mode when unconfigured."""
        header_bytes = API_KEY_HEADER.encode("latin-1")
        token: str | None = None
        for key, value in connection.scope.get("headers", ()):
            if key.lower() == header_bytes:
                token = value.decode("latin-1")
                break

        if settings.shared_token:
            if token is None:
                return NoCredentials()
            return PresentedCredential(token)

        return PresentedCredential(token or "local-dev")


class ConsoleKeyAuthenticator(CredentialVerifier[str | None, str]):
    """Verify the presented console key against settings.shared_token."""

    name: ClassVar[str] = "console-key"
    slot: ClassVar[str] = ConsoleKeySlot.name
    participates_by_default: ClassVar[bool] = True

    async def authenticate(
        self,
        credential: str | None,
        connection: ASGIConnection,
    ) -> AuthenticationOutcome[str]:
        """Validate the console key using constant-time digest comparison."""
        expected_token = settings.shared_token
        if expected_token:
            if not credential or not secrets.compare_digest(credential, str(expected_token)):
                return InvalidCredentials()
            claims = "console-client"
        else:
            claims = "local-anonymous"

        return Authenticated(
            claims=claims,
            evidence=AuthenticationEvidence(
                mechanism=self.name,
                slot=self.slot,
                authenticated_at=datetime.now(UTC),
            ),
        )


class ConsoleKeyIdentityResolver(IdentityResolver[str, str]):
    """Resolve authenticated claims into a Principal."""

    async def resolve(self, claims: str) -> Principal[str] | None:
        """Build a Principal from the verified claims identifier."""
        return Principal(
            id=claims,
            display_name=claims,
            user=claims,
        )


def build_security_config() -> SecurityConfig[str]:
    """Create the SecurityConfig instance for the GOE Listener application."""
    return SecurityConfig(
        slots=[ConsoleKeySlot()],
        mechanisms=[
            AuthenticationMechanism(
                authenticator=ConsoleKeyAuthenticator(),
                resolver=ConsoleKeyIdentityResolver(),
                scheme_name="ConsoleKey",
                security_scheme=SecurityScheme(
                    type="apiKey",
                    name=API_KEY_HEADER,
                    security_scheme_in="header",
                    description="GOE Console shared API key.",
                ),
            ),
        ],
        exclude=[r"^/mcp", r"^/\.well-known"],
    )
