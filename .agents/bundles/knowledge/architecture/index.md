---
type: Architecture
title: Architecture & Orchestration
description: Core architecture, lifecycle orchestration, canonical typing, and schema synchronization
tags:
  - architecture
  - orchestration
  - core
  - index
---

# Architecture & Orchestration

This section documents the foundational architecture and orchestration runtime of the GOE framework.

## Chapters

- [Orchestration Core](orchestration.md) - Deep dive into `OrchestrationRunner`, process locking, execution identity, repository tracking, and command steps.
- [Offload Lifecycle](offload-lifecycle.md) - End-to-end operational phases from pre-flight validation and partition discovery to staging, loading, and verification.
- [Canonical Type Mapping](type-mapping.md) - The 3-tier canonical typing system, sampling algorithms, and type conversion matrices across supported databases.
- [Schema Evolution](schema-evolution.md) - `schema_sync` analysis, difference vector detection, and automated target DDL synchronization.
