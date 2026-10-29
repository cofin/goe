-- SPDX-FileCopyrightText: 2026 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

-- name: get_session_context
SELECT i.version AS version,
       d.db_unique_name AS db_unique_name,
       d.current_scn AS current_scn,
       MAX(CASE WHEN p.name = 'compatible' THEN p.value END) AS compatible,
       MAX(CASE WHEN p.name = 'db_block_size' THEN p.value END) AS db_block_size,
       MAX(CASE WHEN p.name = 'max_string_size' THEN p.value END) AS max_string_size,
       MAX(CASE WHEN p.name = 'cell_offload_processing' THEN p.value END) AS cell_offload_processing,
       SYS_CONTEXT('USERENV', 'SESSION_USER') AS current_user
FROM v$instance i
CROSS JOIN v$database d
LEFT JOIN v$parameter p
  ON p.name IN ('compatible', 'db_block_size', 'max_string_size', 'cell_offload_processing')
GROUP BY i.version, d.db_unique_name, d.current_scn;

-- name: get_table_overview
SELECT t.owner,
       t.table_name,
       t.iot_type,
       t.partitioned,
       pt.partitioning_type,
       pt.subpartitioning_type,
       TRIM(t.degree) AS degree,
       t.compression,
       t.compress_for,
       t.num_rows,
       t.blocks,
       t.avg_row_len,
       t.last_analyzed,
       NVL(s.size_bytes, NVL(t.blocks, 0) * TO_NUMBER(NVL(bp.value, '8192'))) AS size_bytes
FROM all_tables t
LEFT JOIN all_part_tables pt
  ON pt.owner = t.owner
 AND pt.table_name = t.table_name
LEFT JOIN (
    SELECT owner,
           segment_name,
           SUM(bytes) AS size_bytes
    FROM dba_segments
    WHERE owner = :owner
      AND segment_name = :table_name
      AND segment_type LIKE 'TABLE%'
    GROUP BY owner, segment_name
) s
  ON s.owner = t.owner
 AND s.segment_name = t.table_name
LEFT JOIN v$parameter bp
  ON bp.name = 'db_block_size'
WHERE t.owner = :owner
  AND t.table_name = :table_name;

-- name: get_table_columns
SELECT c.column_id,
       c.column_name,
       c.data_type,
       c.data_type_owner,
       c.data_type_mod,
       c.char_used,
       c.data_length,
       c.char_length,
       c.data_precision,
       c.data_scale,
       c.nullable,
       c.data_default,
       c.hidden_column,
       c.virtual_column,
       c.num_distinct,
       c.num_nulls,
       c.avg_col_len,
       c.low_value,
       c.high_value,
       pkc.column_position AS part_pos,
       spkc.column_position AS subpart_pos
FROM all_tab_cols c
LEFT JOIN all_part_key_columns pkc
  ON pkc.owner = c.owner
 AND pkc.name = c.table_name
 AND TRIM(pkc.object_type) = 'TABLE'
 AND pkc.column_name = c.column_name
LEFT JOIN all_subpart_key_columns spkc
  ON spkc.owner = c.owner
 AND spkc.name = c.table_name
 AND TRIM(spkc.object_type) = 'TABLE'
 AND spkc.column_name = c.column_name
WHERE c.owner = :owner
  AND c.table_name = :table_name
ORDER BY NVL(c.column_id, c.internal_column_id);

-- name: get_table_constraints
SELECT ac.constraint_name,
       ac.constraint_type,
       ac.status,
       ac.validated,
       acc.column_name,
       acc.position
FROM all_constraints ac
JOIN all_cons_columns acc
  ON acc.owner = ac.owner
 AND acc.constraint_name = ac.constraint_name
 AND acc.table_name = ac.table_name
WHERE ac.owner = :owner
  AND ac.table_name = :table_name
  AND ac.constraint_type IN ('P', 'U')
ORDER BY ac.constraint_name, acc.position;

-- name: get_table_indexes
SELECT ai.owner AS index_owner,
       ai.index_name,
       ai.index_type,
       ai.uniqueness,
       aic.column_name,
       aic.column_position
FROM all_indexes ai
JOIN all_ind_columns aic
  ON aic.index_owner = ai.owner
 AND aic.index_name = ai.index_name
WHERE ai.table_owner = :owner
  AND ai.table_name = :table_name
ORDER BY ai.owner, ai.index_name, aic.column_position;

-- name: get_table_partitions
SELECT tp.partition_name,
       tp.partition_position,
       tp.high_value,
       tp.subpartition_count,
       tp.num_rows,
       tp.blocks,
       tp.avg_row_len,
       NVL(s.size_bytes, NVL(tp.blocks, 0) * TO_NUMBER(NVL(bp.value, '8192'))) AS size_bytes
FROM all_tab_partitions tp
LEFT JOIN (
    SELECT owner,
           segment_name,
           partition_name,
           SUM(bytes) AS size_bytes
    FROM dba_segments
    WHERE owner = :owner
      AND segment_name = :table_name
      AND segment_type IN ('TABLE PARTITION', 'TABLE SUBPARTITION')
    GROUP BY owner, segment_name, partition_name
) s
  ON s.owner = tp.table_owner
 AND s.segment_name = tp.table_name
 AND s.partition_name = tp.partition_name
LEFT JOIN v$parameter bp
  ON bp.name = 'db_block_size'
WHERE tp.table_owner = :owner
  AND tp.table_name = :table_name
ORDER BY tp.partition_position DESC;

-- name: get_table_subpartitions
SELECT tp.partition_name,
       tp.partition_position,
       tsp.subpartition_name,
       tsp.subpartition_position,
       tsp.high_value,
       tsp.num_rows,
       tsp.blocks,
       tsp.avg_row_len,
       NVL(s.size_bytes, NVL(tsp.blocks, 0) * TO_NUMBER(NVL(bp.value, '8192'))) AS size_bytes
FROM all_tab_subpartitions tsp
JOIN all_tab_partitions tp
  ON tp.table_owner = tsp.table_owner
 AND tp.table_name = tsp.table_name
 AND tp.partition_name = tsp.partition_name
LEFT JOIN (
    SELECT owner,
           segment_name,
           partition_name,
           SUM(bytes) AS size_bytes
    FROM dba_segments
    WHERE owner = :owner
      AND segment_name = :table_name
      AND segment_type = 'TABLE SUBPARTITION'
    GROUP BY owner, segment_name, partition_name
) s
  ON s.owner = tsp.table_owner
 AND s.segment_name = tsp.table_name
 AND s.partition_name = tsp.subpartition_name
LEFT JOIN v$parameter bp
  ON bp.name = 'db_block_size'
WHERE tsp.table_owner = :owner
  AND tsp.table_name = :table_name
ORDER BY tp.partition_position DESC, tsp.subpartition_position DESC;

-- name: get_type_attributes
SELECT attr_no,
       attr_name,
       attr_type_name,
       attr_type_owner,
       length,
       precision,
       scale
FROM all_type_attrs
WHERE owner = :type_owner
  AND type_name = :type_name
ORDER BY attr_no;

-- name: get_collection_types
SELECT coll_type,
       elem_type_name,
       elem_type_owner,
       upper_bound,
       length,
       precision,
       scale
FROM all_coll_types
WHERE owner = :type_owner
  AND type_name = :type_name;

-- name: get_schema_tables
SELECT owner,
       table_name,
       iot_type,
       partitioned,
       num_rows
FROM all_tables
WHERE owner = :owner
ORDER BY table_name;

-- name: get_views
SELECT owner,
       view_name,
       text_length,
       text
FROM all_views
WHERE owner = :owner
ORDER BY view_name;
