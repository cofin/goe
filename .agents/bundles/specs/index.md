---
type: Reference
title: Specifications Registry
description: Active, planned, and completed feature specifications and task worksheets
tags:
  - reference
  - specs
  - index
---

# Specifications Registry

This directory contains specifications and task worksheets for active, planned, and completed work streams in Flow.

## Master Roadmaps (PRDs)

- [GOE Modernization Master Roadmap (`modernization_overhaul_20260823`)](modernization_overhaul_20260823/spec.md) - [State: Planned] Master architectural roadmap overhauling packaging/CI, serialization with msgspec & sqlspec, unified rich-click CLI, and Litestar listener ecosystem.

## Active & Planned Child Flows

- [Chapter 1: Build Tooling, Ruff, UV Dependency Groups & GitHub Actions CI Overhaul (`build_ci_overhaul_20260823`)](build_ci_overhaul_20260823/spec.md) - [State: Planned] Modernization of build backend to Hatchling, UV dependency groups, Ruff linter/formatter, modernized Makefile, and multi-matrix GitHub Actions CI with PyApp standalone binary builds.
- [Chapter 2: High-Performance Msgspec Serialization & SQLSpec Data Layer (`msgspec_sqlspec_overhaul_20260823`)](msgspec_sqlspec_overhaul_20260823/spec.md) - [State: Planned] Complete elimination of orjson in favor of msgspec encoders/decoders and typed Struct models, alongside SQLSpec data abstraction integration.
- [Chapter 3: Unified Rich-Click CLI Suite & Interactive Terminal UX (`rich_click_cli_overhaul_20260823`)](rich_click_cli_overhaul_20260823/spec.md) - [State: Planned] Consolidation of legacy optparse scripts into a unified, richly formatted Click CLI suite with subcommands, styled panels, and backward-compatible bin/ wrappers.
- [Chapter 4: Next-Generation Litestar Listener Service & Ecosystem (`litestar_listener_overhaul_20260823`)](litestar_listener_overhaul_20260823/spec.md) - [State: Planned] Complete rebuild of the GOE Listener service with Litestar 2.8+, Granian ASGI runtime, litestar-queues, litestar-security, litestar-autowire, and litestar-mcp.

## Completed Flows

Completed flows are synthesized into the knowledge base upon archive and recorded in [Change Log](../log.md).
