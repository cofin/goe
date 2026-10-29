-- name: fetch_server_version
SELECT @@VERSION AS server_version;

-- name: check_schema_exists
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name = ?;

-- name: check_table_exists
SELECT table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema = ?
  AND table_name = ?;

-- name: check_view_exists
SELECT table_name
FROM information_schema.tables
WHERE table_type = 'VIEW'
  AND table_schema = ?
  AND table_name = ?;

-- name: fetch_table_columns
SELECT column_name
,      ordinal_position AS column_id
,      is_nullable AS nullable
,      data_type
,      COALESCE(numeric_precision, datetime_precision) AS data_precision
,      numeric_scale AS data_scale
,      character_octet_length AS byte_length
,      column_default AS data_default
,      NULL AS hidden_columns
,      character_maximum_length AS char_length
FROM information_schema.columns
WHERE table_schema = ?
  AND table_name = ?
ORDER BY ordinal_position;

-- name: fetch_primary_key_columns
SELECT COL_NAME(ic.object_id, ic.column_id) AS column_name
FROM sys.tables t
INNER JOIN sys.indexes i
  ON t.object_id = i.object_id
INNER JOIN sys.index_columns ic
  ON i.object_id = ic.object_id
 AND i.index_id = ic.index_id
INNER JOIN sys.schemas s
  ON t.schema_id = s.schema_id
WHERE s.name = ?
  AND t.name = ?
  AND i.is_primary_key = 1
ORDER BY ic.column_id;

-- name: fetch_table_details
WITH partitions AS (
    SELECT DISTINCT p.partition_number
    ,      p.rows
    FROM sys.tables t
    INNER JOIN sys.partitions p
      ON p.object_id = t.object_id
    INNER JOIN sys.schemas s
      ON t.schema_id = s.schema_id
    WHERE s.name = ?
      AND t.name = ?
      AND p.index_id IN (0, 1)
)
SELECT NULL AS iot_type
,      SUM(rows) AS num_rows
,      CASE WHEN MAX(partition_number) > 1 THEN 'YES' ELSE 'NO' END AS partitioned
,      NULL AS partitioning_type
FROM partitions;

-- name: fetch_table_size_bytes
SELECT SUM(ps.in_row_data_page_count + ps.lob_used_page_count + ps.row_overflow_used_page_count) * 8192 AS size_bytes
FROM sys.dm_db_partition_stats ps
INNER JOIN sys.tables t
  ON ps.object_id = t.object_id
INNER JOIN sys.schemas s
  ON t.schema_id = s.schema_id
WHERE s.name = ?
  AND t.name = ?
  AND ps.index_id IN (0, 1);

-- name: fetch_hash_bucket_candidate
SELECT TOP 1 c.name AS column_name
FROM sys.stats st
INNER JOIN sys.stats_columns sc
  ON st.object_id = sc.object_id
 AND st.stats_id = sc.stats_id
INNER JOIN sys.columns c
  ON sc.object_id = c.object_id
 AND sc.column_id = c.column_id
INNER JOIN sys.tables t
  ON st.object_id = t.object_id
INNER JOIN sys.schemas s
  ON t.schema_id = s.schema_id
CROSS APPLY sys.dm_db_stats_properties(st.object_id, st.stats_id) sp
WHERE s.name = ?
  AND t.name = ?
  AND sc.stats_column_id = 1
  AND sp.rows > 0
ORDER BY sp.modification_counter ASC, c.column_id ASC;
