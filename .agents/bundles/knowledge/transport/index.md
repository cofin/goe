---
type: Reference
title: Data Transport & Spark Engine
description: PySpark extraction, Dataproc Serverless, Spark listener metrics, and serialization codecs
tags:
  - reference
  - transport
  - spark
  - dataproc
  - index
---

# Data Transport & Spark Engine

This section documents the distributed transport layer, Spark execution engines, and serialization codecs utilized by GOE.

## Chapters

- [Dataproc & Spark Engines](spark-dataproc.md) - Google Cloud Dataproc Serverless Batches, Dataproc clusters, Apache Livy, and JDBC splitting algorithms.
- [Spark Task Listener](spark-listener.md) - Custom Scala `GOETaskListener`, low-level task metric interception, and compilation matrices.
- [Staging & Serialization](staging-serialization.md) - Staging formats (Avro, Parquet), chunk buffering, and Base64 binary encoding.
