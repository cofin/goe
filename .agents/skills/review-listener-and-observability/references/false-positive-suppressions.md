# False-Positive Suppressions: Litestar Listener, Vertebra Runtime, Durable Jobs, MCP & OpenTelemetry (`FP-LST`)

## `FP-LST-01`: DO NOT FLAG `'httpx': ('httpx2', None)` in `src/goe/cli/commands/listener.py` `_LAZY_IMPORTS`

- **Directive**: DO NOT FLAG `'httpx': ('httpx2', None)` in `src/goe/cli/commands/listener.py` `_LAZY_IMPORTS`.
- **Rationale**: Aliasing `httpx` to `httpx2` in `_LAZY_IMPORTS` preserves compatibility with unit tests that patch `goe.cli.commands.listener.httpx.get` while using `httpx2` at runtime.

## `FP-LST-02`: DO NOT FLAG direct HTTP REST `POST /api/orchestration/*` endpoints for omitting `ConfirmationGate` tokens

- **Directive**: DO NOT FLAG direct HTTP REST `POST /api/orchestration/*` endpoints for omitting `ConfirmationGate` tokens.
- **Rationale**: `ConfirmationGate` (`MCPInputRequiredResult` + `confirmation_token`) is intentionally scoped to MCP tool invocations to guard AI agent mutations; direct REST API callers authenticate with `x-goe-console-key` without interactive MRTR challenges.

## `FP-LST-03`: DO NOT FLAG ephemeral HMAC secret generation in `ConfirmationGate` when `OFFLOAD_LISTENER_SHARED_TOKEN` is unset

- **Directive**: DO NOT FLAG ephemeral HMAC secret generation in `ConfirmationGate` when `OFFLOAD_LISTENER_SHARED_TOKEN` is unset.
- **Rationale**: In local unauthenticated mode (`OFFLOAD_LISTENER_SHARED_TOKEN` unset), `ConfirmationGate` generates a per-process `secrets.token_hex(32)` signing key so MCP confirmation tokens still cryptographically bind the tool name and canonical arguments.

## `FP-LST-04`: DO NOT FLAG `OracleJobStore` using `cursor.fetchmany(limit)` after `SELECT ... FOR UPDATE SKIP LOCKED`

- **Directive**: DO NOT FLAG `OracleJobStore` using `cursor.fetchmany(limit)` after `SELECT ... FOR UPDATE SKIP LOCKED`.
- **Rationale**: Oracle does not allow combining `FETCH FIRST :limit ROWS ONLY` with `FOR UPDATE SKIP LOCKED` in all supported versions; bounding row fetches via `cursor.fetchmany(limit)` on the open cursor is the required Oracle pattern.
