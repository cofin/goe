-- name: get_offloadable_schemas
WITH valid_schemas AS (
        SELECT owner AS schema_name
        ,      count(*) table_count
        FROM   dba_tables
        WHERE  1=1
        AND owner NOT IN (
            SELECT grantee
            FROM dba_role_privs
            WHERE granted_role = 'GOE_OFFLOAD_ROLE'
            AND grantee LIKE '%\_H' escape '\'
        )
        AND owner NOT IN (
        'ANONYMOUS' , 'APEX_PUBLIC_USER' , 'APPQOSSYS'
        , 'AUDSYS' , 'AURORA$JIS$UTILITY$' , 'CSMIG' , 'CTXSYS'
        , 'DBMS_PRIVILEGE_CAPTURE' , 'DBSFWUSER' , 'DBSNMP' , 'DIP'
        , 'DMSYS' , 'DSSYS' , 'DVF' , 'DVSYS'
        , 'ECCADMIN' , 'EXFSYS' , 'FLOWS_030000' , 'FLOWS_FILES'
        , 'GGSYS' , 'GSMADMIN_INTERNAL' , 'GSMCATUSER' , 'GSMROOTUSER'
        , 'GSMUSER' , 'IGNITE' , 'LBACSYS' , 'MDDATA'
        , 'MDSYS' , 'MGMT_VIEW' , 'MTSSYS' , 'OJVMSYS'
        , 'OLAPSYS' , 'ORACLE_OCM' , 'ORDDATA' , 'ORDPLUGINS'
        , 'ORDSYS' , 'OSE$HTTP$ADMIN' , 'OUTLN' , 'OWBSYS'
        , 'OWBSYS_AUDIT' , 'PERFSTAT' , 'REMOTE_SCHEDULER_AGENT' , 'SI_INFORMTN_SCHEMA'
        , 'SPATIAL_CSW_ADMIN_USR' , 'SPATIAL_WFS_ADMIN_USR' , 'SYS$UMF' , 'SYS'
        , 'SYSBACKUP' , 'SYSDG' , 'SYSKM' , 'SYSMAN'
        , 'SYSRAC' , 'SYSTEM' , 'TRACESVR' , 'TSMSYS'
        , 'WKPROXY' , 'WKSYS' , 'WK_TEST' , 'WMSYS'
        , 'XDB' , 'XS$NULL'
        )
        AND NOT regexp_like( owner, '^APEX_[0-9]*')
        AND NOT regexp_like( owner, '^FLOWS_[0-9]*')
        AND owner NOT IN (UPPER(:adm_user), UPPER(:app_user), UPPER(:repo_user))
        GROUP BY owner
        )
,    segments AS (
        SELECT /*+
                    MATERIALIZE
                    LEADING(s vs)
                    NO_MERGE(s)
                    USE_HASH(vs)
                    SWAP_JOIN_INPUTS(vs)
                */
            s.owner
        ,      CASE
                WHEN EXISTS( SELECT 1 FROM dba_role_privs WHERE granted_role = 'GOE_OFFLOAD_ROLE' AND grantee = owner || '_H' ) THEN 'True'
                ELSE 'False'
            END hybrid_schema_exists
        ,      vs.table_count
        ,      s.segment_name
        ,      s.partition_name
        ,      s.segment_type
        ,      s.bytes
        FROM   dba_segments         s
            INNER JOIN
            valid_schemas        vs
            ON (vs.schema_name   = s.owner)
        WHERE  1=1
        )
SELECT
    s.owner  schema_name
    , s.hybrid_schema_exists
    , s.table_count
    , sum(bytes) schema_size_in_bytes
FROM
    segments s
GROUP BY
    s.owner
    , s.hybrid_schema_exists
    , s.table_count
ORDER BY
    s.owner;

-- name: get_schema_tables
WITH unsupported_columns AS (
        SELECT ct.owner
        ,      ct.table_name
        ,      MIN(ct.unsupported_data_type) KEEP (
                DENSE_RANK FIRST ORDER BY ct.unsupported_data_type)   AS unsupported_data_type
        ,      COUNT(ct.unsupported_data_type)                        AS unsupported_data_type_count
        ,      MIN(ct.unsupported_col_name_1)  KEEP (
                DENSE_RANK FIRST ORDER BY ct.unsupported_col_name_1)  AS unsupported_col_name_1
        ,      COUNT(ct.unsupported_col_name_1)                       AS unsupported_col_name_1_count
        ,      MIN(ct.unsupported_col_name_2)  KEEP (
                DENSE_RANK FIRST ORDER BY ct.unsupported_col_name_2)  AS unsupported_col_name_2
        ,      COUNT(ct.unsupported_col_name_2)                       AS unsupported_col_name_2_count
        ,      MIN(ct.unsupported_col_name_3)  KEEP (
                DENSE_RANK FIRST ORDER BY ct.unsupported_col_name_3)  AS unsupported_col_name_3
        ,      COUNT(ct.unsupported_col_name_3)                       AS unsupported_col_name_3_count
        ,      MIN(ct.unsupported_col_name_4)  KEEP (
                DENSE_RANK FIRST ORDER BY ct.unsupported_col_name_4)  AS unsupported_col_name_4
        ,      COUNT(ct.unsupported_col_name_4)                       AS unsupported_col_name_4_count
        FROM  (
                SELECT /*+
                            MATERIALIZE
                            LEADING(tc vs)
                            NO_MERGE(tc)
                            USE_HASH(vs)
                            SWAP_JOIN_INPUTS(vs)
                        */
                    DISTINCT
                    tc.owner
                ,      tc.table_name
                ,      CASE
                        WHEN REGEXP_SUBSTR(tc.data_type, '[^\( ]+') NOT IN ('VARCHAR', 'VARCHAR2', 'NVARCHAR2',
                                                                            'CHAR', 'NCHAR', 'NUMBER', 'FLOAT',
                                                                            'BINARY_DOUBLE', 'BINARY_FLOAT',
                                                                            'DATE', 'TIMESTAMP', 'INTERVAL',
                                                                            'BLOB', 'CLOB', 'NCLOB', 'RAW')
                        THEN tc.data_type
                    END AS unsupported_data_type
                ,      CASE
                        WHEN NOT REGEXP_LIKE(tc.column_name, '^[A-Za-z0-9_][A-Za-z0-9_]*$')
                        THEN tc.column_name
                    END AS unsupported_col_name_1
                ,      CASE
                        WHEN NOT REGEXP_LIKE(tc.column_name, '^[A-Za-z_][A-Za-z0-9_]*$')
                        THEN tc.column_name
                    END AS unsupported_col_name_2
                ,      CASE
                        WHEN NOT REGEXP_LIKE(tc.column_name, '^[A-Za-z_][A-Za-z0-9_\$]*$')
                        THEN tc.column_name
                    END AS unsupported_col_name_3
                ,      CASE
                        WHEN NOT REGEXP_LIKE(tc.column_name, '^[A-Za-z0-9_#@][A-Za-z_0-9#@\$]*$')
                        THEN tc.column_name
                    END AS unsupported_col_name_4
                FROM   dba_tab_cols        tc
                WHERE  1=1
                AND    tc.owner = UPPER( :schema_name)
                AND    tc.hidden_column = 'NO'
                AND   (   NOT REGEXP_LIKE(tc.column_name, '^[A-Za-z_][A-Za-z0-9_]*$')
                    OR REGEXP_SUBSTR(tc.data_type, '[^\( ]+') NOT IN ('VARCHAR', 'VARCHAR2', 'NVARCHAR2',
                                                                        'CHAR', 'NCHAR', 'NUMBER', 'FLOAT',
                                                                        'BINARY_DOUBLE', 'BINARY_FLOAT',
                                                                        'DATE', 'TIMESTAMP', 'INTERVAL',
                                                                        'BLOB', 'CLOB', 'NCLOB', 'RAW'))
            ) ct
        GROUP BY
            ct.owner
        ,      ct.table_name
        )
,    part_tables AS (
        SELECT /*+
                    MATERIALIZE
                    LEADING(pt vs)
                    NO_MERGE(pt)
                    USE_HASH(vs pc tc)
                    SWAP_JOIN_INPUTS(vs)
                */
            pt.owner
        ,      pt.table_name
        ,      pt.partitioning_type
        ,      pt.subpartitioning_type
        FROM   dba_part_tables            pt
        WHERE  1=1
        AND    pt.owner = UPPER( :schema_name)
        )
,    tab_part_subpart AS (
        SELECT
            /*+
            materialize
            no_merge(dt)
            user_hash(dtp dts)
            */
            dt.owner                                       table_owner
            , dt.table_name                                table_name
            , dtp.partition_name                           partition_name
            , dts.subpartition_name                        subpartition_name
        FROM
            dba_tables dt
        LEFT OUTER JOIN
            dba_tab_partitions dtp
            ON (
            dtp.table_owner = dt.owner
            AND dtp.table_name = dt.table_name
            )
        LEFT OUTER JOIN
            dba_tab_subpartitions dts
            ON (
            dts.table_owner = dtp.table_owner
            AND dts.table_name = dtp.table_name
            AND dts.partition_name = dtp.partition_name
            )
        WHERE
            dt.owner = UPPER( :schema_name)
    )
,    segments AS (
        SELECT
            /*+
            materialize
            no_merge(ds)
            */
            ds.owner
            , ds.segment_name
            , ds.partition_name
            , ds.bytes
        FROM
            dba_segments ds
        WHERE
            ds.owner = UPPER( :schema_name)
    )
,    size_data AS (
        SELECT
            t.table_owner   table_owner
            , t.table_name  table_name
            , sum(s.bytes)  table_size
            , sum(op.bytes) table_offloaded_size
        FROM
            tab_part_subpart t
        INNER JOIN
            segments s
            ON (
            s.owner = t.table_owner
            AND s.segment_name = t.table_name
            AND COALESCE( s.partition_name, s.segment_name) = COALESCE( t.subpartition_name, t.partition_name, t.table_name)
            )
        LEFT OUTER JOIN
            /* slot: repo_user */.frontend_object fo
            ON (
            fo.database_name = t.table_owner
            AND fo.object_name = t.table_name
            )
        LEFT OUTER JOIN
            /* slot: repo_user */.offload_partition op
            ON (
            op.frontend_object_id = fo.id
            AND op.name = COALESCE( t.subpartition_name, t.partition_name, t.table_name)
            )
        GROUP BY
            t.table_owner, t.table_name
    )
,    reclaim_data AS (
        SELECT
            /*+
            materialize
            */
            fo.database_name   table_owner
            , fo.object_name   table_name
            , sum(op.bytes)    table_reclaimed_size
        FROM
            /* slot: repo_user */.frontend_object fo
        INNER JOIN
            /* slot: repo_user */.offload_partition op
            ON (
            op.frontend_object_id = fo.id
            )
        WHERE NOT EXISTS(
            SELECT 1
                FROM tab_part_subpart t
                WHERE fo.database_name = t.table_owner
                AND   fo.object_name = t.table_name
                AND   op.name = COALESCE( t.subpartition_name, t.partition_name, t.table_name)
        )
        GROUP BY
            fo.database_name, fo.object_name
    )
,    table_data AS (
        SELECT /*+
                    MATERIALIZE
                    LEADING(t vs)
                    NO_MERGE(t)
                    USE_HASH(vs pt uc)
                    SWAP_JOIN_INPUTS(vs)
                */
            t.owner
        ,      t.table_name
        ,      sd.table_size
        ,      sd.table_offloaded_size
        ,      rd.table_reclaimed_size
        ,      t.num_rows table_stats_rows
        ,      t.last_analyzed table_stats_date
        ,      CASE
                WHEN t.partitioned = 'YES' THEN NULL
                ELSE t.compression
            END table_compression
        ,      CASE
                WHEN t.partitioned = 'YES' THEN NULL
                ELSE t.compress_for
            END table_compress_for
        ,      pt.partitioning_type
        ,      pt.subpartitioning_type
        ,      CASE
                WHEN om.offloaded_owner IS NULL then 'False'
                ELSE 'True'
            END table_is_offloaded
        ,      CASE
                WHEN t.cluster_name IS NOT NULL
                THEN 1
                WHEN t.iot_type = 'IOT'
                THEN 2
                WHEN t.iot_type = 'IOT_OVERFLOW'
                THEN 3
                WHEN t.secondary = 'Y'
                THEN 4
                WHEN t.nested = 'YES'
                THEN 5
                WHEN t.table_name LIKE 'GOE_ADV%'
                THEN 6
                WHEN EXISTS (SELECT NULL
                                FROM   dba_mviews    mv
                                WHERE  mv.owner      = t.owner
                                AND    mv.mview_name = t.table_name)
                THEN 7
                WHEN EXISTS (SELECT NULL
                                FROM   dba_mview_logs mvl
                                WHERE  mvl.log_owner = t.owner
                                AND    mvl.log_table = t.table_name)
                THEN 8
                ELSE 0
            END AS table_type
        ,      uc.unsupported_data_type
        ,      uc.unsupported_data_type_count
        ,      uc.unsupported_col_name_1
        ,      uc.unsupported_col_name_1_count
        ,      uc.unsupported_col_name_2
        ,      uc.unsupported_col_name_2_count
        ,      uc.unsupported_col_name_3
        ,      uc.unsupported_col_name_3_count
        ,      uc.unsupported_col_name_4
        ,      uc.unsupported_col_name_4_count
        ,      uc./* slot: unsupported_col_name */       AS unsupported_col_name
        ,      uc./* slot: unsupported_col_name_count */ AS unsupported_col_name_count
        FROM   dba_all_tables           t
            INNER JOIN
            size_data                sd
            ON (    sd.table_owner   = t.owner
                AND sd.table_name    = t.table_name)
            LEFT OUTER JOIN
            reclaim_data             rd
            ON (    rd.table_owner   = t.owner
                AND rd.table_name    = t.table_name)
            LEFT OUTER JOIN
            part_tables              pt
            ON (    pt.owner         = t.owner
                AND pt.table_name    = t.table_name)
            LEFT OUTER JOIN
            unsupported_columns      uc
            ON (    uc.owner         = t.owner
                AND uc.table_name    = t.table_name)
            LEFT OUTER JOIN
                /* slot: repo_user */.offload_metadata om
            ON (    om.offloaded_owner              = t.owner
                AND om.offloaded_table              = t.table_name
                AND om.hybrid_view_type             = 'GOE_OFFLOAD_HYBRID_VIEW')
        WHERE  1=1
        AND    t.owner = UPPER( :schema_name)
        AND   (t.owner, t.table_name) NOT IN (SELECT et.owner, et.table_name FROM dba_external_tables et)
        AND    t.temporary = 'N'
        AND    t.dropped   = 'NO'
        )
SELECT /*+ MONITOR */
      t.table_name                                                           AS table_name
    , t.table_size                                                           AS table_size_in_bytes
    , t.table_offloaded_size                                                 AS table_offloaded_size_in_bytes
    , t.table_reclaimed_size                                                 AS table_reclaimed_size_in_bytes
    , t.table_stats_rows                                                     AS estimated_row_count
    , t.table_stats_date                                                     AS statistics_last_gathered_on
    , t.partitioning_type                                                    AS partitioning_type
    , t.subpartitioning_type                                                 AS subpartitioning_type
    , t.table_compression                                                    AS table_compression
    , t.table_compress_for                                                   AS table_compress_for
    , t.table_is_offloaded                                                   AS is_offloaded
    , CASE
       WHEN t.partitioning_type IS NOT NULL
       THEN 'True'
       ELSE 'False'
      END                                                                    AS is_partitioned
    , CASE
       WHEN t.subpartitioning_type IS NOT NULL
       THEN decode( t.subpartitioning_type, 'NONE', 'False', 'True')
       ELSE 'False'
      END                                                                    AS is_subpartitioned
    , CASE
       WHEN t.table_compress_for IS NOT NULL
       THEN 'True'
       WHEN nvl(t.table_compression, 'DISABLED') != 'DISABLED'
       THEN 'True'
       ELSE 'False'
      END                                                                    AS is_compressed
    , CASE
       WHEN t.unsupported_data_type_count + t.unsupported_col_name_count > 0
       THEN 'False'
       WHEN t.table_type in (1, 3, 4, 5, 6, 7, 8)
       THEN 'False'
       ELSE 'True'
      END                                                                    AS is_offloadable
    , CASE t.table_type
       WHEN 1
       THEN 'Table In Cluster'
       WHEN 3
       THEN 'IOT Overflow'
       WHEN 4
       THEN 'Secondary Table'
       WHEN 5
       THEN 'Nested Table'
       WHEN 6
       THEN 'GOE Table'
       WHEN 7
       THEN 'Materialized View'
       WHEN 8
       THEN 'Materialized View Log'
       ELSE
        CASE
         WHEN t.unsupported_data_type IS NOT NULL
         THEN 'Column Types [' || t.unsupported_data_type ||
              CASE
               WHEN t.unsupported_data_type_count > 1
               THEN ' +' || TO_CHAR(t.unsupported_data_type_count - 1) || ' more'
              END || ']'
         WHEN t.unsupported_col_name IS NOT NULL
         THEN 'Column Names [' || t.unsupported_col_name ||
              CASE
               WHEN t.unsupported_col_name_count > 1
               THEN ' +' || TO_CHAR(t.unsupported_col_name_count - 1) || ' more'
              END || ']'
        END
      END                                                                    AS reason_not_offloadable
FROM table_data t
ORDER BY t.table_name;

-- name: get_command_step_codes
SELECT code FROM /* slot: repo_user */.command_step ORDER BY 1;

-- name: get_command_executions
SELECT  CE.UUID                AS EXECUTION_ID,
        CT.CODE                AS COMMAND_TYPE_CODE,
        CT.NAME                AS COMMAND_TYPE,
        S.CODE                 AS STATUS_CODE,
        S.NAME                 AS STATUS,
        CE.START_TIME          AS STARTED_AT,
        CE.END_TIME            AS COMPLETED_AT,
        CE.COMMAND_LOG_PATH    AS COMMAND_LOG_PATH,
        CE.COMMAND_INPUT       AS COMMAND_INPUT,
        CE.COMMAND_PARAMETERS  AS COMMAND_PARAMETERS,
        GV.VERSION             AS GOE_VERSION,
        GV.BUILD               AS GOE_BUILD
FROM /* slot: repo_user */.COMMAND_EXECUTION CE
JOIN /* slot: repo_user */.STATUS S on S.ID = CE.STATUS_ID
JOIN /* slot: repo_user */.COMMAND_TYPE CT on CT.ID = CE.COMMAND_TYPE_ID
JOIN /* slot: repo_user */.GOE_VERSION GV on GV.ID = CE.GOE_VERSION_ID;

-- name: get_command_execution
SELECT  CE.UUID                AS EXECUTION_ID,
        CT.CODE                AS COMMAND_TYPE_CODE,
        CT.NAME                AS COMMAND_TYPE,
        S.CODE                 AS STATUS_CODE,
        S.NAME                 AS STATUS,
        CE.START_TIME          AS STARTED_AT,
        CE.END_TIME            AS COMPLETED_AT,
        CE.COMMAND_LOG_PATH    AS COMMAND_LOG_PATH,
        CE.COMMAND_INPUT       AS COMMAND_INPUT,
        CE.COMMAND_PARAMETERS  AS COMMAND_PARAMETERS,
        GV.VERSION             AS GOE_VERSION,
        GV.BUILD               AS GOE_BUILD
FROM /* slot: repo_user */.COMMAND_EXECUTION CE
JOIN /* slot: repo_user */.STATUS S on S.ID = CE.STATUS_ID
JOIN /* slot: repo_user */.COMMAND_TYPE CT on CT.ID = CE.COMMAND_TYPE_ID
JOIN /* slot: repo_user */.GOE_VERSION GV on GV.ID = CE.GOE_VERSION_ID
WHERE CE.UUID = :execution_id;

-- name: get_command_execution_steps_all
SELECT  CE.UUID          AS EXECUTION_ID,
        CS.ID            AS STEP_ID,
        CS.CODE          AS STEP_CODE,
        CS.TITLE         AS STEP_TITLE,
        CESS.CODE        AS STEP_STATUS_CODE,
        CESS.NAME        AS STEP_STATUS,
        CES.START_TIME   AS STARTED_AT,
        CES.END_TIME     AS COMPLETED_AT,
        CES.STEP_DETAILS AS STEP_DETAILS
FROM /* slot: repo_user */.COMMAND_EXECUTION CE
JOIN /* slot: repo_user */.STATUS S on S.ID = CE.STATUS_ID
JOIN /* slot: repo_user */.COMMAND_EXECUTION_STEP CES ON CE.ID = CES.COMMAND_EXECUTION_ID
JOIN /* slot: repo_user */.STATUS CESS on CESS.ID = CES.STATUS_ID
JOIN /* slot: repo_user */.COMMAND_STEP CS ON CS.ID = CES.COMMAND_STEP_ID
JOIN /* slot: repo_user */.COMMAND_TYPE CT ON CT.ID = CES.COMMAND_TYPE_ID;

-- name: get_command_execution_steps_by_id
SELECT  CE.UUID          AS EXECUTION_ID,
        CS.ID            AS STEP_ID,
        CS.CODE          AS STEP_CODE,
        CS.TITLE         AS STEP_TITLE,
        CESS.CODE        AS STEP_STATUS_CODE,
        CESS.NAME        AS STEP_STATUS,
        CES.START_TIME   AS STARTED_AT,
        CES.END_TIME     AS COMPLETED_AT,
        CES.STEP_DETAILS AS STEP_DETAILS
FROM /* slot: repo_user */.COMMAND_EXECUTION CE
JOIN /* slot: repo_user */.STATUS S on S.ID = CE.STATUS_ID
JOIN /* slot: repo_user */.COMMAND_EXECUTION_STEP CES ON CE.ID = CES.COMMAND_EXECUTION_ID
JOIN /* slot: repo_user */.STATUS CESS on CESS.ID = CES.STATUS_ID
JOIN /* slot: repo_user */.COMMAND_STEP CS ON CS.ID = CES.COMMAND_STEP_ID
JOIN /* slot: repo_user */.COMMAND_TYPE CT ON CT.ID = CES.COMMAND_TYPE_ID
WHERE CE.UUID = :execution_id;

-- name: get_offload_metadata
SELECT frontend_object_owner
,      frontend_object_name
,      backend_object_owner
,      backend_object_name
,      offload_type
,      offload_range_type
,      offload_key
,      offload_high_value
,      offload_predicate_type
,      offload_predicate_value
,      offload_snapshot
,      offload_hash_column
,      offload_sort_columns
,      offload_partition_functions
,      command_execution
FROM   /* slot: repo_user */.offload_metadata_v
WHERE  frontend_object_owner = :frontend_owner
AND    frontend_object_name  = :frontend_name;

-- name: list_offload_metadata_by_owner
SELECT frontend_object_owner
,      frontend_object_name
,      backend_object_owner
,      backend_object_name
,      offload_type
,      offload_range_type
,      offload_key
,      offload_high_value
,      offload_predicate_type
,      offload_predicate_value
,      offload_snapshot
,      offload_hash_column
,      offload_sort_columns
,      offload_partition_functions
,      command_execution
FROM   /* slot: repo_user */.offload_metadata_v
WHERE  frontend_object_owner = :frontend_owner
ORDER BY frontend_object_name;
