---
type: Architecture
title: Canonical Type Mapping System
description: Three-tier data type abstraction, adaptive sampling algorithms, and type conversion matrices
tags:
  - architecture
  - type-mapping
  - canonical-types
  - sampling
  - schema
---

# Canonical Type Mapping System

GOE uses a 3-tier canonical typing system defined in `src/goe/offload/column_metadata.py` to ensure lossless conversions between disparate database dialects:

```
[ Frontend Source Type ]  <--->  [ GOE Canonical Type ]  <--->  [ Target Backend Type ]
   (OracleColumn /                  (CanonicalColumn)             (BigQueryColumn /
    MSSQLColumn /                                                  SnowflakeColumn /
    TeradataColumn)                                                SynapseColumn)
```

## Canonical Types Overview

| Canonical Type | Category | Modifiers | Default Backend Mapping (BigQuery / Snowflake / Synapse) |
| :--- | :--- | :--- | :--- |
| `GOE_TYPE_FIXED_STRING` | String | `data_length`, `char_semantics` | `STRING` / `TEXT(n)` / `char(n)` |
| `GOE_TYPE_VARIABLE_STRING` | String | `data_length`, `char_semantics` | `STRING` / `TEXT(n)` / `varchar(n)` |
| `GOE_TYPE_LARGE_STRING` | String | `char_semantics` | `STRING` / `TEXT` / `varchar(max)` |
| `GOE_TYPE_BINARY` | Binary | `data_length` | `BYTES` / `BINARY(n)` / `varbinary(n)` |
| `GOE_TYPE_LARGE_BINARY` | Binary | — | `BYTES` / `BINARY` / `varbinary(max)` |
| `GOE_TYPE_INTEGER_1` | Integer | 1-byte (-128 to 127) | `INT64` / `NUMBER(2,0)` / `tinyint` |
| `GOE_TYPE_INTEGER_2` | Integer | 2-byte (-32768 to 32767) | `INT64` / `NUMBER(4,0)` / `smallint` |
| `GOE_TYPE_INTEGER_4` | Integer | 4-byte (-2^31 to 2^31-1) | `INT64` / `NUMBER(9,0)` / `int` |
| `GOE_TYPE_INTEGER_8` | Integer | 8-byte (-2^63 to 2^63-1) | `INT64` / `NUMBER(18,0)` / `bigint` |
| `GOE_TYPE_INTEGER_38` | Integer | 38-digit integer | `NUMERIC(38,0)` / `NUMBER(38,0)` / `decimal(38,0)` |
| `GOE_TYPE_DECIMAL` | Decimal | `data_precision`, `data_scale` | `NUMERIC(p,s)` / `NUMBER(p,s)` / `decimal(p,s)` |
| `GOE_TYPE_FLOAT` | Float | IEEE Float32 | `FLOAT64` / `FLOAT` / `real` |
| `GOE_TYPE_DOUBLE` | Float | IEEE Float64 | `FLOAT64` / `FLOAT` / `float` |
| `GOE_TYPE_DATE` | Date/Time | Pure date without time | `DATE` / `DATE` / `date` |
| `GOE_TYPE_TIME` | Date/Time | Time without date | `TIME` / `TIME` / `time` |
| `GOE_TYPE_TIMESTAMP` | Date/Time | Date with time | `DATETIME` / `TIMESTAMP_NTZ` / `datetime2` |
| `GOE_TYPE_TIMESTAMP_TZ`| Date/Time | Date with timezone | `TIMESTAMP` / `TIMESTAMP_TZ` / `datetimeoffset` |
| `GOE_TYPE_INTERVAL_DS` | Interval | Day to Second | `STRING` / `TEXT` / `varchar(100)` |
| `GOE_TYPE_INTERVAL_YM` | Interval | Year to Month | `STRING` / `TEXT` / `varchar(100)` |
| `GOE_TYPE_BOOLEAN` | Boolean | True / False | `BOOLEAN` / `BOOLEAN` / `bit` |

## Adaptive Sampling Engine

When source columns have unconstrained precision (such as Oracle `NUMBER` or `FLOAT` without specified scale), `is_safe_mapping()` evaluates to `False`. GOE invokes `sample_rdbms_data_types()`:
1. **Sampling Query**: Queries a representative sample of rows (default `--data-sample-pct AUTO`):
   ```sql
   SELECT MAX(LENGTH(TRUNC(col))) AS max_int_digits,
          MAX(LENGTH(col - TRUNC(col)) - 1) AS max_scale
   FROM source_table SAMPLE BLOCK (sample_pct);
   ```
2. **Type Determination**:
   - If `max_scale == 0`: Selects the smallest integer type (`INTEGER_1` through `INTEGER_8` or `INTEGER_38`).
   - If `max_scale > 0`: Derives precision `p = max_int_digits + max_scale` and scale `s = max_scale`, mapping to `DECIMAL(p, s)`.
3. **Reproducibility**: Logs CLI override flags (e.g. `--integer-8-columns COL_A`) so future offloads can run deterministically without sampling overhead.

## Synthetic Partition Columns

For target platforms lacking expression-based partitioning, GOE generates synthetic partition columns during transformation:
- **Date/Timestamp**: `GOE_PART_Y_<COL>` (Year), `GOE_PART_M_<COL>` (Month), `GOE_PART_D_<COL>` (Day).
- **Integer Bucketing**: `GOE_PART_<BUCKET>_<COL>` (e.g., `GOE_PART_1000_CUSTOMER_ID`).
