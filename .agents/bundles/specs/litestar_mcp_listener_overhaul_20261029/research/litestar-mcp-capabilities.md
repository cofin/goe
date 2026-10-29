---
type: Research
research_id: "litestar-mcp-capabilities"
title: Litestar-MCP 0.16.0 Stateless Protocol & Native Integration Reference
description: Verified API contracts, route discovery branching, DI constraints, security integration, MRTR input gating, skills/prompts/tasks extensions, and stdio/bridge transports in litestar-mcp 0.16.0.
scope: integration
tags: [litestar-mcp, litestar-security, mcp, protocol]
status: stable
state: promoted
promoted_to: litestar_mcp_listener_overhaul_20261029
created_at: "2026-10-29T17:40:00Z"
updated_at: "2026-10-29T18:55:00Z"
---

# `litestar-mcp` `0.16.0` Native Integration Findings

## Scope and Primary Sources

Verified against resolved `uv.lock` versions (`litestar==2.25.0`, `litestar-mcp==0.16.0`, `litestar-security==0.6.0`, `litestar-autowire==0.2.0`, `msgspec==0.22.0`, `httpx2==2.16.0`) and installed `litestar-mcp` / `litestar-security` reference documentation:

- `litestar-mcp` `SKILL.md` and `references/stateless-protocol.md`
- `litestar-security` `SKILL.md` (`SecurityPlugin`, `SecurityConfig`, `AUTH_POLICY_OPT_KEY`, `required`, `public`)
- `litestar-mcp` `0.16.0` package modules (`litestar_mcp`, `litestar_mcp.mcp.plugin`, `litestar_mcp.mcp.service`, `litestar_mcp.mcp.config`, `litestar_mcp.mcp.skills`, `litestar_mcp.mcp.prompt_controller`, `litestar_mcp.mcp.stdio`, `litestar_mcp.mcp.bridge`)

## Verified Capabilities & Constraints

### 1. Stateless Protocol `2026-07-28` (`POST /mcp`) (`F-MCP-01`)

- Transport is strictly request-scoped `POST /mcp` (plus `OPTIONS`). Legacy `initialize`, `notifications/initialized`, `Mcp-Session-Id`, `GET /mcp`, `DELETE /mcp`, `ping`, and `/.well-known/mcp-server.json` are absent.
- Every JSON-RPC call supplies `params._meta["io.modelcontextprotocol/protocolVersion"] = "2026-07-28"` and `params._meta["io.modelcontextprotocol/clientCapabilities"]`, matched by HTTP headers `MCP-Protocol-Version: 2026-07-28`, `Mcp-Method: <method>`, and `Mcp-Name: <name_or_uri>` on named operations (`tools/call`, `resources/read`, `prompts/get`, `skills/get`, `resources/directory/read`, `tasks/*`).
- Capability negotiation occurs via `server/discover`. List operations (`tools/list`, `resources/list`, `resources/templates/list`, `prompts/list`, `skills/list`, `resources/directory/read`) use opaque cursor pagination (`MCPConfig.list_page_size`).

### 2. Exact `MCPConfig` Instance DI Requirement (`F-MCP-02`)

- `LitestarMCP.on_app_init` registers `"config": Provide(provide_mcp_config, sync_to_thread=False)` on the `/mcp` router, where `MCPController` injects `config: NamedDependency[MCPConfig]`.
- Because `MCPConfig` is a `@dataclass` validated via `msgspec.convert(..., strict=False)` (which checks `type(val) is MCPConfig`), `build_mcp_config()` MUST return an exact `MCPConfig` instance (`type(cfg) is MCPConfig`), never a subclass.

### 3. Route Discovery Branching (`@mcp_tool` vs `mcp_resource` Handlers) (`F-MCP-03`)

- In `litestar_mcp.mcp.plugin` (`_discover_mcp_routes`), route registration branches with `if metadata: self._register_from_metadata(...) elif handler.opt: self._register_from_opt(...)`, and `MetadataRegistry.set()` stores a single entry per function qualname. Meanwhile, `MCPHandlerService.tools_list` reads `annotations`, `output_schema`, `task_support`, and `task_input_before_start` exclusively from `MetadataRegistry` (`@mcp_tool`), not from `handler.opt`.
- Consequently, putting `@mcp_tool(...)` and `mcp_resource="..."` on the same controller method causes `_discover_mcp_routes` to skip `_register_from_opt` completely (registering zero `goe://` resources/templates).
- Clean pattern: decorate public REST controller methods with `@mcp_tool(..., annotations=..., task_support=...)`, and mount a dedicated internal `GOEResourcesController(SecureController)` (`path = "/api/_mcp/resources"`, `include_in_schema = False`, `auth = required("console-key")`) where every method carries a Litestar `@get("/...")` HTTP route decorator (stacking `@get("/...")` above `@mcp_resource(uri="goe://...", name="...", description="...", mime_type="application/json")` for static `goe://` URIs and `@get("/...", mcp_resource="<name>", mcp_resource_template="goe://...", mcp_resource_description="...", mcp_resource_mime_type="application/json")` for templated `goe://` URIs, because `Controller.get_route_handlers()` ignores methods lacking an HTTP route decorator) delegating to the same async service/cache helpers.
- `LitestarMCP` always publishes `litestar://openapi` (`application/json`) in `resources/list` while keeping `/mcp` hidden from OpenAPI by default (`include_in_schema=False`).
- Returning `MCPResourceLink(name=..., uri=..., mime_type=..., size=...)` from a tool emits a lightweight `resource_link` content block that MCP clients dereference lazily via `resources/read`.

### 4. Handler-Level MRTR (`MCPInputRequiredResult`), `RuntimeError` Context Guard, and `task_input_before_start=True` (`F-MCP-04`)

- `get_mcp_request_context()` returns the active `MCPRequestContext` (`client_id`, `owner_id`, `progress_token`, `input_responses`, `request_state`, `report_progress(...)`) during `/mcp` dispatch and raises **`RuntimeError`** when invoked from a direct HTTP REST call outside `/mcp`.
- Guarding with `try: ctx = get_mcp_request_context() except RuntimeError: ctx = None` allows mutating handlers (`execute_offload`, `apply_schema_sync`) to return typed `FrozenBaseStruct` DTOs (`schemas.CommandScheduled`, `SchemaSyncExecutionResult`) directly on ordinary HTTP `POST` calls (`ctx is None`) without requiring confirmation tokens or serializing `MCPToolResult` wrappers, while enforcing `ConfirmationGate.require_mcp_confirmation(...)` when `ctx is not None`.
- On Round 1 over `/mcp` without confirmation, returning `MCPInputRequiredResult(input_requests={"confirm": {...}, "confirmation_token": {...}}, request_state="...", meta={...})` on a tool marked `task_input_before_start=True` returns synchronously before creating a `TaskRecord`. On Round 2, the client issues a second `tools/call` carrying `requestState` and `inputResponses={"confirm": True}` (or supplies a preview-issued signed `confirmation_token`).
- `MCPConfig.before_tool_call` and `MCPConfig.after_tool_call` swallow callback exceptions by design and must be reserved strictly for observability (OpenTelemetry spans and metrics).

### 5. Authentication Ownership Across `/mcp` & `PromptController` (`F-MCP-05`)

- `MCPConfig(route_opt={AUTH_POLICY_OPT_KEY: required("console-key")})` attaches the `litestar-security` authentication policy directly to the `/mcp` router.
- `PromptController` subclasses inherit from `litestar.Controller` rather than `SecureController`. When `SecurityPlugin` registers a named mechanism (`"console-key"`), `PromptController` subclasses must declare `opt = {AUTH_POLICY_OPT_KEY: required("console-key")}` as a plain class attribute (without `ClassVar`, matching `litestar.Controller.opt` typing in `mypy`).
- `LitestarMCP` in `0.16.0` recursively discovers `PromptController` subclasses mounted inside nested `Router` trees, including controllers auto-discovered by `AutowirePlugin`.

### 6. `MCPSkillsConfig`, `MCPTaskConfig`, and Stdio / Bridge Auth Headers (`F-MCP-06`)

- `MCPSkillsConfig(paths=[...], directory_read=True)` indexes `<path>/<skill-name>/SKILL.md` directories (requiring regular files and YAML frontmatter `name` matching the directory name plus non-empty `description`) and serves `skills/list`, `skills/get`, `resources/directory/read`, and `skill://<name>/<rel_path>` reads with SHA-256 integrity checks.
- `MCPTaskConfig` enables `io.modelcontextprotocol/tasks` (`tasks/get`, `tasks/result`, `tasks/list`, `tasks/cancel`) backed by a Litestar `Store` (`MCPTaskStore`), paired with `task_support="optional"` on long-running `@mcp_tool` declarations (`validate_table`, `apply_schema_sync`, `generate_status_report`, `execute_offload`). Note that `tasks/cancel` cancels in-flight `MCPTaskStore` tool runners by `taskId`, whereas durable background rows in `GOE_LISTENER_JOBS` are cancelled cooperatively via `cancel_offload_job` (`POST /api/orchestration/executions/{execution_id}/cancel/`).
- In `litestar_mcp.mcp.stdio` (`run_stdio` / `run_stdio_async`) and `litestar_mcp.mcp.bridge` (`run_stdio_streamable_http_bridge`), auth header forwarding defaults to `header_name="Authorization"` and `token_prefix="Bearer "`. Because `ConsoleKeyAuthenticator` compares `x-goe-console-key` directly via `secrets.compare_digest` without a `"Bearer "` prefix, both `goe listener mcp stdio` and `goe listener mcp bridge` must pass `header_name="x-goe-console-key"` and `token_prefix=""` whenever `OFFLOAD_LISTENER_SHARED_TOKEN` is configured.

## Confidence & Limitations

- **Confidence**: High — verified against resolved `0.16.0` package contracts and local `litestar-mcp` / `litestar-security` reference manuals.
- **Limitations**: `LitestarA2A` (`litestar-mcp[a2a]`) requires `a2a-sdk` and is intentionally excluded per user scope decision.
