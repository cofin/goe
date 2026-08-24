---
type: Reference
title: Spark Task Listener Architecture
description: Custom Scala GOETaskListener, metric capture, Log4j scraping, and cross-compilation matrices
tags:
  - reference
  - transport
  - spark
  - scala
  - listener
---

# Spark Task Listener Architecture

The **Spark Task Listener** (`tools/spark-listener/`) is a custom Scala extension designed to capture fine-grained task execution metrics from Apache Spark.

## Implementation (`GOETaskListener.scala`)

- Extends `org.apache.spark.scheduler.SparkListener`.
- Intercepts `onTaskEnd(taskEnd: SparkListenerTaskEnd)`:
  - `taskMetrics.outputMetrics.recordsWritten` (exact row count extracted).
  - `taskMetrics.outputMetrics.bytesWritten` (exact byte volume).
  - `taskMetrics.duration` & `executorRunTime`.
- Serializes metrics as JSON logs via Log4j.

## Compilation Matrix

Built via `sbt` and `Makefile` across Scala 2.12/2.13 and Spark 3.0 through 3.5:
- `spark-3.0.1-listener-1.0.jar` (Scala 2.12)
- `spark-3.1.2-listener-1.0.jar` (Scala 2.12)
- `spark-3.2.0-listener-1.0.jar` (Scala 2.12 / 2.13)
- `spark-3.3.0-listener-1.0.jar` (Scala 2.12 / 2.13)
- `spark-3.5.1-listener-1.0.jar` (Scala 2.12 / 2.13)
- `spark-3.5.3-listener-1.0.jar` (Scala 2.12 / 2.13)

## Metric Scraping & Polling Fallback

1. **Stdout/Stderr Scraper**: The Python driver scrapes Spark execution logs for `GOETaskListener` JSON events using regex `SPARK_LOG_ROW_COUNT_PATTERN`.
2. **Database Polling Fallback**: If logs are missing, `OffloadTransportSqlStatsThread` polls source RDBMS performance views (`V$SESSTAT`, `V$SQL`) matching module tag `GOE-Transport`.
