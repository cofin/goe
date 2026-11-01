---
type: concept
title: Google Cloud Run & Container Deployment
description: Container packaging, Cloud Run Jobs deployment, VPC network connectors, and Oracle client modes.
status: stable
tags:
  - reference
  - operations
  - container
  - cloud-run
generated:
  by: flow/0.26.0
  at: "2026-11-01T15:25:00Z"
verified:
  - by: agent:flow-setup
    at: "2026-11-01T15:25:00Z"
    commit: 02b9409
sources:
  - id: listener-cmd
    resource: src/goe/cli/commands/listener.py::listener
    title: Listener CLI and Worker Topology Commands
  - id: vertebra-gate
    resource: src/goe/listener/vertebra_gate.py::build_vertebra_command
    title: Vertebra ASGI Command Builder
---

# Google Cloud Run & Container Deployment

<!-- truth: start -->
- Container deployments run `goe listener start` for the HTTP/MCP web tier (`vertebra run goe.listener.asgi:app`) and `goe listener start --worker-only` for dedicated `DurableJobWorker` background pods.[^listener-cmd][^vertebra-gate]
- `CgroupQuota.detect()` (`src/goe/platform/worker.py`) sizes default HTTP workers and clamps DuckDB memory to 75% of the container cgroup limit.
<!-- truth: end -->

GOE supports containerized execution via **Google Cloud Run Jobs** for serverless, event-driven, or scheduled offloads.

## Container Architecture

- **Base Image**: `google/cloud-sdk:slim` with Python 3.11.
- **Payload**: Distributable `goe.tar.gz` unpacked into `/opt/goe/offload` with virtual environment dependencies.
- **Oracle Client**:
  - Thin mode (default): Zero external native libraries.
  - Thick mode: Installs Oracle Instant Client RPMs/zips for Oracle Wallet authentication.

## Execution via Cloud Run Jobs

```bash
# Execute offload job in Cloud Run
gcloud run jobs create offload-sales-job \
  --image gcr.io/${PROJECT_ID}/goe:${VERSION} \
  --network=${VPC_NETWORK} \
  --subnet=${VPC_SUBNET} \
  --service-account=${SERVICE_ACCOUNT} \
  --args "offload,-t,SH.SALES,-x,--no-ansi"
```

## Networking & IAM Invariants

- **VPC Access**: Cloud Run Jobs require a Serverless VPC Access Connector or Direct VPC egress to route private JDBC traffic to on-premises / GCE Oracle databases.
- **Private Google Access**: Subnets must have Private Google Access enabled to communicate with BigQuery and GCS APIs without public IP addresses.

[^listener-cmd]: `src/goe/cli/commands/listener.py::listener` — Listener CLI and Worker Topology Commands.
[^vertebra-gate]: `src/goe/listener/vertebra_gate.py::build_vertebra_command` — Vertebra ASGI Command Builder.
