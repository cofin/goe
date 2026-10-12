-- name: get_partition_column_names
SELECT UPPER(pk.column_name)
FROM   dba_part_key_columns pk
WHERE  pk.owner = :owner
AND    pk.name = :table_name
ORDER BY pk.column_position;

-- name: get_subpartition_column_names
SELECT UPPER(pk.column_name)
FROM   dba_subpart_key_columns pk
WHERE  pk.owner = :owner
AND    pk.name = :table_name
ORDER BY pk.column_position;

-- name: get_session_events
SELECT event, ROUND(time_waited_micro/1e6,2) FROM v$session_event WHERE sid = SYS_CONTEXT('USERENV','SID');

-- name: get_iot_type
SELECT NVL2(t.iot_type,'IOT',NULL) AS iot_type
FROM   all_tables t
WHERE  t.owner = :owner
AND    t.table_name = :table_name;

-- name: agg_validate_sample_column_names
SELECT column_name
FROM  (
       SELECT column_name
       ,      column_id
       ,      MAX(column_id) OVER () AS last_column_id
       ,      ROW_NUMBER() OVER (ORDER BY num_distinct DESC) AS ndv_rank
       FROM   all_tab_cols
       WHERE  owner = :owner
       AND    table_name = :table_name
       AND    hidden_column = 'NO'
      )
WHERE  column_id IN (1, last_column_id)
OR     ndv_rank <= :required_no;

-- name: get_columns
SELECT UPPER(column_name)
,      column_id
,      nullable
,      data_type
,      data_precision
,      data_scale
,      data_length     AS byte_length
,      data_default
,      hidden_column
,      char_used
,      char_length
FROM   all_tab_cols
WHERE  owner = :owner
AND    table_name = :table_name
AND    hidden_column = 'NO'
ORDER BY column_id ASC;

-- name: get_current_scn
SELECT current_scn FROM v$database;

-- name: get_db_unique_name
SELECT SYS_CONTEXT('USERENV', 'DB_UNIQUE_NAME') ||
       CASE
          WHEN version >= 12
          THEN CASE
                  WHEN SYS_CONTEXT('USERENV', 'CDB_NAME') IS NOT NULL
                  THEN '_' || SYS_CONTEXT('USERENV', 'CON_NAME')
               END
       END
FROM  (
       SELECT TO_NUMBER(REGEXP_SUBSTR(version, '[0-9]+')) AS version
       FROM   v$instance
      );

-- name: get_primary_key_column_names
SELECT cc.column_name
FROM   dba_constraints c
,      dba_cons_columns cc
WHERE  c.owner = :owner
AND    c.table_name = :table_name
AND    c.constraint_type = 'P'
AND    cc.owner = c.owner
AND    cc.table_name = c.table_name
AND    cc.constraint_name = c.constraint_name
ORDER BY cc.position;

-- name: get_session_user
SELECT sys_context('USERENV','SESSION_USER') FROM DUAL;

-- name: get_table_default_parallelism
SELECT TRIM(degree) FROM dba_tables WHERE owner = :owner AND table_name = :table_name;

-- name: get_iot_table_size
SELECT SUM(bytes) AS bytes
FROM dba_segments s
WHERE (s.owner, s.segment_name) = (SELECT c.owner, c.index_name
                                   FROM dba_constraints c
                                   WHERE c.owner = :owner
                                   AND c.table_name = :table_name
                                   AND c.constraint_type  = 'P');

-- name: get_table_size
SELECT SUM(bytes) bytes
FROM dba_segments s
WHERE s.owner = :owner
AND s.segment_name = :table_name;

-- name: schema_exists
SELECT 1 FROM dba_users WHERE username = :schema;

-- name: table_exists
SELECT table_name FROM dba_tables WHERE owner = :owner AND table_name = :table_name;

-- name: view_exists
SELECT 1 FROM dba_views WHERE owner = :owner AND view_name = :view_name;
