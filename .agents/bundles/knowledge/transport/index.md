---
type: Reference
title: Data Transport, Spark & DuckDB Engines
description: PySpark extraction, Dataproc Serverless, opt-in DuckDB transport, Spark listener metrics, and serialization codecs
tags:
  - reference
  - transport
  - spark
  - dataproc
  - duckdb
  - index
---

# Data Transport, Spark & DuckDB Engines

This section documents the distributed and local transport layer, Spark and Dataproc execution engines, opt-in zero-JVM DuckDB transport, and serialization codecs utilized by GOE.

## Chapters

- [Dataproc, Spark & Query Import Engines](spark-dataproc.md) - GCP-first `AUTO` transport order, Google Cloud Dataproc Serverless Batches, Dataproc clusters, Apache Livy, Query Import, JDBC splitting algorithms, and transport OpenTelemetry spans.
- [DuckDB & `duckdb-oracle` Offload Transport](duckdb.md) - Opt-in zero-JVM `OffloadTransportDuckDB` (`--offload-transport-method=DUCKDB`), `cofin/duckdb-oracle` (`oracle_query`), community `gcs` extension (`gcss://` + dual-mode ADC secrets), mandatory `AS OF SCN` verification, and per-batch spans.
- [Spark Task Listener](spark-listener.md) - Custom Scala `GOETaskListener`, low-level task metric interception, and compilation matrices.
- [Staging & Serialization](staging-serialization.md) - Staging formats (Parquet default on GCP, Avro), chunk buffering, and Base64 binary encoding.
