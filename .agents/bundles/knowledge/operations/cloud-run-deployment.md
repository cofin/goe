---
type: Reference
title: Google Cloud Run & Container Deployment
description: Container packaging, Cloud Run Jobs deployment, VPC network connectors, and Oracle client modes
tags:
  - reference
  - operations
  - container
  - cloud-run
  - gcp
---

# Google Cloud Run & Container Deployment

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
