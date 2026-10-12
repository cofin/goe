---
type: Reference
title: Operations & Tooling
description: CLI entrypoints, runtime layout, environment configuration, OpenTelemetry observability, database installation, and container deployment
tags:
  - reference
  - operations
  - tooling
  - observability
  - deployment
  - index
---

# Operations & Tooling

This section documents operational workflows, CLI utilities, runtime directory layout, configuration management, OpenTelemetry observability, and deployment architectures.

## Chapters

- [CLI Utilities](cli-tools.md) - Command-line tools: `offload`, `connect`, `logmgr`, `agg_validate`, and `listener`.
- [Offload Home Runtime](offload-home.md) - Directory layout, build targets, packaging, and virtualenv installation.
- [Configuration Reference](configuration-and-env.md) - Complete inventory of environment variables, defaults, overrides, and validation rules.
- [OpenTelemetry Observability](observability.md) - Zero-cost-by-default tracing, metrics, `ExecutionId` context bridge, OTLP / Google Cloud Telemetry API exporters, and JSONL log correlation.
- [Database Installation](database-installation.md) - Oracle DDL, user security privileges, PL/SQL packages, and upgrade migrations.
- [Container & Cloud Run](cloud-run-deployment.md) - Google Cloud Run Jobs container deployment and networking.
