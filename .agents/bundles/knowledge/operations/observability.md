---
type: Reference
title: OpenTelemetry Observability, Step Spans, Metrics & Log Correlation
description: Zero-cost-by-default OpenTelemetry architecture, ObservabilitySettings, ExecutionId-to-W3C context bridge, OTLP/GCP Telemetry API exporters, and structured log correlation
tags:
  - reference
  - operations
  - observability
  - opentelemetry
  - tracing
  - metrics
  - logging
---

# OpenTelemetry Observability, Step Spans, Metrics & Log Correlation

GOE provides an opt-in, zero-cost-by-default OpenTelemetry observability layer (`src/goe/observability/` and `src/goe/listener/telemetry.py`) covering CLI commands, orchestration steps, Listener HTTP/MCP/queue workers, `OracleGateway` SQLSpec queries, offload transports (Spark, Dataproc, Query Import, DuckDB), Google Cloud Storage (`GOEGcs`), and Google BigQuery.

## Zero-Cost-By-Default Architecture

- **Dependency Split (`pyproject.toml`)**:
  - `opentelemetry-api>=1.40.0` is a lightweight core dependency.
  - `opentelemetry-sdk>=1.40.0`, `opentelemetry-exporter-otlp-proto-grpc>=1.40.0`, `opentelemetry-exporter-otlp-proto-http>=1.40.0`, and `opentelemetry-instrumentation-asgi>=0.61b0` reside in the optional `otel` extra (`uv sync --extra otel`).
- **Disabled Path (`GOE_OTEL_ENABLED=false`, Default)**:
  - `ObservabilityRuntime` (`src/goe/observability/runtime.py`) returns API no-op tracers and meters without importing `opentelemetry.sdk`.
  - No background threads are started, no network sockets are opened, and Oracle session attributes (`V$SESSION.CLIENT_INFO`), SQL text, subprocess environments, Spark properties, BigQuery labels, and `.log` text output remain identical to baseline.
- **Fail-Safe Exporter Initialization**:
  - If `GOE_OTEL_ENABLED=true` is set without the `otel` extra installed or an exporter constructor raises an exception, `ObservabilityRuntime` logs a single warning and degrades gracefully to a no-op runtime without aborting the offload.

## Configuration (`ObservabilitySettings` in `src/goe/observability/config.py`)

`ObservabilitySettings.from_env_and_cli(options, env)` resolves settings with precedence `CLI flag > GOE_OTEL_* > OTEL_* > default`:

| Setting / CLI Flag | Environment Variable(s) | Default | Description |
| :--- | :--- | :--- | :--- |
| `--otel-enabled` | `GOE_OTEL_ENABLED` | `False` | Master opt-in switch for OpenTelemetry tracing, metrics, and log correlation. |
| `--otel-exporter` | `GOE_OTEL_EXPORTER`, `OTEL_TRACES_EXPORTER` | `"none"` (`"otlp"` when enabled with endpoint) | Exporter backend: `none`, `console`, `jsonl`, `otlp` / `otlp_grpc`, `otlp_http`, `gcp`, `memory`. |
| `--otel-endpoint` | `GOE_OTEL_ENDPOINT`, `OTEL_EXPORTER_OTLP_ENDPOINT` | `None` | OTLP collector endpoint URL (or `https://telemetry.googleapis.com` for `gcp`). |
| `--otel-protocol` | `GOE_OTEL_PROTOCOL`, `OTEL_EXPORTER_OTLP_PROTOCOL` | `"grpc"` | OTLP wire protocol (`grpc` or `http/protobuf`). |
| `--otel-service-name` | `GOE_OTEL_SERVICE_NAME`, `OTEL_SERVICE_NAME` | `"goe"` | OpenTelemetry `service.name` resource attribute. |
| `--log-format` | `GOE_LOG_FORMAT` | `"text"` | Primary log file format (`text` or `json`). |
| `--log-json-sidecar` | `GOE_LOG_JSON_SIDECAR` | `False` | Write a structured `<log_path>.jsonl` sidecar alongside the human-readable `.log` file. |

### Google Cloud Telemetry (OTLP) API Exporter (`exporter="gcp"`)
When `exporter="gcp"`, `src/goe/observability/_sdk.py` targets Google Cloud's OTLP endpoint (`https://telemetry.googleapis.com/v1/traces` and `/v1/metrics`) over `OTLPSpanExporter` / `OTLPMetricExporter` (`http/protobuf`), attaching an `_AdcAuthSession` authenticated via `resolve_gcp_credentials(config, component="otel")` and setting `gcp.project_id` on the OpenTelemetry `Resource` (never using deprecated `opentelemetry-exporter-gcp-*` packages).

## `ExecutionId` <-> W3C Trace Context Bridge (`src/goe/observability/context.py`)

- `bind_execution_context(execution_id, command_type=..., incoming_headers=...)` binds `ExecutionId` (`str(execution_id)`) into:
  1. Process-local `ContextVar`s (`get_current_execution_id()`, `get_current_command_type()`, `get_current_step_id()`).
  2. W3C `baggage` (`goe.execution.id`, `goe.command.type`).
  3. SQLSpec `CorrelationContext` (`CorrelationContext.context(str(execution_id))`).
- **`ExecutionContextSpanProcessor` (`src/goe/observability/_sdk.py`)**: Automatically stamps `goe.execution.id`, `goe.command.type`, and `goe.step.id` onto every span started while context is bound, including child library spans (`sqlspec.query`, ASGI spans).
- **Cross-Boundary Helpers**:
  - `inject_carrier(carrier)` / `extract_carrier(carrier)`: W3C `traceparent` + `baggage` propagation across HTTP headers and queue payloads.
  - `build_subprocess_trace_env(base_env)`: Injects `TRACEPARENT`, `TRACESTATE`, and `GOE_EXECUTION_ID` into child subprocess environments when OpenTelemetry is active.
  - `submit_with_context(executor, fn, *args, **kwargs)`: Copies `contextvars.copy_context()` and OpenTelemetry context into `ThreadPoolExecutor` worker threads (used by `OffloadTransportDuckDB`).

## Canonical Span Hierarchy & Metric Catalog

### Span Hierarchy
```text
goe.command.offload (INTERNAL, OrchestrationRunner.offload)
├── goe.step.<step_id> (INTERNAL, OffloadMessages.offload_step)
│   ├── sqlspec.query (CLIENT, OracleGateway dictionary/repository SQL + SQLCommenter)
│   ├── goe.chunk (INTERNAL, _offload_chunk)
│   │   └── goe.transport.<method> (CLIENT, OffloadTransport.transport)
│   │       ├── goe.os_cmd.<exe> (CLIENT, run_os_cmd subprocess with TRACEPARENT)
│   │       └── goe.transport.duckdb.batch (CLIENT, OffloadTransportDuckDB._run_batch)
│   ├── goe.storage.gs.<op> (CLIENT, GOEGcs @traced_storage_call)
│   └── goe.backend.bigquery.<op> (CLIENT, BackendBigQueryApi DDL/DML/query/load_table_from_uri)
```

### Canonical Metric Instruments (`GOEMetrics` in `src/goe/observability/metrics.py`)
1. `goe.commands.total` (Counter, `{command}`): Total GOE commands executed.
2. `goe.commands.duration` (Histogram, `s`): End-to-end command duration.
3. `goe.steps.duration` (Histogram, `s`): Individual `offload_step` execution duration.
4. `goe.transport.rows_fetched` (Counter, `{row}`): Rows extracted by offload transport.
5. `goe.transport.bytes_staged` (Counter, `By`): Bytes staged by offload transport.
6. `goe.transport.duration` (Histogram, `s`): Offload transport duration.
7. `goe.storage.bytes_transferred` (Counter, `By`): Cloud storage bytes read/written.
8. `goe.bigquery.slot_millis` (Counter, `ms`) & `goe.bigquery.bytes_billed` (Counter, `By`): BigQuery job resource consumption.

## Repository, Log & Listener Correlation

- **`OFFLOAD_REPO` Persistence**: `OracleOrchestrationRepoClient.start_command()` injects `_trace_id` and `_span_id` into `COMMAND_PARAMETERS` JSON, and `end_command_step()` injects `_trace_id` and `_span_id` into `STEP_DETAILS` JSON when an active recording span exists.
- **Structured Log Correlation (`src/goe/observability/log_correlation.py`, `src/goe/util/goe_log_fh.py`)**:
  - `GOELogFileHandle` keeps stdout human-readable (`text`) at all times, formats the `.log` file as JSON lines when `GOE_LOG_FORMAT=json`, or writes a parallel `<log_path>.jsonl` sidecar when `GOE_LOG_JSON_SIDECAR=true` (emitting `timestamp`, `severity`, `message`, `execution_id`, `command_type`, `step`, `trace_id`, `span_id`, `logging.googleapis.com/trace`, and `logging.googleapis.com/spanId`).
  - `install_log_record_correlation()` installs a `logging.setLogRecordFactory` hook stamping `trace_id`, `span_id`, `execution_id`, and `step_id` onto standard Python `LogRecord` instances.
- **Listener, Queue & MCP Telemetry (`src/goe/listener/telemetry.py`)**:
  - Lazily binds `OpenTelemetryConfig` / `OpenTelemetryPlugin` from `litestar.plugins.opentelemetry` when `GOE_OTEL_ENABLED=true`.
  - Configures `litestar-queues` `QueueConfig(observability=ObservabilityConfig(enable_otel=True))` and propagates `_trace_carrier` inside `OrchestrationController.offload` -> `run_offload_job`.
  - Wraps `LitestarMCP` tool invocations via `MCPConfig(before_tool_call=..., after_tool_call=...)` in `goe.mcp.tool.<tool_name>` spans.
